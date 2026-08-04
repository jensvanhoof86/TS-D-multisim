import sys
import time
import math
import argparse
import serial
import serial.tools.list_ports
import threading
import json
import socket
import os

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime


# =========================================================
# TCP broadcast server (for 10012 datastream)
# =========================================================

class TcpBroadcastServer:
    def __init__(self, port: int, name: str):
        self.port = port
        self.name = name
        self.clients = []
        self.lock = threading.Lock()
        self.running = True

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print(f"[{self.name}] Listening on 0.0.0.0:{self.port} (TCP)")

    def _run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.port))
        srv.listen(5)
        srv.settimeout(1.0)

        while self.running:
            try:
                conn, addr = srv.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                print(f"[{self.name}] Client connected: {addr}")
                with self.lock:
                    self.clients.append(conn)
            except socket.timeout:
                continue
            except Exception:
                continue

        try:
            srv.close()
        except Exception:
            pass

    def send(self, data: bytes):
        if not data:
            return
        with self.lock:
            dead = []
            for c in self.clients:
                try:
                    c.sendall(data)
                except Exception:
                    dead.append(c)

            for d in dead:
                try:
                    d.close()
                except Exception:
                    pass
                try:
                    self.clients.remove(d)
                except ValueError:
                    pass

    def shutdown(self):
        self.running = False
        with self.lock:
            for c in self.clients:
                try:
                    c.close()
                except Exception:
                    pass
            self.clients.clear()


# =========================================================
# UDP sender (for 10013 LiveTools / FusionRX compatible)
# =========================================================

class UdpSender:
    def __init__(self, host: str, port: int, name: str):
        self.host = host
        self.port = port
        self.name = name
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Enable broadcast if using 255.255.255.255 or *.255, etc.
        if host == "255.255.255.255" or host.endswith(".255"):
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        print(f"[{self.name}] Sending to {self.host}:{self.port} (UDP)")

    def send(self, data: bytes):
        if not data:
            return
        try:
            self.sock.sendto(data, (self.host, self.port))
        except Exception:
            pass

    def shutdown(self):
        try:
            self.sock.close()
        except Exception:
            pass


# =========================================================
# HTTP GPS API server (TS-D Live)
# =========================================================

class GpsApiHandler(BaseHTTPRequestHandler):

    def _send_json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.lower()

        if path == "/ping":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"OK")
            return

        if path == "/api/sources":
            qs = parse_qs(parsed.query)
            ids = None

            if "ids" in qs:
                ids = set()
                for part in qs["ids"][0].split(","):
                    try:
                        ids.add(int(part))
                    except ValueError:
                        pass

            with gps_lock:
                values = list(gps_state.values())

            if ids is not None:
                values = [v for v in values if v["id"] in ids]

            values.sort(key=lambda x: x["id"])

            self._send_json({"sources": values})
            return

        self.send_response(404)
        self.end_headers()


gps_state = {}
gps_lock = threading.Lock()


