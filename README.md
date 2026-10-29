# The Cook

> **Prototype — for demonstration purposes only.** This project was
> "vibe-coded" with GPT-6.1 sol. It is not intended for production use.

A desktop dashboard for **cooking PUS telecommands** and inspecting telemetry
received through a serial port or a TCP connection. Built with Python, Tkinter
and pyserial.

## License

The application source code is licensed under the [MIT License](LICENSE).
ECSS reference documents are not distributed with this project. Their rights
remain with their respective owners.

## Install with pipx

The Cook requires **Python 3.10 or newer**, Tkinter and a graphical desktop.
The same pure-Python wheel can be installed on Linux, macOS and Windows;
Python, Tkinter and serial-device permissions must be available on the host.
Tkinter is a Python/system component, not a dependency pipx can download from PyPI.

On Debian/Ubuntu, install the prerequisites once:

```bash
sudo apt install pipx python3-tk python3-venv
pipx ensurepath
```

Open a new terminal after `pipx ensurepath`. Download the `.whl` file from the
[GitHub releases](https://github.com/mkooshmanian/thecook/releases), then install it:

```bash
pipx install ./thecook-0.3.0-py3-none-any.whl
thecook
```

Use the filename matching the downloaded version. pipx installs pyserial in an
isolated environment and exposes `thecook` in `~/.local/bin` on Linux. Keep the
wheel for installation; copying it directly into `~/.local/bin` does not install it.
Use a Python installation that includes Tkinter; if needed, select it explicitly
with `pipx install --python /usr/bin/python3 ./thecook-0.3.0-py3-none-any.whl`.

You can also install directly from GitHub without downloading a release:

```bash
pipx install 'git+https://github.com/mkooshmanian/thecook.git'
```

This requires Git and installs the current default branch. To install from an
existing local checkout, use `pipx install .` in the repository directory.

To update a wheel installation, download the new wheel and replace the installed
version (substitute the actual filename):

```bash
pipx install --force ./thecook-0.3.0-py3-none-any.whl
```

For a GitHub installation, use `pipx upgrade thecook`. To remove the application:
`pipx uninstall thecook`.

The project is not published on PyPI; a bare `pipx install thecook` is not the
installation method for this repository. Help and version are available without
opening a window:

```bash
thecook --help
thecook --version
```

## Run from source

For development:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python -m thecook
```

If pyserial and Tkinter are already installed in your Python environment, run
`python3 -m thecook` directly from the repository.

## Build a GitHub release

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install build twine
python -m build
python -m twine check dist/*
```

For version 0.3.0 this creates:

```text
dist/thecook-0.3.0-py3-none-any.whl
dist/thecook-0.3.0.tar.gz
```

The wheel includes the application, dependency metadata and MIT license; Python,
Tkinter and the ECSS documents are not bundled. The source archive also includes
the README and build configuration.

The **Build release packages** GitHub Actions workflow builds and checks both
archives, verifies installation with pipx, and creates a GitHub release with both
files when a `v`-prefixed tag is pushed. The tag must match the version in
`pyproject.toml` and point to a commit containing the workflow. For version 0.3.0,
commit and push the changes first, then run:

```bash
git tag -a v0.3.0 -m "The Cook 0.3.0"
git push origin v0.3.0
```

The workflow generates release notes automatically. A rerun uploads the packages
to the existing release. It uses GitHub's built-in token and does not need a
personal token or publish anything to PyPI. For future releases, update
`pyproject.toml` before creating the matching tag. GitHub Actions must be enabled
in the repository; the workflow requests `contents: write` for release creation.
A manual workflow run creates downloadable Actions artifacts without publishing
a release.

## Usage

The dashboard adapts to split-screen windows: controls wrap onto extra rows and
the TC and TM panels stack vertically when space is limited. Use the page's
vertical scrollbar or the mouse wheel over labels and panel backgrounds to reach
the rest of the interface. Text areas and the packet table keep their own scrolling.
Keyboard navigation also scrolls focused controls into view. Mission settings
can be scrolled in small windows as well.
Scrollbars update with the visible area and automatically hide when scrolling is
unnecessary, including the packet table's horizontal and vertical scrollbars.

1. Choose **Serial** or **TCP** in **01 Communication link**. The
   settings change immediately with the selected transport:

   - **Serial:** select a port from the list (or enter its path), baud rate and
     serial settings. Defaults are **115200, 8N1**, with no flow control.
   - **TCP:** enter the hostname / IP address and TCP port. Defaults
     are **localhost:4444**. The Cook connects as a TCP client.

   Click **Connect**. Disconnect before changing transport or connection settings;
   values are retained when switching between transports.
2. Choose compatibility profile or PUS-C, then enter the APID, sequence count, source ID,
   service, subtype and hexadecimal
   application data. Numeric fields accept decimal values or hexadecimal values
   with the `0x` prefix.
3. Review the preview and click **Send TC**. Packet length and CRC are calculated
   automatically. Outgoing CCSDS sequence flags are fixed to **`11` (unsegmented)**;
   there is no segmentation setting. The sequence count advances modulo 16384
   after the complete packet has been written to the link. This write
   confirmation is not a satellite acknowledgement.
4. Select a log entry to inspect its fields, raw bytes, received/calculated CRC
   and, for TM(1,1–8), the Request ID of the referenced TC.

The offline input accepts concatenated packets or successive fragments, using a
buffer separate from the live connection. **Reset RX buffers** discards any
incomplete packets in both buffers. Filters do not affect exports.

The log retains the **latest 2000 packets** and exports to JSON Lines, including
UTC reception timestamps, origin, mission profile and complete packet hex.
TX/RX counters count live serial or TCP traffic; offline input is labelled IMPORT.

On Linux, the current user needs read/write permission on the serial device
(often through the `dialout` group; group changes require a new login session).
Connection, disconnection and write errors are displayed in the interface.

### Connect to QEMU over TCP

Start QEMU with a raw TCP serial server, for example:

```bash
qemu-system-arm -machine mps2-an500 -cpu cortex-m7 -m 16M \
  -kernel /home/mkooshmanian/work/flight-software/build/output/flight-software.elf \
  -nographic -serial mon:stdio -serial tcp:localhost:4444,server,nowait
```

In step 1, select **TCP**, keep **localhost** and **4444**, then click
**Connect**. Telemetry is decoded in the usual traffic panel; **Send TC** writes
telecommands back through the same socket. For another server, change the host
and port. The TCP stream must carry raw binary CCSDS packets, just like the
serial link; no Telnet negotiation or text conversion is applied. A remote
closure or connection error is reported, and you can click **Connect** again.

## PUS variants and mission settings

Use the **PUS variant** selector immediately before **Service** in the TC
composer. Only **compatibility profile** and **PUS-C** are
supported. The default is PUS-C. The selector is disabled while a connection
is open; disconnect before switching variants. Switching preserves the APID,
Source ID, service and other entered values, clears incomplete RX buffers and
recalculates the TC preview.

PUS-C refers to [ECSS-E-ST-70-41C (15 April 2016)](https://ecss.nl/standards/).
Clauses 7.4.1–7.4.4 describe headers, clause 8.1 verification reports, and annex
B.1 the CRC. Obtain reference documents directly from ECSS; they are not included
or needed at runtime. The compatibility profile variant is implemented from the mission layout
and packets supplied with this project; no exhaustive compatibility profile specification is
available. PUS-A is not supported.

The generic differences between the supported variants are:

| Field | compatibility profile | PUS-C |
| --- | ---: | ---: |
| TC source ID field size | 1 byte (8 bits) | 2 bytes (16 bits) |
| TM message type counter field size | 1 byte (8 bits) | 2 bytes (16 bits) |
| TM destination ID field size | 1 byte (8 bits) | 2 bytes (16 bits) |
| Default timestamp size | 8 bytes | 8 bytes |

**Field size is different from field value.** For compatibility profile, a TC source ID field size
of 1 means the identifier occupies one byte. A Source ID value of 0 is encoded as
`00` in that byte; values 0–255 are allowed. For PUS-C, Source ID 0 is encoded as
`0000` in two bytes; values 0–65535 are allowed. **Mission settings** explains
this distinction and shows the fixed widths for the selected variant. Timestamp
and epoch can be adjusted there. Decoded CUC timestamps and their original raw
bytes are shown in packet details and exports. Neither supported layout adds a spare byte after the timestamp.

These two TC(17,1) packets are reproduced exactly (source 0, sequence 0, ACK 0x9):

```text
compatibility profile, APID 812: 1b2cc0000005191101001b73
PUS-C,    APID  85: 1855c000000629110100009021
```

The supplied compatibility profile TM(1,1) splits as follows:

```text
0b2cc0020012 | 10 | 01 | 01 | 00 | 00 | 4effa2228b964a00 | 1b2cc000 | b283
primary       PUS  svc  sub  ctr  dst  timestamp           request ID CRC
```

After the PUS control byte, service and subtype, **counter comes first,
then destination ID, then timestamp**. The timestamp is `4effa2228b964a00`;
its final `00` belongs to the timestamp. The two preceding `00` bytes are the
counter and destination ID, respectively.

The supplied TM stream splits into 25, 25 and 21 bytes, identified as TM(1,1),
TM(1,7) and TM(17,2). All three CRCs are valid. Incoming packets use their own
PUS variant to determine source/counter/destination widths; a mismatch with
the selected outgoing variant is reported as a warning. Timestamp size follows
the mission setting for an implicit P-field and is read from the packet for an
explicit P-field. Existing log entries keep their original decoding when settings
change; re-import an offline packet to apply new time settings.

## CUC onboard time

**Mission settings → Onboard time · CUC** configures decoding based on
CCSDS 301.0-B-4, section 3.2. The reference PDF is not included in release packages.
Only the CUC format is decoded; CDS, CCS and ASCII time formats are outside this
release's scope.

- **Implicit P-field:** the timestamp contains only the time field. Set the coarse
  (whole-second) and fine (binary-fraction) byte counts. Total timestamp size is
  calculated as their sum. Supported sizes are 1–7 coarse and 0–10 fine bytes.
- **Explicit P-field:** each timestamp starts with a one- or two-byte P-field.
  It determines the byte counts and packet timestamp boundary automatically.
  The configured raw/fallback size is used only if the P-field is malformed.
- **Raw hexadecimal:** retains the previous behaviour using the configured field
  size, without attempting CUC decoding.

All counters are big-endian. Fine time is a binary fraction, not an integer number
of milliseconds or microseconds:

```text
elapsed seconds = coarse + fine / 256**(number of fine bytes)
```

The default is **CUC with an explicit P-field**. The preamble describes the time
field and is excluded from the seconds count. For example, `1f4f3e3a68000000`
contains P-field `1f`, four coarse bytes `4f3e3a68` and three fine bytes `000000`.
It displays **2000-02-17 11:30:48** using the CCSDS epoch indicated
by the P-field.

For timestamps without a transmitted P-field, select implicit mode and configure
the byte counts and epoch. For example, the earlier `4effa2228b964a00` timestamp
with a 4+4 split represents `1325376034.54526197910308837890625` seconds since its
epoch. The application does not guess between explicit and implicit formats.

Choose the epoch explicitly:

- **Relative / unknown:** show elapsed seconds without inventing a calendar date.
- **CCSDS 1958 (TAI):** use 1958-01-01 00:00:00 TAI. An explicit CCSDS-epoch CUC
  P-field selects this epoch regardless of the manual setting.
- **Custom (TAI):** enter a whole-second TAI origin as `YYYY-MM-DDTHH:MM:SS`, with
  no UTC offset. An agency-defined P-field requires the mission's epoch setting.
- **Unix 1970 (mission convention):** interpret elapsed seconds as POSIX seconds
  since 1970-01-01. Use only if the flight software implements that convention;
  this is not standard CCSDS-epoch CUC handling.

Calendar display omits the time-scale suffix; the time scale is retained in
packet details and exports. No leap-second conversion is performed.
Received (UTC) in the log is the computer's reception time and is
separate from the decoded **Onboard time** column.

The journal, packet details and JSON Lines export retain raw bytes, exact elapsed
seconds, the fraction numerator/denominator and decoding settings. Displayed
fractions are truncated to at most nine decimal places (an ellipsis marks omitted
digits); exact decimal strings remain in the details/export, without float rounding.
Invalid timestamps produce a decoding warning while preserving packet CRC and
raw payload. Calendar overflow preserves the exact elapsed count.

## Scope and limitations

- CCSDS Space Packets with big-endian primary headers; length field = total size − 7.
- CRC-16/CCITT-FALSE: polynomial `0x1021`, initial value `0xFFFF`, no reflection,
  zero final XOR, transmitted big-endian. All packets are assumed to include a CRC.
- Generic TC formatting and recognition of service 1 reports and service 17 ping
  packets. Other payloads remain hexadecimal, without service/mission-specific
  parameter decoding.
- Serial and TCP transports expect **consecutive binary CCSDS packets**, without delimiters,
  SLIP, COBS, synchronization markers, frame encapsulation or ASCII hex conversion.
- Fragmented serial and TCP reads are assembled using the packet length field. Invalid
  CRCs remain visible. Outgoing packets are always unsegmented; received CCSDS
  segments are flagged and are not reassembled into application messages.
- Live serial and TCP input uses CRC-assisted resynchronization. If a candidate
  is incomplete or has an invalid CRC, a complete CRC-valid packet found inside
  it takes precedence; preceding bytes are discarded and counted in the status
  bar. This recovers, for example, from a duplicated first byte in a QEMU UART
  stream. CRC-invalid packets at their declared boundaries remain visible.
- Bare CCSDS has no unambiguous framing marker: recovery is a heuristic. A valid
  packet embedded in the payload of a fragmented larger packet can be mistaken
  for a new boundary. Offline input keeps strict length-based assembly. Without
  a complete CRC-valid recovery candidate, a plausible incomplete packet remains
  buffered; use **Reset RX buffers** to discard it.
- Settings are not persisted between sessions. PUS services are not exhaustively
  implemented.
