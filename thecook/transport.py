"""Serial I/O runs on a worker; the GUI alone owns widgets and packet parsing."""
from queue import Queue, Empty, Full
from threading import Event, Thread


class SerialWorker(Thread):
    def __init__(self, port, baudrate, parity="N", stopbits=1, bytesize=8):
        super().__init__(daemon=True)
        self.settings = dict(port=port, baudrate=baudrate, parity=parity,
                             stopbits=stopbits, bytesize=bytesize)
        self.events = Queue(maxsize=512)
        self.commands = Queue(maxsize=16)
        self.stopping = Event()

    def emit(self, kind, data=None):
        while not self.stopping.is_set():
            try:
                self.events.put((kind, data), timeout=0.1)
                return
            except Full:
                pass

    def run(self):
        try:
            import serial
            with serial.Serial(**self.settings, timeout=0.05, write_timeout=1,
                               xonxoff=False, rtscts=False, dsrdtr=False) as port:
                self.emit("connected", self.settings["port"])
                while not self.stopping.is_set():
                    try:
                        packet = self.commands.get_nowait()
                    except Empty:
                        packet = None
                    if packet is not None:
                        written = port.write(packet)
                        if written != len(packet):
                            raise OSError(f"Partial write: {written}/{len(packet)} bytes.")
                        self.emit("sent", packet)
                    data = port.read(min(max(port.in_waiting, 1), 8192))
                    if data:
                        self.emit("received", data)
        except Exception as exc:
            self.emit("error", str(exc))
        finally:
            # Always report termination, even after an explicit disconnect.
            try:
                self.events.put(("closed", None), timeout=0.2)
            except Full:
                pass

    def stop(self):
        self.stopping.set()
