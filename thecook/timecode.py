"""CUC decoding from CCSDS 301.0-B-4, section 3.2.

Binary fractions are retained exactly. Calendar rendering never labels TAI as UTC.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

EPOCHS = ("Relative / unknown", "CCSDS 1958 (TAI)", "Custom (TAI)", "Unix 1970 (mission convention)")
MODES = ("CUC — implicit P-field", "CUC — explicit P-field", "Raw hexadecimal")


@dataclass(frozen=True)
class CUCConfig:
    mode: str = MODES[1]
    coarse_bytes: int = 4
    fine_bytes: int = 4
    epoch: str = EPOCHS[0]
    custom_epoch: str = "2000-01-01T00:00:00"

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError("Unknown timestamp decoding mode.")
        if not 1 <= self.coarse_bytes <= 7 or not 0 <= self.fine_bytes <= 10:
            raise ValueError("CUC supports 1–7 coarse bytes and 0–10 fine bytes.")
        if self.epoch not in EPOCHS:
            raise ValueError("Unknown CUC epoch setting.")
        if self.epoch == EPOCHS[2]:
            parse_epoch(self.custom_epoch)


def parse_epoch(value):
    try:
        epoch = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("Enter a custom TAI epoch as YYYY-MM-DDTHH:MM:SS.") from None
    if epoch.tzinfo is not None or epoch.microsecond:
        raise ValueError("The custom TAI epoch must use whole seconds without a UTC offset.")
    return epoch


def parse_pfield(data):
    if not data:
        raise ValueError("Missing CUC P-field.")
    first = data[0]
    identifier = (first >> 4) & 7
    if identifier not in (1, 2):
        raise ValueError("The P-field does not identify a supported CUC time code.")
    coarse = ((first >> 2) & 3) + 1
    fine = first & 3
    size = 1
    if first & 0x80:
        if len(data) < 2:
            raise ValueError("Truncated extended CUC P-field.")
        second = data[1]
        if second & 0x80:
            raise ValueError("CUC P-field extensions beyond two bytes are not supported.")
        coarse += (second >> 5) & 3
        fine += (second >> 2) & 7
        size = 2
    return size, coarse, fine, identifier


def decode_cuc(data: bytes, config=CUCConfig()) -> dict:
    coarse, fine = config.coarse_bytes, config.fine_bytes
    p_size, identifier = 0, None
    if config.mode == MODES[2]:
        return {"format": "raw", "raw": data.hex()}
    if config.mode == MODES[1]:
        p_size, coarse, fine, identifier = parse_pfield(data)
    expected = p_size + coarse + fine
    if len(data) != expected:
        raise ValueError(f"CUC timestamp length mismatch: {len(data)} bytes, expected {expected} "
                         f"({p_size} P-field + {coarse} coarse + {fine} fine).")
    whole = int.from_bytes(data[p_size:p_size + coarse], "big")
    fraction = int.from_bytes(data[p_size + coarse:], "big")
    bits = fine * 8
    denominator = 1 << bits
    # n / 2**bits = (n * 5**bits) / 10**bits: exact, with no float rounding.
    fraction_digits = str(fraction * 5**bits).zfill(bits).rstrip("0") if fraction else ""
    seconds = str(whole) + ("." + fraction_digits if fraction_digits else "")
    result = dict(format="CUC", raw=data.hex(), p_field=data[:p_size].hex(),
                  coarse_bytes=coarse, fine_bytes=fine, coarse_seconds=whole,
                  fine_value=fraction, fine_denominator=denominator,
                  elapsed_seconds=seconds, resolution_seconds=f"1/{denominator}")
    epoch_setting = EPOCHS[1] if identifier == 1 else config.epoch
    result["epoch"] = epoch_setting
    display_seconds = str(whole) + ("." + fraction_digits[:9] if fraction_digits else "")
    if len(fraction_digits) > 9:
        display_seconds += "…"
    result["display"] = f"{display_seconds} s since epoch"
    if epoch_setting == EPOCHS[0]:
        result["display"] += " (unspecified)"
        return result
    if epoch_setting == EPOCHS[1]:
        epoch, scale = datetime(1958, 1, 1), "TAI"
    elif epoch_setting == EPOCHS[2]:
        epoch, scale = parse_epoch(config.custom_epoch), "TAI"
    else:
        epoch, scale = datetime(1970, 1, 1), "POSIX (mission convention)"
    result["epoch_origin"] = epoch.isoformat()
    result["time_scale"] = scale
    try:
        calendar = epoch + timedelta(seconds=whole)
    except OverflowError:
        result["calendar_note"] = "Calendar value exceeds the supported year range; elapsed seconds remain exact."
        return result
    # Display up to nanoseconds, truncating rather than rounding into the next second.
    stamp = calendar.isoformat(sep=" ", timespec="seconds")
    if fraction_digits:
        stamp += "." + fraction_digits[:9]
        if len(fraction_digits) > 9:
            stamp += "…"
    result["calendar"] = stamp
    result["display"] = stamp
    return result