def start_server(port):
    server = ThreadingHTTPServer(("localhost", port), GpsApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[HTTP] GPS API server running on http://localhost:{port}")
    return server


def update_source(id, lat, lng, heading, speed, altitude):
    with gps_lock:
        gps_state[id] = {
            "id": id,
            "lat": lat,
            "lng": lng,
            "heading": heading,
            "speed": speed,
            "altitude": altitude,
            # MATCH C# JavaScriptSerializer format
            "lastUpdateUtc": f"/Date({int(time.time() * 1000)})/"
        }


# -------------------------------------------------
# PKLDS helpers (legacy Eurolinx)
# -------------------------------------------------

def deg_to_ddmm(lat, lon):
    # Latitude
    lat_hemi = "N" if lat >= 0 else "S"
    lat = abs(lat)
    lat_deg = int(lat)
    lat_min = (lat - lat_deg) * 60

    # Longitude
    lon_hemi = "E" if lon >= 0 else "W"
    lon = abs(lon)
    lon_deg = int(lon)
    lon_min = (lon - lon_deg) * 60

    return lat_deg, lat_min, lat_hemi, lon_deg, lon_min, lon_hemi


def pkl_checksum(body):
    cs = 0
    for c in body:
        cs ^= ord(c)
    return f"{cs:02X}"


def build_pklds_sentence(vehicle_id, lat, lon):
    lat_deg, lat_min, lat_hemi, lon_deg, lon_min, lon_hemi = deg_to_ddmm(lat, lon)

    body = (
        f"PKLDS,,A,"
        f"{lat_deg:02d}{lat_min:07.4f},{lat_hemi},"
        f"{lon_deg:03d}{lon_min:07.4f},{lon_hemi},"
        f",,,,,E00,100,{vehicle_id},80,00,"
    )

    cs = pkl_checksum(body)
    sentence = f"${body}*{cs}\r\n"

    # Add legacy prefix: 39 32 03 02  (ASCII "92" + control bytes)
    prefix = bytes([0x39, 0x32, 0x03, 0x02])

    return prefix + sentence.encode()


# -------------------------------------------------
# NMEA helpers (GPGGA / LIVETOOLS)
# -------------------------------------------------

def nmea_checksum(s):
    cs = 0
    for c in s:
        cs ^= ord(c)
    return f"{cs:02X}"


def deg_to_nmea_lat(lat):
    hemi = "N" if lat >= 0 else "S"
    lat = abs(lat)
    d = int(lat)
    m = (lat - d) * 60
    return f"{d:02d}{m:07.4f}", hemi


def deg_to_nmea_lon(lon):
    hemi = "E" if lon >= 0 else "W"
    lon = abs(lon)
    d = int(lon)
    m = (lon - d) * 60
    return f"{d:03d}{m:07.4f}", hemi


def build_gga(hhmmss, lat, lon, alt):
    lat_s, lat_h = deg_to_nmea_lat(lat)
    lon_s, lon_h = deg_to_nmea_lon(lon)

    body = (
        f"GPGGA,{hhmmss}.00,"
        f"{lat_s},{lat_h},"
        f"{lon_s},{lon_h},"
        f"1,08,1.0,{alt:.1f},M,0.0,M,,"
    )
    return f"${body}*{nmea_checksum(body)}\r\n"


def build_rmc(hhmmss, lat, lon, speed_knots=0.0, course=0.0):
    lat_s, lat_h = deg_to_nmea_lat(lat)
    lon_s, lon_h = deg_to_nmea_lon(lon)

    ddmmyy = datetime.utcnow().strftime("%d%m%y")

    body = (
        f"GPRMC,{hhmmss}.00,A,"
        f"{lat_s},{lat_h},"
        f"{lon_s},{lon_h},"
        f"{speed_knots:.1f},"
        f"{course:.1f},"
        f"{ddmmyy},,,A"
    )
    return f"${body}*{nmea_checksum(body)}\r\n"


def build_gsa():
    body = (
        "GPGSA,A,3,"
        "01,03,04,17,19,11,31,28,"
        ",,,,,"
        "1.5,0.8,1.3"
    )
    return f"${body}*{nmea_checksum(body)}\r\n"


def build_gsv():
    s1 = (
        "GPGSV,2,1,08,"
        "01,25,140,39,"
        "03,50,081,44,"
        "04,75,140,46,"
        "11,11,310,45"
    )
    s2 = (
        "GPGSV,2,2,08,"
        "17,28,226,45,"
        "19,37,255,46,"
        "28,10,029,35,"
        "31,24,053,37"
    )

    return [
        f"${s1}*{nmea_checksum(s1)}\r\n",
        f"${s2}*{nmea_checksum(s2)}\r\n",
    ]


# -------------------------------------------------
# PRAVE helpers (Raveon AN177 $PRAVE sentence)
# -------------------------------------------------

# Used whenever --prave-id-map isn't given and no prave_id_map.json
# sits next to this script. Maps DSM hex ID -> PRAVE numeric "From ID".
DEFAULT_PRAVE_ID_MAP = {
    "00": 1000,
    "0B": 1001,
    "0C": 1002,
    "0D": 1003,
    "03": 1006,
}


def deg_to_prave_lat(lat):
    sign = "-" if lat < 0 else ""
    lat = abs(lat)
    d = int(lat)
    m = (lat - d) * 60
    return f"{sign}{d:02d}{m:07.4f}"


def deg_to_prave_lon(lon):
    sign = "-" if lon < 0 else ""
    lon = abs(lon)
    d = int(lon)
    m = (lon - d) * 60
    return f"{sign}{d:03d}{m:07.4f}"


def map_prave_id(dsm_id, id_map):
    if dsm_id in id_map:
        return id_map[dsm_id]
    return int(dsm_id, 16)


def load_prave_id_map(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {str(k).replace("DSM", "").upper(): int(v) for k, v in raw.items()}


def build_prave(from_id, hhmmss, lat, lon, alt, speed_kmh, course, to_id=0,
                 num_sats=8, gps_status=1, temp_c=0.0, voltage=0.0,
                 io_status=0, rssi=0, status="", odometer=None):
    lat_s = deg_to_prave_lat(lat)
    lon_s = deg_to_prave_lon(lon)

    fields = [
        "PRAVE",
        f"{from_id:04d}",
        f"{to_id:04d}",
        lat_s,
        lon_s,
        hhmmss,
        str(gps_status),
        str(num_sats),
        f"{alt:.0f}",
        f"{temp_c:.1f}",
        f"{voltage:.1f}",
        str(io_status),
        str(rssi),
        f"{speed_kmh:.0f}",
        f"{course:.0f}",
        status,
        "",  # spare
    ]
    if odometer is not None:
        fields.append(f"{odometer:.1f}")

    body = ",".join(fields)
    return f"${body}*{nmea_checksum(body)}\r\n"


# -------------------------------------------------
# DSM helpers
# -------------------------------------------------

def map_amp_id(dsm_id, enable_remap):
    if enable_remap and dsm_id == "00":
        return 0x64
    return int(dsm_id, 16)


def is_valid_hex_byte(s):
    return len(s) == 2 and all(c in "0123456789ABCDEF" for c in s)


def list_ports():
    ports = serial.tools.list_ports.comports()
    print("Available serial ports:")
    for p in ports:
        print(f"  {p.device}  - {p.description}")
    return ports


def progress_tag(dsm_id, hhmmss):
    t = f"{hhmmss[0:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}"
    tag = f"-DSM{dsm_id}({t})"
    return f"\033[36m{tag}\033[0m"  # cyan


def parse_dsm_line(line):
    ts_part, payload = line.strip().split("]", 1)
    timestamp_ms = int(ts_part[1:])

    payload = payload.strip()
    parts = payload.split(",")

    dsm_id = parts[0][4:]  # DSMxx (also works for $DSMxx -> yields xx)
    hhmmss = parts[1]
    lat = float(parts[2])
    lon = float(parts[3])
    alt = float(parts[4])
    speed = float(parts[5])
    course = float(parts[6])
    status = parts[7]

    return timestamp_ms, dsm_id, hhmmss, lat, lon, alt, speed, course, status


def hex_dump(data):
    return " ".join(f"0x{b:02X}" for b in data)


# -------------------------------------------------
# AMP / Kenwood binary encoding
# -------------------------------------------------

def encode_amp(dsm_id, lat_deg, lon_deg, alt_m, enable_remap=False):
    lat_rad = math.radians(lat_deg)
    lon_rad = math.radians(lon_deg)

    lat_i = int(lat_rad * 100_000_000)
    lon_i = int(lon_rad * 100_000_000)
    alt_i = int(alt_m)

    frame = bytearray()
    frame.append(map_amp_id(dsm_id, enable_remap))
    frame += lat_i.to_bytes(4, "big", signed=True)
    frame += lon_i.to_bytes(4, "big", signed=True)
    frame += alt_i.to_bytes(2, "big", signed=True)
    return bytes(frame)


# =========================================================
# Main
# =========================================================

parser = argparse.ArgumentParser()
parser.add_argument("--port", help="Serial port (e.g. COM4 or /dev/ttyUSB0)")
parser.add_argument("--protocol", help="Protocol: AMP19200 | KENWOOD4800 | DSM115200 | GPGGA4800 | LIVETOOLS4800 | PKLDS9600 | NMEA4800 | PRAVE115200")
parser.add_argument("--loop", action="store_true", help="Loop the input file continuously")

parser.add_argument("--enable-server", action="store_true", help="Enable HTTP GPS API server")
parser.add_argument("--server-port", type=int, default=5005, help="HTTP server port (default: 5005)")

parser.add_argument("--enable-remapDSM00", action="store_true", help="Remap DSM00 to ID 0x64 for AMP/KENWOOD protocols")

# UPDATED: LiveTools is UDP (FusionRX compatible)
parser.add_argument("--enable-livetools-server", action="store_true", help="Send LiveTools NMEA on UDP 10013 (FusionRX compatible)")
parser.add_argument("--livetools-ip", default="255.255.255.255", help="LiveTools UDP destination IP (default: 255.255.255.255 broadcast)")
parser.add_argument("--livetools-port", type=int, default=10013, help="LiveTools UDP destination port (default: 10013)")

# datastream remains TCP
parser.add_argument("--enable-datastream", action="store_true", help="Mirror main serial output bytes on TCP 10012")

parser.add_argument("file", help="DSM input file")
parser.add_argument("--nmea-out", dest="nmea_out", help="Optional NMEA output at 4800 baud (DSM00 only): RMC then 200ms then GGA")
parser.add_argument("--starttime", help="Start replay at or after this HHMMSS (e.g. 104750)")

parser.add_argument("--require-0F", action="store_true")
parser.add_argument("--ignore", action="append", default=[])
parser.add_argument("--id", help="DSM ID to filter (used with GPGGA/LIVETOOLS and livetools-server)")
parser.add_argument("--DSM-out", dest="dsm_out", help="Optional mirror output of raw DSM at 115200 baud (e.g. COM12)")

parser.add_argument("--prave-id-map", dest="prave_id_map", help="Optional JSON file mapping DSM hex IDs to PRAVE numeric 'From ID' values (PRAVE115200 only). Defaults to prave_id_map.json next to this script, or a built-in default if that file is absent.")
parser.add_argument("--prave-strict-map", dest="prave_strict_map", action="store_true", help="PRAVE115200 only: skip any DSM ID not present in the PRAVE ID map, instead of falling back to its raw hex value")

args = parser.parse_args()

args.ignore = [i.replace("DSM", "").upper() for i in args.ignore]

start_hhmmss = None
if args.starttime:
    if not args.starttime.isdigit() or len(args.starttime) != 6:
        print("Invalid --starttime format, expected HHMMSS (e.g. 104750)")
        sys.exit(1)
    start_hhmmss = int(args.starttime)


# -------------------------------------------------
# Select serial port
# -------------------------------------------------

if args.port:
    port = args.port
else:
    list_ports()
    port = input("\nSelect serial port: ").strip()

protocol = args.protocol.upper() if args.protocol else None

if protocol is None:
    print("\nSelect format:")
    print("1) AMP 19200")
    print("2) DSM 115200")
    print("3) GPGGA 4800")
    print("4) Kenwood 4800")
    print("5) LiveTools 4800")
    print("6) Kenwood PKLDS 9600")
    print("7) NMEA 4800 (GPRMC + 200ms + GPGGA)")
    print("8) PRAVE 115200 (Raveon $PRAVE)")

    choice = input("Choice: ").strip()

    protocol_map = {
        "1": "AMP19200",
        "2": "DSM115200",
        "3": "GPGGA4800",
        "4": "KENWOOD4800",
        "5": "LIVETOOLS4800",
        "6": "PKLDS9600",
        "7": "NMEA4800",
        "8": "PRAVE115200",
    }

    protocol = protocol_map.get(choice)
    if not protocol:
        print("Invalid selection")
        sys.exit(1)

# ---- protocol decoding ----

if protocol == "AMP19200":
    mode_name = "AMP"
    baud = 19200

elif protocol == "KENWOOD4800":
    mode_name = "Kenwood"
    baud = 4800

elif protocol == "DSM115200":
    mode_name = "DSM"
    baud = 115200

elif protocol == "GPGGA4800":
    mode_name = "GPGGA"
    baud = 4800
    if not args.id:
        args.id = input("Enter DSM ID to filter (e.g. DSM00): ").strip()
    args.id = args.id.replace("DSM", "").upper()

elif protocol == "LIVETOOLS4800":
    mode_name = "LIVETOOLS"
    baud = 4800
    if not args.id:
        args.id = input("Enter DSM ID to filter (e.g. DSM00): ").strip()
    args.id = args.id.replace("DSM", "").upper()

elif protocol == "PKLDS9600":
    mode_name = "PKLDS"
    baud = 9600

elif protocol == "PRAVE115200":
    mode_name = "PRAVE"
    baud = 115200

elif protocol == "NMEA4800":
    mode_name = "NMEA4800"
    baud = 4800
    if not args.id:
        args.id = input("Enter DSM ID to filter (e.g. DSM00): ").strip()
    args.id = args.id.replace("DSM", "").upper()

else:
    print(f"Unknown protocol: {protocol}")
    sys.exit(1)

# -------------------------------------------------
# PRAVE ID map (DSM hex ID -> PRAVE numeric "From ID")
# -------------------------------------------------

prave_id_map = dict(DEFAULT_PRAVE_ID_MAP)
if mode_name == "PRAVE":
    default_map_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prave_id_map.json")
    map_path = args.prave_id_map or default_map_path

    if os.path.exists(map_path):
        try:
            prave_id_map = load_prave_id_map(map_path)
            print(f"Loaded PRAVE ID map from {map_path}\n")
        except Exception as e:
            print(f"Failed to load PRAVE ID map from {map_path}: {e}")
            sys.exit(1)
    elif args.prave_id_map:
        print(f"PRAVE ID map file not found: {map_path}")
        sys.exit(1)
    else:
        print("No prave_id_map.json found next to script; using built-in default PRAVE ID map\n")

# If livetools UDP is enabled but we are not in a mode that already prompts for --id,
# prompt here so UDP 10013 knows which DSM ID to track.
if args.enable_livetools_server and mode_name not in ("GPGGA", "LIVETOOLS", "NMEA4800"):
    if not args.id:
        args.id = input("Enter DSM ID to filter for LiveTools UDP (e.g. DSM00): ").strip()
    args.id = args.id.replace("DSM", "").upper()

# -------------------------------------------------
# Open serial ports
# -------------------------------------------------

ser = serial.Serial(port, baud, timeout=1)
print(f"\nOpened {port} @ {baud} baud ({mode_name})\n")

dsm_ser = None
if args.dsm_out:
    try:
        dsm_ser = serial.Serial(args.dsm_out, 115200, timeout=1)
        print(f"Opened DSM output {args.dsm_out} @ 115200 baud\n")
    except Exception as e:
        print(f"Failed to open DSM-out port {args.dsm_out}: {e}")
        sys.exit(1)

nmea_ser = None
if args.nmea_out:
    try:
        nmea_ser = serial.Serial(args.nmea_out, 4800, timeout=1)
        print(f"Opened NMEA output {args.nmea_out} @ 4800 baud\n")
    except Exception as e:
        print(f"Failed to open NMEA-out port {args.nmea_out}: {e}")
        sys.exit(1)

# -------------------------------------------------
# Start servers
# -------------------------------------------------

http_server = None
if args.enable_server:
    http_server = start_server(args.server_port)

datastream_server = TcpBroadcastServer(10012, "DataStream") if args.enable_datastream else None
livetools_udp = UdpSender(args.livetools_ip, args.livetools_port, "LiveTools") if args.enable_livetools_server else None


# -------------------------------------------------
# Serial write wrapper (mirrors to TCP 10012 if enabled)
# -------------------------------------------------

def send_main(data: bytes):
    ser.write(data)
    if datastream_server:
        datastream_server.send(data)


# -------------------------------------------------
# LiveTools sender (reuses exact sentences as LIVETOOLS4800)
# -------------------------------------------------

def build_livetools_burst_bytes(hhmmss, lat, lon, alt, spd, crs) -> bytes:
    # Identical content order as LIVETOOLS4800 mode.
    gga = build_gga(hhmmss, lat, lon, alt).encode()
    gsa = build_gsa().encode()
    gsv_list = [g.encode() for g in build_gsv()]
    rmc = build_rmc(hhmmss, lat, lon, spd, crs).encode()
    return b"".join([gga, gsa] + gsv_list + [rmc])


def send_livetools_udp(hhmmss, lat, lon, alt, spd, crs, respect_serial_delays: bool):
    """
    If respect_serial_delays=True (when main mode is LIVETOOLS),
    we send chunks in the same cadence as serial mode (0.05s sleeps).
    Otherwise we send the same bytes as one combined UDP datagram (no extra delay).
    """
    if not livetools_udp:
        return

    if not respect_serial_delays:
        livetools_udp.send(build_livetools_burst_bytes(hhmmss, lat, lon, alt, spd, crs))
        return

    # cadence like serial LIVETOOLS4800
    livetools_udp.send(build_gga(hhmmss, lat, lon, alt).encode())
    time.sleep(0.05)

    livetools_udp.send(build_gsa().encode())
    time.sleep(0.05)

    for g in build_gsv():
        livetools_udp.send(g.encode())
        time.sleep(0.05)

    livetools_udp.send(build_rmc(hhmmss, lat, lon, spd, crs).encode())


# -------------------------------------------------
# Playback loop
# -------------------------------------------------

while True:
    last_ts = None
    started = False if start_hhmmss is not None else True

    with open(args.file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("["):
                continue

            try:
                ts, dsm_id, hhmmss, lat, lon, alt, spd, crs, status = parse_dsm_line(line)
                tag = progress_tag(dsm_id, hhmmss)
                hhmmss_i = int(hhmmss)

                update_source(
                    id=int(dsm_id, 16),
                    lat=lat,
                    lng=lon,
                    heading=crs,
                    speed=spd,
                    altitude=alt
                )

            except Exception:
                print("SKIP (unparsable):", line.strip())
                continue

            # -------------------------------------------------
            # Skip until start time reached
            # -------------------------------------------------
            if not started:
                if hhmmss_i < start_hhmmss:
                    continue

                started = True
                last_ts = None
                print(f"\n--- Starting replay at {hhmmss} ---\n")

            # -------------------------------------------------
            # Optional NMEA mirror output (DSM00 only)
            # -------------------------------------------------
            if nmea_ser and dsm_id == "00":
                rmc = build_rmc(hhmmss, lat, lon, spd, crs)
                gga = build_gga(hhmmss, lat, lon, alt)

                nmea_ser.write(rmc.encode())
                time.sleep(0.2)
                nmea_ser.write(gga.encode())

                print("NMEA TX:", rmc.strip())
                print("NMEA TX:", gga.strip())

            if not is_valid_hex_byte(dsm_id):
                print(f"SKIP (invalid DSM ID): DSM{dsm_id}")
                continue

            if args.require_0F and status != "0F":
                continue

            if dsm_id in args.ignore:
                continue

            # Serial-mode filters
            if mode_name in ("GPGGA", "LIVETOOLS", "NMEA4800") and dsm_id != args.id:
                continue

            if mode_name == "PRAVE" and args.prave_strict_map and dsm_id not in prave_id_map:
                print(f"SKIP (PRAVE unmapped): DSM{dsm_id}")
                continue

            # Timing based on log timestamps
            if last_ts is not None:
                time.sleep((ts - last_ts) / 1000.0)
            last_ts = ts

            # -------------------------------------------------
            # Optional DSM mirror output
            # -------------------------------------------------
            if dsm_ser:
                dsm_line = line.split("]", 1)[1].strip()
                dsm_ser.write(dsm_line.encode() + b"\r\n")

            # -------------------------------------------------
            # Optional LiveTools UDP output (ID-filtered)
            # -------------------------------------------------
            if livetools_udp and args.id and dsm_id == args.id:
                # If main mode is LIVETOOLS, we match serial cadence.
                # Otherwise, don't add extra sleeps; send one combined datagram.
                send_livetools_udp(hhmmss, lat, lon, alt, spd, crs, respect_serial_delays=(mode_name == "LIVETOOLS"))

            # -------------------------------------------------
            # Main serial output modes (mirrored to 10012 if enabled)
            # -------------------------------------------------
            if mode_name in ("AMP", "Kenwood"):
                data = encode_amp(
                    dsm_id,
                    lat,
                    lon,
                    alt,
                    enable_remap=args.enable_remapDSM00
                )
                send_main(data)
                print("TX:", hex_dump(data), tag)

            elif mode_name == "DSM":
                out = line.split("]", 1)[1].strip()
                send_main(out.encode() + b"\r\n")
                print("TX:", out, tag)

            elif mode_name == "GPGGA":
                gga = build_gga(hhmmss, lat, lon, alt)
                send_main(gga.encode())
                print("TX:", gga.strip(), tag)

            elif mode_name == "LIVETOOLS":
                gga = build_gga(hhmmss, lat, lon, alt)
                gsa = build_gsa()
                gsv_list = build_gsv()
                rmc = build_rmc(hhmmss, lat, lon, spd, crs)

                send_main(gga.encode())
                time.sleep(0.05)

                send_main(gsa.encode())
                time.sleep(0.05)

                for gsv in gsv_list:
                    send_main(gsv.encode())
                    time.sleep(0.05)

                send_main(rmc.encode())

                print("TX: LIVETOOLS burst", tag)

            elif mode_name == "NMEA4800":
                rmc = build_rmc(hhmmss, lat, lon, spd, crs)
                gga = build_gga(hhmmss, lat, lon, alt)

                send_main(rmc.encode())
                time.sleep(0.2)
                send_main(gga.encode())

                print("TX:", rmc.strip(), tag)
                print("TX:", gga.strip(), tag)

            elif mode_name == "PKLDS":
                vehicle_id = 1000 + int(dsm_id, 16)
                pkt = build_pklds_sentence(vehicle_id, lat, lon)
                send_main(pkt)
                print("TX: PKLDS", pkt, tag)

            elif mode_name == "PRAVE":
                from_id = map_prave_id(dsm_id, prave_id_map)
                prave = build_prave(from_id, hhmmss, lat, lon, alt, spd * 1.852, crs)
                send_main(prave.encode())
                print("TX:", prave.strip(), tag)

    if not args.loop:
        break

    print("\n--- Looping simulation ---\n")


print("Done.")
try:
    ser.close()
except Exception:
    pass

if dsm_ser:
    try:
        dsm_ser.close()
    except Exception:
        pass

if nmea_ser:
    try:
        nmea_ser.close()
    except Exception:
        pass

if http_server:
    try:
        http_server.shutdown()
    except Exception:
        pass

if livetools_udp:
    livetools_udp.shutdown()

if datastream_server:
    datastream_server.shutdown()