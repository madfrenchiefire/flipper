# Controlling an iShow 2.3 laser box from Python

## What IS.exe revealed (read this first)

Decompiling iShow 2.3's `IS.exe` showed that **the software never talks USB**.
Its only output path (`hwmain.hwout.sendout`) streams frames over **TCP to
`192.168.1.172`, port 4000**. `CyUSB.dll` ships in the folder, but IS.exe never
loads it.

**But the board has no network hardware.** The photo of the "Guicard13" board (2011-12-10) shows:

Parts confirmed from close-up photos:

- **U1: Cypress CY7C68013A-56PVXC (FX2LP)**, the USB chip, with a 24 MHz crystal.
- **U3: 24C01 EEPROM**, only 128 bytes. That is enough for the USB ID (`3333:6666`) and nothing else.
  The FX2 therefore runs no program until the PC uploads firmware into it each time the box is
  plugged in. On Windows this was done by the Cypress driver (CyUSB.sys plus a firmware script/hex
  named in its `.inf`).
- **U6: STC90C52RC**, an 8051 microcontroller with its own 24 MHz crystal and a serial programming
  header (`ISP`: G R T V). It sits between the FX2 and the outputs and most likely does the timing.
- **U4: TI TLC7528C**, a *dual 8-bit* DAC. These are the X and Y outputs, so **positions are 8-bit
  (0–255)**, matching IS.exe.
- **U2: LM324**, a quad op-amp that turns the DAC outputs into ILDA X/Y signals.
- **U5: 74HC08**, four AND gates feeding the ILDA colour pins. **Colours are on/off (TTL)**: red,
  green and blue are each either fully on or off (7 colours plus blank), with no dimming.
- An **A0512S** module makes the ±12 V supply.
- **No Ethernet chip or transformer.** The RJ45 jack is probably DMX or a link port.

So the box is really a USB device. iShow 2.3 sends to 192.168.1.172:4000, so either this IS.exe was
built for a network box, or a separate helper program received that data and passed it on over USB
(the most likely user of `CyUSB.dll`). That helper, or the firmware file it uploads, is the missing
piece. Look in the iShow folder for other `.exe` files and for `.hex`/`.iic`/`.spt`/`.bix`/`.sys` files.

The decoded protocol, implemented in `ishow_net.py`:

- **Per chunk (up to 15000 bytes):** open a TCP connection to the box on port 4000.
  Read 20 bytes; the first 4 are a little-endian int32 status. If the status is
  ≤ 0 the box is busy, so close and retry.
- **Header (8 bytes):** speed×2, "je", colour setting, 1 if the frame fits in
  one chunk (else 0), then `04 05 06 07`.
- **Payload:** the point bytes, then close the connection.
- **Each point is 6 bytes:** `X, Y, R, I, B, G`, all 0–255, with the centre at 127.5.
  I = 0.299R + 0.587G + 0.114B.
- **Frame end:** the frame ends with the last position repeated, blanked.
- **Streaming:** iShow re-sends the current frame continuously. The status reply
  is the flow control.

```
python fake_box.py                                   # terminal 1: simulated box
python ishow_net.py --ip 127.0.0.1 --shape square    # terminal 2
python ishow_net.py --shape circle --seconds 10      # the real box at 192.168.1.172
```

```python
from ishow_net import IShowNet
from ishow_dac import Point

with IShowNet() as dac:                  # 192.168.1.172:4000
    while True:
        dac.send_frame([Point(-0.5, 0, r=1), Point(0.5, 0, r=1)])
```

The USB-capture tools below (`probe.py`, `analyze_capture.py`, `ishow_dac.py`)
are the route for this USB board. The data format above is still the best guess for the points.

| File | What it does |
|---|---|
| `probe.py` | Finds the box and lists its USB IDs, endpoints and chip type |
| `analyze_capture.py` | Reads a Wireshark capture: start-up commands, packet header, bytes per point |
| `protocol.json` | The byte layout of the box (**placeholder values until you fill it in**) |
| `ishow_dac.py` | The driver: `IShowDAC`, `Point`, test shapes, `.ild` playback, `--dry-run` |
| `ishow_net.py` | **The decoded iShow 2.3 protocol** (TCP 192.168.1.172:4000) |
| `fake_box.py` | Simulated box for testing `ishow_net.py` without hardware |
| `ilda.py` | Reads `.ild` files (formats 0, 1, 2, 4, 5) |

```
pip install -r requirements.txt
```

---

## Step 1: get the box visible to Python

