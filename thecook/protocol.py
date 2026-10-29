"""CCSDS space packets, mission-tailored PUS headers and stream assembly.

Multi-byte fields are big-endian. CRC is CRC-16/CCITT-FALSE (0x1021,
init=0xffff, refin/refout=false, xorout=0). No serial link framing is added.
"""
from dataclasses import dataclass, field
import binascii
import re
import struct
from .timecode import CUCConfig, MODES, decode_cuc, parse_pfield

NAMES = {(17, 1): "Ping", (17, 2): "Ping reply",
         (1, 1): "Acceptance successful", (1, 2): "Acceptance failed",
         (1, 3): "Execution started", (1, 4): "Execution start failed",
         (1, 5): "Execution progress", (1, 6): "Execution progress failed",
         (1, 7): "Execution completed", (1, 8): "Execution failed"}


def crc16(data: bytes) -> int:
    return binascii.crc_hqx(data, 0xffff)


def parse_hex(value: str) -> bytes:
    value = re.sub(r"\s+", "", value)
    if len(value) % 2 or re.search(r"[^0-9a-fA-F]", value):
        raise ValueError("Invalid hexadecimal: enter pairs of digits 00–FF.")
    return bytes.fromhex(value)


def integer(value: str) -> int:
    """Decimal by default, hexadecimal only with a 0x prefix."""
    return int(value, 16 if value.lower().startswith("0x") else 10)


@dataclass(frozen=True)
class Profile:
    code: int = 2
    tm_time_bytes: int = 8
    time_config: CUCConfig = field(default_factory=CUCConfig)

    def __post_init__(self):
        if self.code not in (1, 2):
            raise ValueError("Only PUS ISIS and PUS-C are supported.")
        if not 0 <= self.tm_time_bytes <= 32:
            raise ValueError("Timestamp size must be between 0 and 32 bytes.")

    @property
    def name(self):
        return "PUS ISIS" if self.code == 1 else "PUS-C"

    @property
    def tc_source_bytes(self):
        return self.code

    @property
    def tm_destination_bytes(self):
        return self.code

    @property
    def tm_counter_bytes(self):
        return self.code


def build_tc(apid=812, sequence=0, service=17, subtype=1, source=0,
             ack=9, payload=b"", profile=Profile()) -> bytes:
    for name, value, upper in (("APID", apid, 2047), ("Sequence", sequence, 16383),
                               ("Service", service, 255), ("Subtype", subtype, 255),
                               ("ACK", ack, 15)):
        if not 0 <= value <= upper:
            raise ValueError(f"{name} must be between 0 and {upper}.")
    if not 0 <= source < 1 << (8 * profile.tc_source_bytes):
        raise ValueError("The source identifier does not fit the selected profile.")
    secondary = bytes([(profile.code << 4) | ack, service, subtype])
    secondary += source.to_bytes(profile.tc_source_bytes, "big")
    size = len(secondary) + len(payload) + 2
    if size > 65536:
        raise ValueError("Data exceeds the Space Packet length limit.")
    # Outgoing packets are always unsegmented (sequence flags = 0b11).
    packet = struct.pack(">HHH", 0x1800 | apid, 0xC000 | sequence, size - 1)
    packet += secondary + payload
    return packet + crc16(packet).to_bytes(2, "big")


