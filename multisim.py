# ================================
# MULTISIM v5 — CLEAN DROP-IN
# ================================

import sys
import time
import math
import argparse
import serial
import serial.tools.list_ports
import threading
import json
import socket

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from datetime import datetime

# =========================================================
# HTTP GPS API (TS-D Live)
# =========================================================

gps_state = {}
gps_lock = threading.Lock()


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
            with gps_lock:
                values = list(gps_state.values())
            values.sort(key=lambda x: x["id"])
            self._send_json({"sources": values})
            return

        self.send_response(404)
        self.end_headers()


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
            # match your old C# format
            "lastUpdateUtc": f"/Date({int(time.time() * 1000)})/"
        }

# =========================================================
# CONSOLE TAG
# =========================================================

def progress_tag(dsm_id, hhmmss):
    t = f"{hhmmss[0:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}"
    return f"\033[36m-DSM{dsm_id}({t})\033[0m"


# =========================================================
# TCP BROADCAST SERVER
# =========================================================

class TcpBroadcastServer:

    def __init__(self, port, name="TCP"):
        self.port = port
        self.name = name
        self.clients = []
        self.lock = threading.Lock()
        self.running = True

        self.thread = threading.Thread(
            target=self._run,
            daemon=True
        )
        self.thread.start()

        print(f"[{self.name}] Listening on port {self.port}")

    def _run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.port))
        srv.listen(5)

        while self.running:
            try:
                conn, addr = srv.accept()
                print(f"[{self.name}] Client connected: {addr}")
                with self.lock:
                    self.clients.append(conn)
            except Exception:
                pass

    def send(self, data: bytes):
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
                self.clients.remove(d)

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
# HELPERS
# =========================================================

def is_valid_hex_byte(s):
    return len(s) == 2 and all(c in "0123456789ABCDEF" for c in s.upper())


def hex_dump(data):
    return " ".join(f"0x{b:02X}" for b in data)


# =========================================================
# PKLDS
# =========================================================

def deg_to_ddmm(lat, lon):
    lat_hemi = "N" if lat >= 0 else "S"
    lon_hemi = "E" if lon >= 0 else "W"

    lat = abs(lat)
    lon = abs(lon)

    lat_deg = int(lat)
    lon_deg = int(lon)

    lat_min = (lat - lat_deg) * 60
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

    prefix = bytes([0x39, 0x32, 0x03, 0x02])
    return prefix + sentence.encode()


# =========================================================
# AMP
# =========================================================

def encode_amp(dsm_id, lat_deg, lon_deg, alt_m, enable_remap=False):

    if enable_remap and dsm_id == "00":
        id_byte = 0x64
    else:
        id_byte = int(dsm_id, 16)

    lat_rad = math.radians(lat_deg)
    lon_rad = math.radians(lon_deg)

    lat_i = int(lat_rad * 100_000_000)
    lon_i = int(lon_rad * 100_000_000)

    frame = bytearray()
    frame.append(id_byte)
    frame += lat_i.to_bytes(4, "big", signed=True)
    frame += lon_i.to_bytes(4, "big", signed=True)
    frame += int(alt_m).to_bytes(2, "big", signed=True)

    return bytes(frame)


# =========================================================
# PARSER
# =========================================================

def parse_dsm_line(line):
    """
    Returns:
    (timestamp_ms, dsm_id, hhmmss, lat, lon, alt, speed, course, status)
    """
    ts_part, payload = line.strip().split("]", 1)
    timestamp_ms = int(ts_part[1:])

    payload = payload.strip()      # removes whitespace + tabs around
    payload = payload.lstrip()     # extra safety

    # allow $DSMxx
    if payload.startswith("$"):
        payload = payload[1:]

    parts = payload.split(",")

    if len(parts) < 8 or not parts[0].startswith("DSM") or len(parts[0]) < 5:
        raise ValueError("Not a DSM sentence")

    dsm_id = parts[0][3:5]   # DSM00 -> "00" (more explicit & robust)
    hhmmss = parts[1]
    lat = float(parts[2])
    lon = float(parts[3])
    alt = float(parts[4])
    speed = float(parts[5])
    course = float(parts[6])
    status = parts[7]

    return timestamp_ms, dsm_id, hhmmss, lat, lon, alt, speed, course, status
# =========================================================
# ARGUMENTS
# =========================================================

parser = argparse.ArgumentParser()

parser.add_argument("file")
parser.add_argument("--port")
parser.add_argument("--protocol")
parser.add_argument("--loop", action="store_true")

parser.add_argument("--enable-livetools-server", action="store_true")
parser.add_argument("--enable-datastream", action="store_true")
parser.add_argument("--enable-server", action="store_true", help="Enable HTTP GPS API server")
parser.add_argument("--server-port", type=int, default=5005, help="HTTP server port (default: 5005)")

args = parser.parse_args()

http_server = None
if args.enable_server:
    http_server = start_server(args.server_port)


# =========================================================
# SERIAL
# =========================================================

port = args.port or "COM1"
protocol = (args.protocol or "").upper()

if protocol == "PKLDS9600":
    baud = 9600
elif protocol == "AMP19200":
    baud = 19200
else:
    baud = 115200

ser = serial.Serial(port, baud, timeout=1)
print(f"Opened {port} @ {baud}")


# =========================================================
# SERVERS
# =========================================================

livetools_server = TcpBroadcastServer(10013, "LiveTools") if args.enable_livetools_server else None
datastream_server = TcpBroadcastServer(10012, "DataStream") if args.enable_datastream else None


# =========================================================
# SERIAL SEND
# =========================================================

def send_serial(data: bytes, label="", tag=""):

    ser.write(data)

    if datastream_server:
        datastream_server.send(data)

    try:
        preview = data.decode(errors="ignore").strip()
    except Exception:
        preview = hex_dump(data)

    print(f"{label}: {preview} {tag}")


# =========================================================
# PLAYBACK
# =========================================================

while True:

    last_ts = None

    with open(args.file, "r", encoding="utf-8") as f:

        for line in f:

            if not line.startswith("["):
                continue

            try:
                ts, dsm_id, hhmmss, lat, lon, alt, spd, crs, status = parse_dsm_line(line)
            except Exception:
                print("SKIP:", line.strip())
                continue

            if not is_valid_hex_byte(dsm_id):
                print("SKIP invalid DSM:", dsm_id)
                continue

            update_source(
                id=int(dsm_id, 16),
                lat=lat,
                lng=lon,
                heading=crs,
                speed=spd,
                altitude=alt
            )

            tag = progress_tag(dsm_id, hhmmss)

            if last_ts is not None:
                time.sleep((ts - last_ts) / 1000.0)

            last_ts = ts

            if protocol == "PKLDS9600":
                vehicle_id = 1000 + int(dsm_id, 16)
                pkt = build_pklds_sentence(vehicle_id, lat, lon)
                send_serial(pkt, "TX PKLDS", tag)

            elif protocol == "AMP19200":
                data = encode_amp(dsm_id, lat, lon, alt, False)
                send_serial(data, "TX AMP", tag)

    if not args.loop:
        break


ser.close()
if http_server:
    http_server.shutdown()
print("Done.")