**Windows 11**
1. Plug in the box and download **Zadig** (https://zadig.akeo.ie).
2. Options → *List All Devices*, then pick the iShow box (it may be called
   "Unknown device", or have a Cypress/STM name).
3. Choose **WinUSB** and click *Install / Replace Driver*. This is a signed
   Microsoft driver, so Windows 11 accepts it.
4. Install libusb for pyusb: `pip install libusb-package` (included in
   `requirements.txt`). Alternatively, copy `libusb-1.0.dll` next to your script.

**Linux / Raspberry Pi** (often the easiest choice): nothing to install. Run
the scripts with `sudo`, or add a udev rule for the VID/PID.

Then run:

```
python probe.py                # unplug/replug to see which line is the box
python probe.py 3333 6666      # dump the iShow 2.3 box (its ID is 3333:6666)
```

Write down the **VID/PID** and the **bulk OUT endpoint**. Point data almost
certainly goes there.

### If the box has no firmware

Many cheap DACs use a Cypress FX2 chip, which starts *empty*. Each time you
plug it in, the Windows driver uploads its firmware. If `probe.py` shows
**`04b4:8613`** (and warns about it), that's your case. You will see the
upload in the capture from step 2 as a long run of vendor control
transfers with `bRequest=0xa0`. Fixes:

- Replay that upload. Run `analyze_capture.py --export session.json` on a
  capture that starts *before* you plug the box in, and set `session_file`.
  The box will re-enumerate with a new PID after the upload. Run `probe.py`
  again and connect to the new PID.
- Alternatively, extract the firmware `.hex`/`.bix` from the old driver package
  and load it with `fxload` on Linux.

## Step 2: record the original software

You need a machine where the old iShow driver still works:

- **A virtual machine.** Install VirtualBox or VMware on your Win 11 PC and
  create a Windows 7 (or XP) VM. Pass the USB box through to it, then install
  iShow 2.3 and its driver inside the VM.
- **Or an old PC/laptop** with Windows 7.
- **On Windows 11 itself (maybe):** boot with *Disable driver signature
  enforcement* (Settings → Recovery → Advanced startup → Troubleshoot →
  Startup Settings → 7). This only works if the driver package has a 64-bit
  `.sys`; many old iShow drivers are 32-bit only.

Capture the USB traffic:

- **In the VM / old PC:** install Wireshark with **USBPcap** and capture on
  the USBPcap interface for the box's root hub.
- **Or on a Linux host** running the VM: `sudo modprobe usbmon`, then
  capture `usbmonN` in Wireshark. You capture from outside the VM, so
  nothing extra goes inside it.

What to record (keep each capture short, 5–10 s, one per file):

1. Start capturing, **plug the box in**, then start iShow. This captures
   firmware upload and start-up commands.
2. Output **one slow single-colour dot moving left → right**. This shows which bytes are X.
3. The same dot moving bottom → top. This shows Y.
4. A **static red** circle, then **green**, then **blue**. This shows the colour bytes.
5. Change the **scan speed (PPS)** in iShow. This shows which control transfer
   sets the point rate.

Save as `.pcapng` (or `.pcap`).

## Step 3: read the protocol out of the capture

```
python analyze_capture.py capture1.pcapng --export session.json
python analyze_capture.py capture2.pcapng
```

It prints:

- **Control transfers**: the vendor commands sent before the first point
  data (marked `*`). These are the start-up sequence. `--export` saves them so
  the driver can replay them.
- **OUT packet sizes and hex dumps**: the point data.
- **Fixed header bytes**: a common command prefix on every packet.
- **A bytes-per-point guess**, plus the first points split into columns. In
  the left→right capture, the column that ramps is X. In the colour captures,
  the column that changes is R/G/B.

Things to check: byte order (`e80b` little-endian = 0x0be8 = 3048), the value range
(12-bit 0–4095 or 16-bit), whether Y is inverted, and whether a 2-byte field
after the header matches the number of points in the packet.

## Step 4: fill in `protocol.json` and run

Put your findings into `protocol.json`: `vid`, `pid`, `out_endpoint`,
`session_file`, the `header` (constant bytes, plus a point `count` field if there
is one), and the `point` fields (`offset`, `size`, `endian`, `min`, `max`,
`invert`). Check what you'd send without touching hardware:

```
python ishow_dac.py --dry-run --shape square
```

Compare those bytes with the capture. When they look the same:

```
python ishow_dac.py --shape circle --seconds 10
python ishow_dac.py --shape rgb
python ishow_dac.py --ilda myshow.ild
```

From your own script:

```python
import math
from ishow_dac import IShowDAC, Point

with IShowDAC.from_config("protocol.json") as dac:
    t = 0
    while True:
        pts = [Point(0.6 * math.cos(a / 50 * math.pi + t), 0.6 * math.sin(a / 25 * math.pi),
                     r=1, g=0.3, b=0) for a in range(200)]
        dac.send_frame(pts)
        t += 0.05
```

If the box sends status replies (the capture shows IN packets after each OUT),
set `status_endpoint`. The driver then reads a reply after every write. If the
box shows a "buffer full" byte, flow control can be added in `_write`.

---

## Safety

- **Never output a still, bright point.** Galvos that aren't moving put all
  the power in one spot. Test at low power and with the beam on a wall, never in
  the audience.
- `IShowDAC` blanks the output when it closes (even after an error), but if your
  script is killed hard the box may keep its last frame. Keep the laser's
  interlock key within reach.
- Leave `points_per_second` within your scanner's rating (usually 20–30 kpps).

## If you'd rather skip the reverse engineering

DACs with open, documented protocols and ready-made Python libraries cost less than a day of work:
**Helios DAC** (USB, libusb, Python wrapper), **Ether Dream** (network, open
protocol), **LaserCube** (Wi-Fi/USB, open-source drivers). Any of them plugs
into the same ILDA DB25 port on your laser. To use one, only the `_write`
method in `ishow_dac.py` changes; the shapes and `.ild` playback stay as they are.
