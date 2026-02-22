# multisim_gui.py
# Simple Tkinter GUI wrapper around multisim.py (runs it as a subprocess)
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
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import serial.tools.list_ports
except Exception:
    serial = None


APP_TITLE = "SteadyLink MultiSim GUI"


PROTOCOLS = [
    "AMP19200",
    "KENWOOD4800",
    "DSM115200",
    "GPGGA4800",
    "LIVETOOLS4800",
    "PKLDS9600",
]


def list_com_ports():
    if serial is None:
        return []
    ports = []
    for p in serial.tools.list_ports.comports():
        # show both device and description nicely
        label = f"{p.device}  —  {p.description}"
        ports.append((p.device, label))
    return ports


class MultiSimGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1050x720")
        self.minsize(900, 650)

        self.proc = None
        self.reader_thread = None
        self.stop_reader = threading.Event()
        self.log_queue = queue.Queue()

        self._build_ui()
        self._refresh_ports()

        self.after(100, self._drain_log_queue)

    # ---------------- UI ----------------
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        # --- File ---
        ttk.Label(top, text="DSM log file:").grid(row=0, column=0, sticky="w")
        self.file_var = tk.StringVar()
        self.file_entry = ttk.Entry(top, textvariable=self.file_var)
        self.file_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(top, text="Browse…", command=self._pick_file).grid(row=0, column=2, sticky="ew")

        # --- Protocol ---
        ttk.Label(top, text="Protocol:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.protocol_var = tk.StringVar(value="AMP19200")
        proto = ttk.Combobox(top, textvariable=self.protocol_var, values=PROTOCOLS, state="readonly", width=18)
        proto.grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(10, 0))
        proto.bind("<<ComboboxSelected>>", lambda e: self._update_id_hint())

        # --- Port ---
        ttk.Label(top, text="Main serial port:").grid(row=1, column=2, sticky="w", pady=(10, 0))
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=28)
        self.port_combo.grid(row=1, column=3, sticky="ew", padx=(8, 8), pady=(10, 0))
        ttk.Button(top, text="Refresh", command=self._refresh_ports).grid(row=1, column=4, sticky="ew", pady=(10, 0))

        # --- Options row ---
        opts = ttk.LabelFrame(top, text="Options", padding=10)
        opts.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(12, 0))
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

        ttk.Checkbutton(opts, text="--loop", variable=self.loop_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(opts, text="--enable-server", variable=self.enable_server_var).grid(row=0, column=1, sticky="w")
        ttk.Label(opts, text="--server-port").grid(row=0, column=2, sticky="e")
        ttk.Entry(opts, textvariable=self.server_port_var, width=8).grid(row=0, column=3, sticky="w")

        ttk.Checkbutton(opts, text="--enable-datastream (TCP 10012)", variable=self.enable_datastream_var).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(opts, text="--enable-livetools-server (TCP 10013)", variable=self.enable_livetools_server_var).grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Checkbutton(opts, text="--enable-remapDSM00", variable=self.enable_remap_var).grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(opts, text="--require-0F", variable=self.require_0f_var).grid(row=1, column=3, sticky="w", pady=(6, 0))

        # --- Extra outputs / filters ---
        extras = ttk.LabelFrame(top, text="Outputs / Filters", padding=10)
        extras.grid(row=3, column=0, columnspan=5, sticky="ew", pady=(12, 0))
        extras.columnconfigure(1, weight=1)
        extras.columnconfigure(3, weight=1)

        # DSM-out
        ttk.Label(extras, text="DSM-out (115200):").grid(row=0, column=0, sticky="w")
        self.dsm_out_var = tk.StringVar(value="")
        self.dsm_out_combo = ttk.Combobox(extras, textvariable=self.dsm_out_var, state="readonly", width=28)
        self.dsm_out_combo.grid(row=0, column=1, sticky="w", padx=(8, 18))

        # NMEA-out
        ttk.Label(extras, text="NMEA-out (4800, DSM00 only):").grid(row=0, column=2, sticky="w")
        self.nmea_out_var = tk.StringVar(value="")
        self.nmea_out_combo = ttk.Combobox(extras, textvariable=self.nmea_out_var, state="readonly", width=28)
        self.nmea_out_combo.grid(row=0, column=3, sticky="w", padx=(8, 0))

        # --id
        ttk.Label(extras, text="--id (DSMxx):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.id_var = tk.StringVar(value="DSM00")
        ttk.Entry(extras, textvariable=self.id_var, width=12).grid(row=1, column=1, sticky="w", padx=(8, 18), pady=(8, 0))

        self.id_hint = ttk.Label(extras, text="", foreground="#666")
        self.id_hint.grid(row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))
        self._update_id_hint()

        # --starttime
        ttk.Label(extras, text="--starttime (HHMMSS):").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.starttime_var = tk.StringVar(value="")
        ttk.Entry(extras, textvariable=self.starttime_var, width=12).grid(row=2, column=1, sticky="w", padx=(8, 18), pady=(8, 0))

        # --ignore (comma)
        ttk.Label(extras, text="--ignore (comma list):").grid(row=2, column=2, sticky="w", pady=(8, 0))
        self.ignore_var = tk.StringVar(value="")
        ttk.Entry(extras, textvariable=self.ignore_var).grid(row=2, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))

        # --- Controls ---
        controls = ttk.Frame(top)
        controls.grid(row=4, column=0, columnspan=5, sticky="ew", pady=(12, 0))
        controls.columnconfigure(2, weight=1)

        self.start_btn = ttk.Button(controls, text="Start", command=self._start)
        self.start_btn.grid(row=0, column=0, padx=(0, 8))

        self.stop_btn = ttk.Button(controls, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=(0, 12))

        ttk.Button(controls, text="Clear Log", command=self._clear_log).grid(row=0, column=3)

        # --- Log area ---
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

        self._log(f"{APP_TITLE} ready.\n")

    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="Select DSM log file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.file_var.set(path)

    def _refresh_ports(self):
        ports = list_com_ports()
        devices = [""] + [dev for dev, _ in ports]
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
        if proto in ("GPGGA4800", "LIVETOOLS4800"):
            self.id_hint.config(text="Used by this protocol (serial output is filtered to this DSM ID).")
        else:
            self.id_hint.config(text="Only needed if --enable-livetools-server is enabled.")

    # ---------------- Process control ----------------
    def _build_args(self):
        # multisim.py path (same folder)
        base_dir = os.path.dirname(os.path.abspath(__file__))
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

# Try mapping label → device
        main_port = self._label_to_device.get(main_label, "").strip()

# If mapping failed, assume user typed COM port manually
        if not main_port and main_label and main_label.lower() != "(none)":
            main_port = main_label

        if not main_port:
            raise ValueError("Please select a main serial port.")

        args = [sys.executable, multisim_path, in_file, "--port", main_port, "--protocol", proto]

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

        # --id: always pass if set (harmless if unused; multisim will ignore unless needed)
        dsm_id = self.id_var.get().strip()
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
                cwd=os.path.dirname(os.path.abspath(__file__)),
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