def decode(packet: bytes, profile=Profile()) -> dict:
    if len(packet) < 8:
        raise ValueError("Packet too short.")
    identification, control, length = struct.unpack(">HHH", packet[:6])
    if len(packet) != length + 7:
        raise ValueError(f"Length mismatch: {len(packet)} instead of {length + 7}.")
    tc = bool(identification & 0x1000)
    result = dict(kind="TC" if tc else "TM", apid=identification & 0x7ff,
                  sequence=control & 0x3fff, flags=control >> 14,
                  ccsds_version=identification >> 13, length=len(packet),
                  length_field=length, crc_received=f"{int.from_bytes(packet[-2:], 'big'):04X}",
                  crc_calculated=f"{crc16(packet[:-2]):04X}",
                  crc_ok=crc16(packet[:-2]) == int.from_bytes(packet[-2:], "big"),
                  hex=packet.hex(), warnings=[])
    warnings = result["warnings"]
    if result["ccsds_version"] != 0:
        warnings.append("Unsupported CCSDS version.")
    if result["flags"] != 3:
        warnings.append("Segmented CCSDS packet: application reassembly is not supported.")
    if not identification & 0x800:
        result.update(name="No secondary header", payload=packet[6:-2].hex())
        return result
    if len(packet) < 11:
        raise ValueError("Truncated PUS header.")
    code = (packet[6] >> 4) & 7
    result.update(pus_code=code, service=packet[7], subtype=packet[8])
    result["name"] = NAMES.get((packet[7], packet[8]), "Application data")
    if code != profile.code:
        received_name = {1: "PUS ISIS", 2: "PUS-C"}.get(code, "an unsupported PUS variant")
        warnings.append(f"Received {received_name}; selected variant is {profile.name}.")
    if code not in (1, 2):
        warnings.append("Unknown PUS header; data shown as raw bytes.")
        result["payload"] = packet[9:-2].hex()
        return result
    # Header widths follow the received PUS variant, even if the selected
    # outgoing variant differs. Timestamp size remains mission-specific.
    wire_profile = Profile(code=code, tm_time_bytes=profile.tm_time_bytes)
    result["pus_variant"] = wire_profile.name
    offset = 9
    if tc:
        result["ack"] = packet[6] & 15
        size = wire_profile.tc_source_bytes
        end = offset + size
        if end > len(packet) - 2:
            raise ValueError("Truncated source identifier.")
        result["source"] = int.from_bytes(packet[offset:end], "big")
        offset = end
    else:
        counter_size = wire_profile.tm_counter_bytes
        if offset + counter_size > len(packet) - 2:
            raise ValueError("Truncated TM message type counter.")
        result["message_counter"] = int.from_bytes(packet[offset:offset + counter_size], "big")
        result["time_reference_status"] = packet[6] & 15
        offset += counter_size
        size = wire_profile.tm_destination_bytes
        if offset + size > len(packet) - 2:
            raise ValueError("Truncated TM destination identifier.")
        time_size = profile.tm_time_bytes
        if profile.time_config.mode == MODES[1]:
            try:
                p_size, coarse, fine, _ = parse_pfield(packet[offset + size:-2])
                time_size = p_size + coarse + fine
            except ValueError:
                # Keep the mission's fallback boundary; decode_cuc reports the
                # malformed P-field without hiding the primary/PUS fields.
                pass
        end = offset + size + time_size
        truncated = end > len(packet) - 2
        if truncated:
            end = len(packet) - 2
        result["destination"] = int.from_bytes(packet[offset:offset + size], "big")
        offset += size
        time_data = packet[offset:end]
        result["time_raw"] = time_data.hex()
        try:
            if truncated:
                result["undecoded_data"] = time_data.hex()
                raise ValueError(f"Truncated timestamp: {len(time_data)} bytes available, expected {time_size}; payload boundary is unknown.")
            result["time"] = decode_cuc(time_data, profile.time_config)
        except ValueError as exc:
            result["time_error"] = str(exc)
            warnings.append(f"Timestamp decoding: {exc}")
        offset = end
    payload = packet[offset:-2]
    result["payload"] = payload.hex()
    if not tc and packet[7] == 1 and 1 <= packet[8] <= 8:
        if len(payload) >= 4:
            pid, seq = struct.unpack(">HH", payload[:4])
            result["request_id"] = payload[:4].hex()
            result["request_apid"] = pid & 0x7ff
            result["request_sequence"] = seq & 0x3fff
            result["verification_data"] = payload[4:].hex()
        else:
            warnings.append("Verification Request ID missing or truncated.")
    return result


class PacketStream:
    """Assemble bare CCSDS packets, optionally recovering corrupted boundaries.

    By default only impossible primary headers are skipped. Live links can opt
    into CRC-assisted recovery: a complete valid packet inside an incomplete or
    CRC-invalid candidate takes precedence over that candidate's length field.
    This is a heuristic, since bare CCSDS has no unambiguous framing marker.
    """
    def __init__(self, resynchronize=False):
        self.buffer = bytearray()
        self.discarded = 0
        self.resynchronize = resynchronize

    def _recovery_offset(self, size):
        # Search only within the current candidate. A CRC-invalid packet followed
        # by a valid packet at its declared boundary must still be delivered.
        for offset in range(1, min(size, len(self.buffer) - 7)):
            if self.buffer[offset] >> 5 != 0:
                continue
            candidate_size = int.from_bytes(self.buffer[offset + 4:offset + 6], "big") + 7
            end = offset + candidate_size
            if candidate_size < 8 or end > len(self.buffer):
                continue
            if crc16(self.buffer[offset:end - 2]) == int.from_bytes(self.buffer[end - 2:end], "big"):
                return offset
        return None

    def feed(self, data: bytes) -> list[bytes]:
        self.buffer.extend(data)
        packets = []
        while len(self.buffer) >= 6:
            size = int.from_bytes(self.buffer[4:6], "big") + 7
            if self.buffer[0] >> 5 != 0 or size < 8:
                del self.buffer[0]
                self.discarded += 1
                continue
            if self.resynchronize and (
                len(self.buffer) < size
                or crc16(self.buffer[:size - 2]) != int.from_bytes(self.buffer[size - 2:size], "big")
            ):
                offset = self._recovery_offset(size)
                if offset is not None:
                    del self.buffer[:offset]
                    self.discarded += offset
                    continue
            if len(self.buffer) < size:
                break
            packets.append(bytes(self.buffer[:size]))
            del self.buffer[:size]
        return packets
