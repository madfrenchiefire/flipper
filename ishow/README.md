# Controlling an iShow 2.3 USB-ILDA box from Python

The iShow box is a USB-to-ILDA DAC. The PC sends it a stream of laser points,
and it turns them into the analog X/Y/R/G/B signals on the DB25 ILDA plug.
Its USB protocol is not published, and its driver doesn't install on Windows 11.
The plan:

1. Talk to the box with **libusb** (through `pyusb`) instead of the old driver.
2. **Record** the original iShow software talking to the box once, on an old
   Windows VM or PC.
3. **Read the protocol out of the recording** with `analyze_capture.py`.
4. Write the layout into `protocol.json`, then drive the laser from Python
   with `ishow_dac.py`.

| File | What it does |
|---|---|
| `probe.py` | Finds the box and lists its USB IDs, endpoints and chip type |
| `analyze_capture.py` | Reads a Wireshark capture: start-up commands, packet header, bytes per point |
| `protocol.json` | The byte layout of the box (**placeholder values until you fill it in**) |
| `ishow_dac.py` | The driver: `IShowDAC`, `Point`, test shapes, `.ild` playback, `--dry-run` |
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
python probe.py 04b4 8613      # dump that device (use your VID/PID)
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
