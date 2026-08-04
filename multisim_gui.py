# multisim_gui.py
# User-friendly Tkinter GUI wrapper around multisim.py (runs it as a subprocess)
#
# Requirements:
#   pip install pyserial
#
# Usage:
#   python multisim_gui.py
#
# Assumptions:
#   - multisim.py is in the SAME folder as this GUI script
#   - multisim.py is executed as: python multisim.py <file> [args...]

import os
import sys
import queue
import shutil
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import serial.tools.list_ports
except Exception:
    serial = None


APP_TITLE = "SteadyLink MultiSim GUI"


# Protocol -> (baud rate, short description, requires a --id DSM filter)
PROTOCOL_INFO = {
    "AMP19200":      (19200,  "AMP binary protocol (antenna tracking controllers)", False),
    "KENWOOD4800":   (4800,   "Kenwood binary protocol", False),
    "DSM115200":     (115200, "Raw DSM passthrough (forwards the DSM line as-is)", False),
    "GPGGA4800":     (4800,   "NMEA GPGGA sentence only", True),
    "LIVETOOLS4800": (4800,   "Full NMEA burst: GGA, GSA, GSV x2, RMC", True),
    "PKLDS9600":     (9600,   "Legacy Eurolinx PKLDS protocol", False),
    "NMEA4800":      (4800,   "GPRMC, wait 200ms, then GPGGA", True),
    "PRAVE115200":   (115200, "Raveon $PRAVE sentence (AN177), one per vehicle", False),
}

PROTOCOLS = list(PROTOCOL_INFO.keys())
ID_REQUIRED_PROTOCOLS = {p for p, (_, _, needs_id) in PROTOCOL_INFO.items() if needs_id}


def get_base_dir():
    # When frozen by PyInstaller (--onefile), __file__ points into the
    # bootloader's randomized temp extraction folder (%TEMP%\_MEIxxxxxx),
    # which is different on every run. Use the real exe's location instead.
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_python_executable():
    # When frozen, sys.executable is multisim_gui.exe itself, not a Python
    # interpreter, so it can't be used to run multisim.py. Fall back to a
    # system Python (same as the .bat files, which use the "py" launcher).
    if getattr(sys, "frozen", False):
        for candidate in ("py", "python"):
            found = shutil.which(candidate)
            if found:
                return found
        raise FileNotFoundError(
            "Could not find a Python interpreter (py/python) on PATH. "
            "multisim.py requires a system Python install to run."
        )
    return sys.executable


def list_com_ports():
    if serial is None:
        return []
    ports = []
    for p in serial.tools.list_ports.comports():
        label = f"{p.device}  —  {p.description}"
        ports.append((p.device, label))
    return ports


# =========================================================
# Small hover-tooltip helper
# =========================================================

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        try:
            self.tip.wm_attributes("-topmost", True)
        except Exception:
            pass
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tip, text=self.text, justify="left",
            background="#ffffe0", foreground="#000000",
            relief="solid", borderwidth=1,
            font=("Segoe UI", 9), wraplength=380, padx=6, pady=4,
        )
        label.pack()

    def hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


HELP_TEXT = """SteadyLink MultiSim - How to use this GUI

============================================================
QUICK START
============================================================
1. DSM log file
   Click "Browse..." and choose the .txt log file to replay.
   Each line looks like:
     [123456]DSM00,105704,50.12345,4.56789,120.0,30.5,180.0,0F
   Format: [timestamp]DSMxx,HHMMSS,lat,lon,alt,speed,course,status

2. Protocol
   Choose which output format to send on the main serial port.
   See the protocol table below for details on each one.

3. Main serial port
   Choose the COM port the simulator will transmit on.
   Click "Refresh" if a port you plugged in doesn't show up yet.

4. Options / Outputs (optional)
   Turn on loop playback, mirror outputs, TCP/HTTP servers, or
   filters as needed. Hover any control in the app for a short
   explanation, or read the full reference below.

5. Click "Start".
   The exact command line being run is printed at the top of the
   Console Output panel, so you can see (and copy) it.

6. Click "Stop" to terminate the simulator at any time.

============================================================
PROTOCOL REFERENCE
============================================================
"""

for _name, (_baud, _desc, _needs_id) in PROTOCOL_INFO.items():
    HELP_TEXT += f"  {_name:<15} {_baud:>7} baud   {_desc}"
    if _needs_id:
        HELP_TEXT += "   [requires DSM ID filter]"
    HELP_TEXT += "\n"

