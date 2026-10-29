"""The Cook: a dependency-light desktop dashboard (Tk + pyserial)."""
import json
from collections import deque
from dataclasses import asdict, replace
from datetime import datetime, timezone
from queue import Empty, Full
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from .protocol import (Profile, PacketStream, build_tc, decode, parse_hex,
                       integer, crc16)
from .transport import SerialWorker
from .layout import AutoScrollbar, FlowFrame, ScrollPage

BG = "#10151d"
PANEL = "#19212c"
FG = "#e6edf6"
MUTED = "#98a9bf"
ACCENT = "#f4ad61"
PUS_VARIANTS = {"PUS ISIS": 1, "PUS-C": 2}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("The Cook · PUS kitchen")
        self.geometry(f"{min(1440, self.winfo_screenwidth() - 80)}x{min(940, self.winfo_screenheight() - 120)}")
        self.minsize(420, 360)
        self.configure(bg=BG)
        self.worker = None
        self.connected = False
        self.pending = False
        self.profile = Profile()
        self.stream = PacketStream()
        self.offline_stream = PacketStream()
        self.records = deque(maxlen=2000)
        self.counter = 0
        self.tx_count = 0
        self.rx_count = 0
        self.bad_count = 0
        self.current_packet = None
        self.vars = {}
        self._theme()
        self._layout()
        self.refresh_ports()
        self.preview()
        self._poll_job = self.after(50, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _theme(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=PANEL, foreground=FG, font=("DejaVu Sans", 10))
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=PANEL)
        s.configure("TLabel", background=PANEL)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Title.TLabel", background=BG, font=("DejaVu Sans", 27, "bold"))
        s.configure("Heading.TLabel", font=("DejaVu Sans", 12, "bold"))
        s.configure("TButton", padding=(12, 8), background="#2a3646", foreground=FG)
        s.map("TButton", background=[("active", "#3a4b60")])
        s.configure("Accent.TButton", background=ACCENT, foreground="#161b22")
        s.map("Accent.TButton", background=[("active", "#ffd09b")])
        s.configure("TEntry", fieldbackground=BG, foreground=FG, insertcolor=FG, padding=5)
        s.configure("TCombobox", fieldbackground=BG, background="#2a3646", foreground=FG, padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", BG)], foreground=[("readonly", FG)])
        s.configure("TCheckbutton", background=PANEL, foreground=FG)
        s.map("TCheckbutton", background=[("active", PANEL)])
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                    rowheight=31, borderwidth=0)
        s.configure("Treeview.Heading", background="#253142", foreground=MUTED, padding=6)
        s.map("Treeview", background=[("selected", "#35465d")])
        self.option_add("*TCombobox*Listbox.background", BG)
        self.option_add("*TCombobox*Listbox.foreground", FG)

    def card(self, parent, title):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=12)
        ttk.Label(frame, text=title, style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
        return frame

    def field(self, parent, key, label, default, values=None, width=12):
        box = ttk.Frame(parent, style="Card.TFrame")
        parent.add(box)
        ttk.Label(box, text=label, style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        var = tk.StringVar(value=str(default))
        self.vars[key] = var
        if values is not None:
            widget = ttk.Combobox(box, textvariable=var, values=values, width=width, state="readonly")
        else:
            widget = ttk.Entry(box, textvariable=var, width=width)
        widget.pack(fill="x")
        return widget

    def text_area(self, parent, height=3):
        return tk.Text(parent, height=height, width=1, bg=BG, fg=FG, insertbackground=FG,
                       relief="flat", padx=10, pady=9, wrap="word",
                       font=("DejaVu Sans Mono", 10), selectbackground="#35465d")

    def _layout(self):
        self.page = ScrollPage(self, BG)
        self.page.pack(fill="both", expand=True)
        content = self.page.content
        head = FlowFrame(content, padding=(16, 4))
        head.pack(fill="x")
        head.add(ttk.Label(head, text="the cook", style="Title.TLabel"))
        head.add(ttk.Label(head, text="/  SATELLITE PACKET KITCHEN", background=BG,
                           foreground=ACCENT))
        self.stats = tk.StringVar(value="TX 0   /   RX 0   /   CRC errors 0")
        self.wrapped_label(content, textvariable=self.stats, background=BG, foreground=MUTED).pack(fill="x", padx=18)
        serial_card = self.card(content, "01   Serial link")
        serial_card.pack(fill="x", padx=16, pady=12)
        row = FlowFrame(serial_card, style="Card.TFrame", item_anchor="s")
        row.pack(fill="x")
        self.port_box = self.field(row, "port", "Port", "", [], 23)
        row.add(ttk.Button(row, text="↻", command=self.refresh_ports))
        self.field(row, "baud", "Baud rate", "115200", width=10)
        self.field(row, "bits", "Bits", "8", ["8", "7"], 3)
        self.field(row, "parity", "Parity", "N", ["N", "E", "O"], 3)
        self.field(row, "stop", "Stop bits", "1", ["1", "1.5", "2"], 3)
        self.connect_button = ttk.Button(row, text="Connect", style="Accent.TButton", command=self.toggle_connection)
        row.add(self.connect_button)
        self.link_status = tk.StringVar(value="● Disconnected")
        row.add(ttk.Label(row, textvariable=self.link_status, foreground=ACCENT, wraplength=250))
        self.status = tk.StringVar(value="Ready · no bytes sent")
        self.wrapped_label(self, textvariable=self.status, background=BG, foreground=MUTED,
                           padding=(16, 8)).pack(side="bottom", fill="x", before=self.page)
        body = self.body = ttk.Frame(content)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        body.columnconfigure(0, weight=1, uniform="panels")
        body.columnconfigure(1, weight=1, uniform="panels")
        body.rowconfigure(0, weight=1)
        left = self.composer = self.card(body, "02   Cook a telecommand")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = self.telemetry = self.card(body, "03   Traffic & telemetry")
        right.grid(row=0, column=1, sticky="nsew")
        row = FlowFrame(left, style="Card.TFrame")
        row.pack(fill="x")
        self.field(row, "apid", "APID", 85, width=8)
        self.field(row, "seq", "Sequence", 0, width=8)
        self.field(row, "source", "Source ID", 0, width=8)
        row = FlowFrame(left, style="Card.TFrame")
        row.pack(fill="x")
        self.pus_box = self.field(row, "pus", "PUS variant", self.profile.name, list(PUS_VARIANTS), 14)
        self.pus_box.bind("<<ComboboxSelected>>", self.select_pus)
        self.field(row, "service", "Service", 17, width=8)
        self.field(row, "subtype", "Subtype", 1, width=8)
        ttk.Label(left, text="Requested success acknowledgements", style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
        row = FlowFrame(left, style="Card.TFrame")
        row.pack(fill="x")
        self.acks = []
        for text, mask in [("Acceptance", 8), ("Start", 4), ("Progress", 2), ("Completion", 1)]:
            v = tk.BooleanVar(value=mask in (8, 1))
            self.acks.append((v, mask))
            row.add(ttk.Checkbutton(row, text=text, variable=v, command=self.preview))
        ttk.Label(left, text="Application data · hexadecimal", style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
        self.payload = self.text_area(left, 2)
        self.payload.pack(fill="x")
        self.payload.bind("<KeyRelease>", lambda _: self.preview())
        ttk.Label(left, text="TC packet · automatic length and CRC", style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
        self.preview_text = self.text_area(left, 2)
        self.preview_text.pack(fill="x")
        self.preview_text.configure(state="disabled")
        self.preview_status = tk.StringVar()
        self.wrapped_label(left, textvariable=self.preview_status, foreground=ACCENT).pack(fill="x", pady=8)
        row = FlowFrame(left, style="Card.TFrame")
        row.pack(fill="x")
        self.send_button = ttk.Button(row, text="Send TC →", style="Accent.TButton", command=self.send, state="disabled")
        row.add(self.send_button)
        row.add(ttk.Button(row, text="Copy hex", command=self.copy_hex))
        ttk.Button(left, text="Mission settings…", command=self.profile_dialog).pack(anchor="w", pady=(16, 0))
        self.profile_label = tk.StringVar()
        self.update_profile_label()
        self.wrapped_label(left, textvariable=self.profile_label, style="Muted.TLabel").pack(fill="x", pady=8)
        self.wrapped_label(left, text="Raw binary stream · CRC-16/CCITT-FALSE",
                           style="Muted.TLabel").pack(fill="x", pady=4)
        bar = FlowFrame(right, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 8))
        self.filter = tk.StringVar(value="All")
        cb = ttk.Combobox(bar, textvariable=self.filter, values=["All", "TM", "TC", "CRC error"], state="readonly", width=13)
        bar.add(cb)
        cb.bind("<<ComboboxSelected>>", lambda _: self.render_table())
        bar.add(ttk.Button(bar, text="Export", command=self.export))
        bar.add(ttk.Button(bar, text="Clear", command=self.clear))
        table_box = ttk.Frame(right)
        table_box.pack(fill="both", expand=True)
        columns = ("time", "direction", "type", "apid", "seq", "crc")
        self.table = ttk.Treeview(table_box, columns=columns, show="headings", height=5, selectmode="browse")
        for key, name, width in zip(columns, ["Time", "Flow", "PUS (S, SS)", "APID", "SEQ", "CRC"], [100, 65, 120, 65, 60, 65]):
            self.table.heading(key, text=name)
            self.table.column(key, width=width, minwidth=45)
        scroll = AutoScrollbar(table_box, orient="vertical", command=self.table.yview)
        horizontal = AutoScrollbar(table_box, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        table_box.columnconfigure(0, weight=1)
        table_box.rowconfigure(0, weight=1)
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.tag_configure("bad", foreground="#ff8888")
        self.table.tag_configure("offline", foreground="#a4b4cd")
        self.table.bind("<<TreeviewSelect>>", self.select_packet)
        ttk.Label(right, text="Selected packet details", style="Muted.TLabel").pack(anchor="w", pady=(12, 5))
        self.details = self.text_area(right, 6)
        self.details.pack(fill="both", expand=True)
        self.details.insert("1.0", "Select a packet to inspect its fields.")
        self.details.configure(state="disabled")
        ttk.Label(right, text="Decode an offline hexadecimal stream", style="Muted.TLabel").pack(anchor="w", pady=(10, 4))
        self.raw = self.text_area(right, 2)
        self.raw.pack(fill="x")
        row = FlowFrame(right, style="Card.TFrame")
        row.pack(fill="x", pady=(6, 0))
        row.add(ttk.Button(row, text="Decode", command=self.import_hex))
        row.add(ttk.Button(row, text="Reset RX buffers", command=self.reset_stream))
        for key in ("apid", "seq", "source", "service", "subtype"):
            self.vars[key].trace_add("write", lambda *_: self.preview())
        self._wide_layout = None
        body.bind("<Configure>", self._resize_panels)

    def wrapped_label(self, parent, **kwargs):
        label = ttk.Label(parent, width=1, **kwargs)
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(1, event.width - 16)))
        return label

    def _resize_panels(self, event):
        wide = event.width >= 1080
        if wide == self._wide_layout:
            return
        self._wide_layout = wide
        if wide:
            self.body.columnconfigure(1, weight=1, uniform="panels")
            self.body.rowconfigure(1, weight=0)
            self.composer.grid_configure(row=0, column=0, padx=(0, 12), pady=0)
            self.telemetry.grid_configure(row=0, column=1, padx=0)
        else:
            self.body.columnconfigure(1, weight=0, uniform="")
            self.body.rowconfigure(1, weight=1)
            self.composer.grid_configure(row=0, column=0, padx=0, pady=(0, 12))
            self.telemetry.grid_configure(row=1, column=0, padx=0)

    def update_profile_label(self):
        p = self.profile
        self.profile_label.set(f"{p.name} · TC source ID size {p.tc_source_bytes} B\n"
                               f"TM counter / destination ID sizes {p.tm_counter_bytes} / {p.tm_destination_bytes} B · timestamp {p.tm_time_bytes} B")

    def select_pus(self, _=None):
        self.profile = replace(self.profile, code=PUS_VARIANTS[self.vars["pus"].get()])
        self.reset_stream()
        self.update_profile_label()
        self.preview()
        self.status.set(f"{self.profile.name} selected · APID and Source ID values unchanged")

    def preview(self):
        try:
            values = {k: integer(self.vars[k].get()) for k in ("apid", "source", "service", "subtype")}
            values["sequence"] = integer(self.vars["seq"].get())
            values["ack"] = sum(mask for var, mask in self.acks if var.get())
            self.current_packet = build_tc(**values, payload=parse_hex(self.payload.get("1.0", "end")), profile=self.profile)
            packet = self.current_packet
            value = packet.hex(" ").upper()
            self.preview_status.set(f"{len(packet)} bytes · CRC {packet[-2:].hex().upper()} · TC({values['service']},{values['subtype']})")
        except (ValueError, OverflowError) as exc:
            self.current_packet = None
            value = ""
            self.preview_status.set(str(exc))
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", value)
        self.preview_text.configure(state="disabled")
        self.send_button.configure(state="normal" if self.connected and self.current_packet and not self.pending else "disabled")

    def copy_hex(self):
        if self.current_packet:
            self.clipboard_clear()
            self.clipboard_append(self.current_packet.hex())
            self.status.set("TC copied to clipboard")

    def refresh_ports(self):
        try:
            from serial.tools import list_ports
            ports = list(list_ports.comports())
            self.port_box.configure(values=[p.device for p in ports])
            if ports and not self.vars["port"].get():
                self.vars["port"].set(ports[0].device)
            # Allow entering e.g. a stable /dev/serial/by-id path manually.
            self.port_box.configure(state="normal")
        except ImportError:
            self.link_status.set("pyserial missing · see README")

    def toggle_connection(self):
        if self.worker:
            self.worker.stop()
            self.connected = False
            self.connect_button.configure(state="disabled")
            self.link_status.set("Closing…")
            self.preview()
            return
        try:
            port = self.vars["port"].get().strip()
            baud = integer(self.vars["baud"].get())
            if not port or baud <= 0:
                raise ValueError("Select a port and a positive baud rate.")
            self.worker = SerialWorker(port, baud, self.vars["parity"].get(),
                                       float(self.vars["stop"].get()), int(self.vars["bits"].get()))
            self.stream = PacketStream()
            self.worker.start()
            self.pus_box.configure(state="disabled")
            self.connect_button.configure(text="Disconnect")
            self.link_status.set("Connecting…")
        except ValueError as exc:
            messagebox.showerror("Serial link", str(exc), parent=self)

    def send(self):
        if not self.connected or not self.current_packet or self.pending:
            return
        try:
            self.worker.commands.put_nowait(self.current_packet)
            self.pending = True
            self.status.set("Writing TC…")
            self.preview()
        except Full:
            self.status.set("Send queue is busy")

    def poll(self):
        worker = self.worker
        if worker:
            for _ in range(150):
                try:
                    kind, value = worker.events.get_nowait()
                except Empty:
                    break
                if kind == "connected":
                    self.connected = True
                    self.link_status.set(f"● {value}")
                elif kind == "received":
                    self.ingest(value, "RX", self.stream)
                elif kind == "sent":
                    self.pending = False
                    self.add_packet(value, "TX")
                    sequence = (int.from_bytes(value[2:4], "big") + 1) & 0x3fff
                    self.vars["seq"].set(str(sequence))
                    self.status.set(f"TC written to port · {len(value)} bytes")
                elif kind == "error":
                    self.connected = False
                    self.status.set(f"Serial error: {value}")
                    messagebox.showerror("Serial link", value, parent=self)
                elif kind == "closed":
                    self.connected = False
                    self.pending = False
                    self.worker = None
                    self.link_status.set("● Disconnected")
                    self.connect_button.configure(text="Connect", state="normal")
                    self.pus_box.configure(state="readonly")
                    if self.stream.buffer:
                        self.status.set(f"Disconnected · {len(self.stream.buffer)} incomplete bytes in RX buffer")
                    break
            self.preview()
        self._poll_job = self.after(50, self.poll)

    def ingest(self, data, origin, stream):
        for packet in stream.feed(data):
            self.add_packet(packet, origin)
        self.status.set(f"{origin} · {len(data)} bytes read · buffer {len(stream.buffer)} B · discarded bytes {stream.discarded}")

    def add_packet(self, packet, origin):
        try:
            record = decode(packet, self.profile)
        except ValueError as exc:
            # Retain malformed packets in the log for investigation/export.
            record = dict(kind="?", name="Unable to decode", hex=packet.hex(),
                          crc_ok=crc16(packet[:-2]) == int.from_bytes(packet[-2:], "big"),
                          decode_error=str(exc), warnings=[str(exc)], length=len(packet))
        self.counter += 1
        record.update(id=str(self.counter), origin=origin, profile=asdict(self.profile),
                      received_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        if len(self.records) == self.records.maxlen:
            old = self.records[0]["id"]
            if self.table.exists(old):
                self.table.delete(old)
        self.records.append(record)
        if origin == "TX":
            self.tx_count += 1
        elif origin == "RX":
            self.rx_count += 1
        if not record["crc_ok"] or record.get("decode_error"):
            self.bad_count += 1
        self.stats.set(f"TX {self.tx_count}   /   RX {self.rx_count}   /   CRC / decoding errors {self.bad_count}   ·   log {len(self.records)}/2000")
        if self.matches(record):
            self.insert_row(record)
            self.table.see(record["id"])

    def matches(self, r):
        f = self.filter.get()
        return f == "All" or (f == "CRC error" and not r["crc_ok"]) or f == r["kind"]

    def insert_row(self, r):
        packet_type = f"{r.get('service', '?')}, {r.get('subtype', '?')}"
        self.table.insert("", "end", iid=r["id"], values=(r["received_at"][11:23],
                          r["origin"], f"{r['kind']} ({packet_type})", r.get("apid", "?"),
                          r.get("sequence", "?"), "OK" if r["crc_ok"] else "INVALID"),
                          tags=("bad" if not r["crc_ok"] or r.get("decode_error") else "offline" if r["origin"] != "RX" else "",))

    def render_table(self):
        self.table.delete(*self.table.get_children())
        for r in self.records:
            if self.matches(r):
                self.insert_row(r)

    def select_packet(self, _=None):
        selection = self.table.selection()
        if not selection:
            return
        record = next((r for r in self.records if r["id"] == selection[0]), None)
        if record:
            summary = [record['name'],
                       f"{record['kind']} · APID {record.get('apid', '?')} · sequence {record.get('sequence', '?')} · {record['length']} bytes",
                       f"CRC: {'OK' if record['crc_ok'] else 'INVALID'}"]
            if 'request_id' in record:
                summary.append(f"Referenced TC: APID {record['request_apid']} · sequence {record['request_sequence']}")
            if record['warnings']:
                summary.extend(record['warnings'])
            text = "\n".join(summary) + "\n\n" + json.dumps(record, indent=2, ensure_ascii=False)
            self.details.configure(state="normal")
            self.details.delete("1.0", "end")
            self.details.insert("1.0", text)
            self.details.configure(state="disabled")

    def import_hex(self):
        try:
            data = parse_hex(self.raw.get("1.0", "end"))
            if not data:
                raise ValueError("Enter a hexadecimal stream.")
            self.ingest(data, "IMPORT", self.offline_stream)
            self.raw.delete("1.0", "end")
        except ValueError as exc:
            messagebox.showerror("Decoding", str(exc), parent=self)

    def reset_stream(self):
        self.stream = PacketStream()
        self.offline_stream = PacketStream()
        self.status.set("Serial and offline RX assembly buffers reset")

    def clear(self):
        self.records.clear()
        self.table.delete(*self.table.get_children())
        self.tx_count = self.rx_count = self.bad_count = 0
        self.stats.set("TX 0   /   RX 0   /   CRC errors 0")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")

    def export(self):
        filename = filedialog.asksaveasfilename(parent=self, defaultextension=".jsonl",
                                               filetypes=[("JSON Lines log", "*.jsonl")])
        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    for record in self.records:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                self.status.set(f"{len(self.records)} packets exported")
            except OSError as exc:
                messagebox.showerror("Export", str(exc), parent=self)

    def profile_dialog(self):
        if self.worker:
            messagebox.showinfo("Mission settings", "Disconnect the serial link before changing mission settings.", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("Mission settings")
        dialog.configure(bg=PANEL)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry(f"{min(680, self.winfo_width())}x{min(760, self.winfo_height())}")
        dialog.minsize(320, 300)
        page = ScrollPage(dialog, PANEL)
        page.pack(fill="both", expand=True)
        frame = ttk.Frame(page.content, style="Card.TFrame", padding=16)
        frame.pack(fill="both", expand=True)
        p = self.profile
        self.wrapped_label(frame, text=p.name, style="Heading.TLabel").pack(fill="x")
        self.wrapped_label(frame, text="Choose ISIS or C using the PUS variant selector before Service.",
                  style="Muted.TLabel").pack(fill="x", pady=(8, 16))
        for label, size in (("TC source ID field size", p.tc_source_bytes),
                            ("TM message type counter field size", p.tm_counter_bytes),
                            ("TM destination ID field size", p.tm_destination_bytes)):
            self.wrapped_label(frame, text=f"{label}: {size} byte(s) ({size * 8} bits)").pack(fill="x", pady=3)
        self.wrapped_label(frame, text=(
            "Field size and field value are different.\n"
            f"TC source ID size = {p.tc_source_bytes} byte(s) is the space this field occupies in the packet.\n"
            "Source ID in the composer is the numeric identifier to encode.\n"
            f"For example, Source ID = 0 is encoded as {'00' * p.tc_source_bytes}.\n"
            f"Allowed Source ID values: 0–{(1 << (8 * p.tc_source_bytes)) - 1}."),
            style="Muted.TLabel").pack(fill="x", pady=16)
        self.wrapped_label(frame, text="TM timestamp field size · bytes").pack(fill="x", pady=(4, 3))
        time_size = tk.StringVar(value=str(p.tm_time_bytes))
        ttk.Entry(frame, textvariable=time_size).pack(fill="x")
        self.wrapped_label(frame, text=(
            "TM layout after the PUS control byte, service and subtype:\n"
            f"counter ({p.tm_counter_bytes} B) → destination ID ({p.tm_destination_bytes} B) → timestamp.\n"
            "There is no spare byte after the timestamp in these supported layouts.\n"
            "Timestamps are displayed as raw hexadecimal bytes.\n"
            "Existing log entries keep their original decoding."),
            style="Muted.TLabel").pack(fill="x", pady=16)
        def apply():
            try:
                updated = replace(self.profile, tm_time_bytes=integer(time_size.get()))
            except ValueError as exc:
                messagebox.showerror("Mission settings", str(exc), parent=dialog)
                return
            self.profile = updated
            self.reset_stream()
            self.update_profile_label()
            self.preview()
            dialog.destroy()
        ttk.Button(frame, text="Apply", style="Accent.TButton", command=apply).pack(anchor="e", pady=8)

    def close(self):
        self.after_cancel(self._poll_job)
        if self.worker:
            self.worker.stop()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
