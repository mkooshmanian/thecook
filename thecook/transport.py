"""Link I/O runs on a worker; the GUI alone owns widgets and packet parsing."""
from queue import Queue, Empty, Full
import socket
from threading import Event, Thread


class LinkWorker(Thread):
    def __init__(self):
        super().__init__(daemon=True)
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
            with self.open_link() as link:
                self.emit("connected", self.endpoint)
                while not self.stopping.is_set():
                    try:
                        packet = self.commands.get_nowait()
                    except Empty:
                        packet = None
                    if packet is not None:
                        self.write(link, packet)
                        self.emit("sent", packet)
                    data = self.read(link)
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


class SerialWorker(LinkWorker):
    def __init__(self, port, baudrate, parity="N", stopbits=1, bytesize=8):
        super().__init__()
        self.settings = dict(port=port, baudrate=baudrate, parity=parity,
                             stopbits=stopbits, bytesize=bytesize)
        self.endpoint = port

    def open_link(self):
        import serial
        return serial.Serial(**self.settings, timeout=0.05, write_timeout=1,
                             xonxoff=False, rtscts=False, dsrdtr=False)

    def write(self, link, packet):
        written = link.write(packet)
        if written != len(packet):
            raise OSError(f"Partial write: {written}/{len(packet)} bytes.")

    def read(self, link):
        return link.read(min(max(link.in_waiting, 1), 8192))


class TCPWorker(LinkWorker):
    """TCP client for a raw binary stream, such as QEMU's TCP serial server."""

    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        address = f"[{host}]" if ":" in host else host
        self.endpoint = f"TCP {address}:{port}"

    def open_link(self):
        link = socket.create_connection((self.host, self.port), timeout=3)
        link.settimeout(0.05)
        return link

    def write(self, link, packet):
        # sendall handles partial socket writes; confirm only the full packet.
        link.settimeout(1)
        try:
            link.sendall(packet)
        finally:
            link.settimeout(0.05)

    def read(self, link):
        try:
            data = link.recv(8192)
        except socket.timeout:
            return b""
        if not data:
            raise ConnectionError("The remote host closed the TCP connection.")
        return data