HELP_TEXT += """
============================================================
FIELD REFERENCE
============================================================

DSM log file
    The recorded telemetry log to replay. Required.

Protocol
    Output format written to the main serial port. Some
    protocols (GPGGA4800, LIVETOOLS4800, NMEA4800) only transmit
    ONE vehicle at a time, so they need a "DSM ID" filter below.

Main serial port
    The COM port the chosen protocol is transmitted on, at the
    baud rate shown in the protocol table (unless overridden).

Override baud rate
    Optional. Forces --port to open at a specific baud rate
    instead of the protocol's default. Leave blank to use the
    default baud for the selected protocol.

--loop
    When the end of the log file is reached, start over from the
    beginning automatically instead of stopping.

--enable-server / --server-port
    Starts a local HTTP API (default port 5005) that TS-D Live
    (or any HTTP client) can poll for live GPS positions of every
    vehicle seen in the log:
        GET http://localhost:<port>/ping
        GET http://localhost:<port>/api/sources

--enable-datastream (TCP 10012)
    Mirrors every byte written to the main serial port to any
    client connected to TCP port 10012. Works with any protocol.
    Useful for network debugging or feeding a virtual receiver.

--enable-livetools-server (TCP 10013)
    Starts a TCP server broadcasting LiveTools-format NMEA bursts
    (identical to LIVETOOLS4800 mode) to any client connected on
    TCP port 10013, filtered to the "DSM ID" below - independent
    of whichever protocol the main serial port is using.

--enable-remapDSM00
    Remaps vehicle DSM00 to tracking ID 0x64 (100 decimal). Only
    affects the AMP19200 / KENWOOD4800 binary protocols.

PRAVE ID map (json, optional)
    Only used by PRAVE115200. Optional JSON file mapping DSM hex
    IDs to the numeric "From ID" sent in the $PRAVE sentence, e.g.
    {"00": 1000, "0B": 1001}. If left blank, multisim.py looks for
    prave_id_map.json next to itself, and falls back to a built-in
    default (00->1000, 0B->1001, 0C->1002, 0D->1003, 03->1006) if
    neither is found.

--prave-strict-map
    Only affects PRAVE115200. Any DSM ID not found in the PRAVE ID
    map is skipped entirely instead of falling back to its raw hex
    value.

--require-0F
    Ignore any log line whose status byte is not "0F" (i.e. only
    process fixes flagged as valid/good).

DSM-out (mirror, 115200 baud)
    Optional second COM port that receives a raw copy of every
    DSM line processed, at 115200 baud, regardless of the main
    protocol.

NMEA-out (mirror, 4800 baud, DSM00 only)
    Optional second COM port that receives GPRMC then (200 ms
    later) GPGGA for vehicle DSM00 only, at 4800 baud, regardless
    of the main protocol.

DSM ID filter (DSMxx)
    Selects which vehicle's data to use for:
      - GPGGA4800 / LIVETOOLS4800 / NMEA4800 main output
      - the LiveTools TCP server (10013)
    Required whenever one of those is in use. Example: DSM00.

--starttime (HHMMSS)
    Skip all log lines before this time-of-day and start replay
    at (or just after) the first line at/after this timestamp.
    Example: 104750

--ignore (comma list)
    Comma-separated DSM IDs to skip entirely, e.g. "00,01" or
    "DSM00,DSM01".

============================================================
TIPS / TROUBLESHOOTING
============================================================
- If a protocol needs a DSM ID (see table above) or the LiveTools
  TCP server is enabled, the GUI requires the "DSM ID filter"
  field to be filled in before starting - otherwise multisim.py
  would silently wait for keyboard input that the GUI can never
  send, and it will look "stuck".
- "Access is denied" / "port already in use" when starting
  usually means another program (or a previous run of this tool)
  still has that COM port open. Close it and click Refresh.
- The Console Output panel shows exactly what multisim.py prints,
  including the full command line used, TX data, and any
  "SKIP (unparsable)" warnings from malformed log lines.
- You can run multiple instances of this GUI at once (e.g. one
  per vehicle) as long as each uses different COM ports/TCP ports.
"""


class MultiSimGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1080x760")
        self.minsize(940, 680)

        self.proc = None
        self.reader_thread = None
        self.stop_reader = threading.Event()
        self.log_queue = queue.Queue()
        self._label_to_device = {}

        self._build_ui()
        self._refresh_ports()

        self.after(100, self._drain_log_queue)

    # ---------------- UI ----------------
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))

        sim_tab = ttk.Frame(notebook, padding=10)
        help_tab = ttk.Frame(notebook, padding=0)
        notebook.add(sim_tab, text="Simulator")
        notebook.add(help_tab, text="Help / How to use")

        self._build_simulator_tab(sim_tab)
        self._build_help_tab(help_tab)

        # --- Log area (always visible, below the tabs) ---
        log_frame = ttk.LabelFrame(self, text="Console Output", padding=10)
        log_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, wrap="none")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        yscroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=yscroll.set)

        xscroll = ttk.Scrollbar(log_frame, orient="horizontal", command=self.log_text.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        self.log_text.configure(xscrollcommand=xscroll.set)

        self._log(f"{APP_TITLE} ready. See the \"Help / How to use\" tab for instructions.\n")

    def _build_help_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        text = scrolledtext.ScrolledText(parent, wrap="word", font=("Consolas", 9))
        text.grid(row=0, column=0, sticky="nsew")
        text.insert("1.0", HELP_TEXT)
        text.configure(state="disabled")

    def _build_simulator_tab(self, top):
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        # --- File ---
        ttk.Label(top, text="DSM log file:").grid(row=0, column=0, sticky="w")
        self.file_var = tk.StringVar()
        self.file_entry = ttk.Entry(top, textvariable=self.file_var)
        self.file_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 8))
        ToolTip(self.file_entry, "The recorded DSM telemetry log to replay.\nFormat per line:\n[timestamp]DSMxx,HHMMSS,lat,lon,alt,speed,course,status")
        browse_btn = ttk.Button(top, text="Browse...", command=self._pick_file)
        browse_btn.grid(row=0, column=4, sticky="ew")

        # --- Protocol ---
        ttk.Label(top, text="Protocol:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.protocol_var = tk.StringVar(value="AMP19200")
        proto = ttk.Combobox(top, textvariable=self.protocol_var, values=PROTOCOLS, state="readonly", width=18)
        proto.grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(10, 0))
        proto.bind("<<ComboboxSelected>>", lambda e: self._update_id_hint())
        ToolTip(proto, "Output format sent on the main serial port.\nSee the Help tab for the full protocol table.")

        # --- Port ---
        ttk.Label(top, text="Main serial port:").grid(row=1, column=2, sticky="w", pady=(10, 0))
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=28)
        self.port_combo.grid(row=1, column=3, sticky="ew", padx=(8, 8), pady=(10, 0))
        ToolTip(self.port_combo, "COM port the simulator transmits the main output on.")
        ttk.Button(top, text="Refresh", command=self._refresh_ports).grid(row=1, column=4, sticky="ew", pady=(10, 0))

        # --- Baud override ---
        ttk.Label(top, text="Override baud rate:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.override_baud_var = tk.StringVar(value="")
        baud_entry = ttk.Entry(top, textvariable=self.override_baud_var, width=18)
        baud_entry.grid(row=2, column=1, sticky="w", padx=(8, 8), pady=(10, 0))
        ToolTip(baud_entry, "Optional. Forces the main port to open at this baud\nrate instead of the protocol's default. Leave blank\nto use the protocol's default baud rate.")

        self.baud_hint = ttk.Label(top, text="", foreground="#666")
        self.baud_hint.grid(row=2, column=2, columnspan=3, sticky="w", pady=(10, 0))

        # --- Options row ---
        opts = ttk.LabelFrame(top, text="Options", padding=10)
        opts.grid(row=3, column=0, columnspan=5, sticky="ew", pady=(12, 0))
        opts.columnconfigure(0, weight=1)
        opts.columnconfigure(1, weight=1)
        opts.columnconfigure(2, weight=1)
        opts.columnconfigure(3, weight=1)

        self.loop_var = tk.BooleanVar(value=False)
        self.enable_server_var = tk.BooleanVar(value=False)
        self.server_port_var = tk.StringVar(value="5005")
        self.enable_datastream_var = tk.BooleanVar(value=False)
        self.enable_livetools_server_var = tk.BooleanVar(value=False)
        self.enable_remap_var = tk.BooleanVar(value=False)
        self.require_0f_var = tk.BooleanVar(value=False)

        c1 = ttk.Checkbutton(opts, text="--loop (restart at end of file)", variable=self.loop_var)
        c1.grid(row=0, column=0, sticky="w")
        ToolTip(c1, "When the end of the log file is reached, start over\nautomatically instead of stopping.")

        c2 = ttk.Checkbutton(opts, text="--enable-server (HTTP GPS API)", variable=self.enable_server_var)
        c2.grid(row=0, column=1, sticky="w")
        ToolTip(c2, "Starts a local HTTP API (GET /ping, GET /api/sources)\nfor TS-D Live or other clients to poll live positions.")

        ttk.Label(opts, text="--server-port").grid(row=0, column=2, sticky="e")
        sp_entry = ttk.Entry(opts, textvariable=self.server_port_var, width=8)
        sp_entry.grid(row=0, column=3, sticky="w")
        ToolTip(sp_entry, "TCP port for the HTTP GPS API server. Default: 5005.")

        c3 = ttk.Checkbutton(opts, text="--enable-datastream (TCP 10012)", variable=self.enable_datastream_var)
        c3.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ToolTip(c3, "Mirrors every byte sent to the main serial port to\nany client connected on TCP port 10012.")

        c4 = ttk.Checkbutton(opts, text="--enable-livetools-server (TCP 10013)", variable=self.enable_livetools_server_var)
        c4.grid(row=1, column=1, sticky="w", pady=(6, 0))
        ToolTip(c4, "Broadcasts LiveTools-format NMEA bursts on TCP 10013,\nfiltered by the DSM ID field below (required).")

        c5 = ttk.Checkbutton(opts, text="--enable-remapDSM00", variable=self.enable_remap_var)
        c5.grid(row=1, column=2, sticky="w", pady=(6, 0))
        ToolTip(c5, "Remaps DSM00 to tracking ID 0x64 (100 decimal).\nOnly affects AMP19200 / KENWOOD4800 protocols.")

        c6 = ttk.Checkbutton(opts, text="--require-0F", variable=self.require_0f_var)
        c6.grid(row=1, column=3, sticky="w", pady=(6, 0))
        ToolTip(c6, "Only process log lines whose status byte is \"0F\"\n(i.e. flagged as a valid/good fix).")

        ttk.Label(opts, text="PRAVE ID map (json, optional):").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.prave_id_map_var = tk.StringVar(value="")
        prave_map_entry = ttk.Entry(opts, textvariable=self.prave_id_map_var)
        prave_map_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        ToolTip(prave_map_entry, "Only used by PRAVE115200. Optional JSON file mapping\nDSM hex IDs to PRAVE numeric 'From ID' values. Leave\nblank to use prave_id_map.json next to multisim.py, or\nthe built-in default mapping.")
        ttk.Button(opts, text="Browse...", command=self._pick_prave_id_map).grid(row=2, column=3, sticky="w", pady=(6, 0))

        self.prave_strict_map_var = tk.BooleanVar(value=False)
        c7 = ttk.Checkbutton(opts, text="--prave-strict-map (skip unmapped IDs)", variable=self.prave_strict_map_var)
        c7.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ToolTip(c7, "Only affects PRAVE115200. Any DSM ID not found in the\nPRAVE ID map is skipped entirely instead of falling\nback to its raw hex value.")

        # --- Extra outputs / filters ---
        extras = ttk.LabelFrame(top, text="Outputs / Filters", padding=10)
        extras.grid(row=4, column=0, columnspan=5, sticky="ew", pady=(12, 0))
        extras.columnconfigure(1, weight=1)
        extras.columnconfigure(3, weight=1)

        # DSM-out
        ttk.Label(extras, text="DSM-out (115200):").grid(row=0, column=0, sticky="w")
        self.dsm_out_var = tk.StringVar(value="")
        self.dsm_out_combo = ttk.Combobox(extras, textvariable=self.dsm_out_var, state="readonly", width=28)
        self.dsm_out_combo.grid(row=0, column=1, sticky="w", padx=(8, 18))
        ToolTip(self.dsm_out_combo, "Optional second COM port that mirrors the raw DSM\nline for every vehicle, at 115200 baud.")

        # NMEA-out
        ttk.Label(extras, text="NMEA-out (4800, DSM00 only):").grid(row=0, column=2, sticky="w")
        self.nmea_out_var = tk.StringVar(value="")
        self.nmea_out_combo = ttk.Combobox(extras, textvariable=self.nmea_out_var, state="readonly", width=28)
        self.nmea_out_combo.grid(row=0, column=3, sticky="w", padx=(8, 0))
        ToolTip(self.nmea_out_combo, "Optional second COM port that mirrors GPRMC then\n(200ms later) GPGGA for DSM00 only, at 4800 baud.")

        # --id
        ttk.Label(extras, text="DSM ID filter (DSMxx):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.id_var = tk.StringVar(value="DSM00")
        id_entry = ttk.Entry(extras, textvariable=self.id_var, width=12)
        id_entry.grid(row=1, column=1, sticky="w", padx=(8, 18), pady=(8, 0))
        ToolTip(id_entry, "Which vehicle to use for GPGGA4800 / LIVETOOLS4800 /\nNMEA4800 output and the LiveTools TCP server.")

        self.id_hint = ttk.Label(extras, text="", foreground="#666")
        self.id_hint.grid(row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))
        self._update_id_hint()

        # --starttime
        ttk.Label(extras, text="--starttime (HHMMSS):").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.starttime_var = tk.StringVar(value="")
        st_entry = ttk.Entry(extras, textvariable=self.starttime_var, width=12)
        st_entry.grid(row=2, column=1, sticky="w", padx=(8, 18), pady=(8, 0))
        ToolTip(st_entry, "Skip log lines before this time and start replay\nat/after it. Example: 104750")

        # --ignore (comma)
        ttk.Label(extras, text="--ignore (comma list):").grid(row=2, column=2, sticky="w", pady=(8, 0))
        self.ignore_var = tk.StringVar(value="")
        ig_entry = ttk.Entry(extras, textvariable=self.ignore_var)
        ig_entry.grid(row=2, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        ToolTip(ig_entry, "Comma-separated DSM IDs to skip entirely,\ne.g. \"00,01\" or \"DSM00,DSM01\".")

        # --- Controls ---
        controls = ttk.Frame(top)
        controls.grid(row=5, column=0, columnspan=5, sticky="ew", pady=(12, 0))
        controls.columnconfigure(3, weight=1)

        self.start_btn = ttk.Button(controls, text="Start", command=self._start)
        self.start_btn.grid(row=0, column=0, padx=(0, 8))

        self.stop_btn = ttk.Button(controls, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=(0, 12))

        ttk.Button(controls, text="Clear Log", command=self._clear_log).grid(row=0, column=2)

    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="Select DSM log file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.file_var.set(path)

    def _pick_prave_id_map(self):
        path = filedialog.askopenfilename(
            title="Select PRAVE ID map (json)",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            self.prave_id_map_var.set(path)

    def _refresh_ports(self):
        ports = list_com_ports()
        labels = ["(none)"] + [label for _, label in ports]

        # Main port
        self.port_combo["values"] = labels
        # store mapping label->device
        self._label_to_device = {label: dev for dev, label in ports}
        self._label_to_device["(none)"] = ""

        # DSM-out and NMEA-out
        self.dsm_out_combo["values"] = ["(none)"] + [label for _, label in ports]
        self.nmea_out_combo["values"] = ["(none)"] + [label for _, label in ports]

        # if empty, select none
        if not self.port_var.get():
            self.port_var.set("(none)")
        if not self.dsm_out_var.get():
            self.dsm_out_var.set("(none)")
        if not self.nmea_out_var.get():
            self.nmea_out_var.set("(none)")

    def _update_id_hint(self):
        proto = self.protocol_var.get().upper().strip()
        baud, desc, needs_id = PROTOCOL_INFO.get(proto, (None, "", False))

        if needs_id:
            self.id_hint.config(text="Required by this protocol (main output is filtered to this DSM ID).")
        else:
            self.id_hint.config(text="Only needed if --enable-livetools-server is enabled.")

        if baud is not None:
            self.baud_hint.config(text=f"Default baud for {proto}: {baud}. {desc}.")
        else:
            self.baud_hint.config(text="")

    # ---------------- Process control ----------------
    def _build_args(self):
        # multisim.py path (same folder as the GUI exe/script)
        base_dir = get_base_dir()
        multisim_path = os.path.join(base_dir, "multisim.py")
        if not os.path.exists(multisim_path):
            raise FileNotFoundError(f"multisim.py not found next to GUI: {multisim_path}")

        in_file = self.file_var.get().strip()
        if not in_file or not os.path.exists(in_file):
            raise FileNotFoundError("Please select a valid DSM input file.")

        proto = self.protocol_var.get().strip()
        if not proto:
            raise ValueError("Please select a protocol.")

        # Map selected label to device
        main_label = self.port_var.get().strip()

        # Try mapping label -> device
        main_port = self._label_to_device.get(main_label, "").strip()

        # If mapping failed, assume user typed COM port manually
        if not main_port and main_label and main_label.lower() != "(none)":
            main_port = main_label

        if not main_port:
            raise ValueError("Please select a main serial port.")

        # DSM ID filter: required whenever the protocol needs it or the
        # LiveTools TCP server is on, otherwise multisim.py would silently
        # block waiting for keyboard input the GUI can never provide.
        dsm_id = self.id_var.get().strip()
        needs_id = proto in ID_REQUIRED_PROTOCOLS or self.enable_livetools_server_var.get()
        if needs_id and not dsm_id:
            raise ValueError(
                "A DSM ID filter (e.g. DSM00) is required for this protocol "
                "or when --enable-livetools-server is on."
            )

        python_exe = get_python_executable()
        # -u: unbuffered stdout, so TX lines stream into the log live instead
        # of sitting in Python's block-buffer until the process exits (stdout
        # isn't a real terminal once it's piped into this GUI).
        args = [python_exe, "-u", multisim_path, in_file, "--port", main_port, "--protocol", proto]

        ob = self.override_baud_var.get().strip()
        if ob:
            if not ob.isdigit():
                raise ValueError("Override baud rate must be a number, e.g. 9600.")
            args += ["--override-baudrate", ob]

        if self.loop_var.get():
            args.append("--loop")

        if self.enable_server_var.get():
            args.append("--enable-server")
            sp = self.server_port_var.get().strip()
            if sp:
                args += ["--server-port", sp]

        if self.enable_datastream_var.get():
            args.append("--enable-datastream")

        if self.enable_livetools_server_var.get():
            args.append("--enable-livetools-server")

        if self.enable_remap_var.get():
            args.append("--enable-remapDSM00")

        if self.require_0f_var.get():
            args.append("--require-0F")

        prave_map = self.prave_id_map_var.get().strip()
        if prave_map:
            args += ["--prave-id-map", prave_map]

        if self.prave_strict_map_var.get():
            args.append("--prave-strict-map")

        if dsm_id:
            args += ["--id", dsm_id]

        # DSM-out
        dsm_label = self.dsm_out_var.get()
        dsm_port = self._label_to_device.get(dsm_label, "").strip()
        if dsm_port:
            args += ["--DSM-out", dsm_port]

        # NMEA-out
        nmea_label = self.nmea_out_var.get()
        nmea_port = self._label_to_device.get(nmea_label, "").strip()
        if nmea_port:
            args += ["--nmea-out", nmea_port]

        # starttime
        st = self.starttime_var.get().strip()
        if st:
            if not st.isdigit() or len(st) != 6:
                raise ValueError("--starttime must be in HHMMSS format, e.g. 104750.")
            args += ["--starttime", st]

        # ignore list (comma separated)
        ign = self.ignore_var.get().strip()
        if ign:
            # allow "DSM00,DSM01" or "00,01"
            parts = [p.strip() for p in ign.split(",") if p.strip()]
            for p in parts:
                if not p.upper().startswith("DSM"):
                    p = "DSM" + p
                args += ["--ignore", p]

        return args

    def _start(self):
        if self.proc is not None:
            return

        try:
            args = self._build_args()
        except Exception as e:
            messagebox.showerror("Cannot start", str(e))
            return

        self._log("\n=== START ===\n")
        self._log("Command:\n  " + " ".join(args) + "\n\n")

        try:
            self.proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                cwd=get_base_dir(),
            )
        except Exception as e:
            self.proc = None
            messagebox.showerror("Failed to start", str(e))
            return

        self.stop_reader.clear()
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

    def _stop(self):
        if self.proc is None:
            return

        self._log("\n=== STOP requested ===\n")
        try:
            self.proc.terminate()
        except Exception:
            pass

        self.stop_reader.set()

        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def _reader_loop(self):
        assert self.proc is not None
        try:
            for line in self.proc.stdout:
                if self.stop_reader.is_set():
                    break
                self.log_queue.put(line)
        except Exception as e:
            self.log_queue.put(f"[GUI] Reader error: {e}\n")
        finally:
            try:
                rc = self.proc.wait(timeout=1)
            except Exception:
                rc = None
            self.log_queue.put(f"\n[GUI] multisim.py exited (code={rc}).\n")
            self.proc = None
            # re-enable start button on UI thread
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.stop_btn.configure(state="disabled"))

    def _drain_log_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self._log(line)
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def _clear_log(self):
        self.log_text.delete("1.0", "end")

    def _log(self, msg: str):
        self.log_text.insert("end", msg)
        self.log_text.see("end")

    def on_close(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.destroy()


def main():
    app = MultiSimGUI()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
