# iShow "Guicard13" board (2011-12-10): wiring notes

## CY7C68013A-56PVXC (U1), 56-pin SSOP

Pin 1 is the corner pin on the **crystal (X1) side**, at the end of the chip nearest the DAC (U4).
Pins 1–28 run down the crystal side and pins 29–56 come back up the DAC side, so pin 56 is the
corner pin on the DAC side, nearest the DAC. The crystal (pins 11/12), USB (15/16) and EEPROM
(22/23) positions on the board confirm this.

| Pin | Signal | Pin | Signal | Pin | Signal | Pin | Signal |
|---|---|---|---|---|---|---|---|
| 1 | PD5 | 15 | D+ | 29 | PB4 | 43 | PA3 |
| 2 | PD6 | 16 | D- | 30 | PB5 | 44 | PA4 |
| 3 | PD7 | 17 | AGND | 31 | PB6 | 45 | PA5 |
| 4 | GND | 18 | VCC | 32 | PB7 | 46 | PA6 |
| 5 | CLKOUT | 19 | GND | 33 | GND | 47 | PA7 |
| 6 | VCC | 20 | IFCLK | 34 | VCC | 48 | GND |
| 7 | GND | 21 | reserved | 35 | GND | 49 | RESET# |
| 8 | RDY0 | 22 | SCL | 36 | CTL0 | 50 | VCC |
| 9 | RDY1 | 23 | SDA | 37 | CTL1 | 51 | WAKEUP |
| 10 | AVCC | 24 | VCC | 38 | CTL2 | 52 | PD0 |
| 11 | XTALOUT | 25 | PB0 | 39 | VCC | 53 | PD1 |
| 12 | XTALIN | 26 | PB1 | 40 | PA0 | 54 | PD2 |
| 13 | AGND | 27 | PB2 | 41 | PA1 | 55 | PD3 |
| 14 | AVCC | 28 | PB3 | 42 | PA2 | 56 | PD4 |

(Source: KiCad `MCU_Cypress.lib`, symbol CY7C68013A-56PVX.)

## TLC7528 (U4), dual 8-bit DAC, 20-pin SOIC

| Pin | Signal | Pin | Signal |
|---|---|---|---|
| 1 | AGND | 11 | DB3 |
| 2 | OUTA | 12 | DB2 |
| 3 | RFBA | 13 | DB1 |
| 4 | REFA | 14 | DB0 |
| 5 | DGND | 15 | CS# |
| 6 | DACA/DACB select | 16 | WR# |
| 7 | DB7 | 17 | VDD |
| 8 | DB6 | 18 | REFB |
| 9 | DB5 | 19 | RFBB |
| 10 | DB4 | 20 | OUTB |

## What the top-layer photo shows (to be confirmed with a multimeter)

- Traces from U1's corner pins on the DAC side (pins ~52–56 = PD0–PD4) wrap under U4 to its
  pins 11–14 (DB3–DB0).
- Traces from U4's pins 7–10 (DB7–DB4) run toward U1's top end, where pins 1–3 are PD5–PD7.
- So the hypothesis is that **the DAC data bus is FX2 port D**, driven directly by the USB chip.
- The lower pins on U1's DAC side (PB, CTL, PA region) go into vias, probably to the STC90C52RC.

### Microscope photos (top layer, confirmed visually)

- **DAC pins 7, 8, 9** (DB7–DB5): three traces leave the DAC's left side, run over the top of U1 and
  curve down into **U1's top pins on the crystal side (pins 1–3 = PD5–PD7)**.
- **DAC pin 10** (DB4): runs left and down to **U1's top pin on the DAC side (pin 56 = PD4)**.
- **DAC pins 11–14** (DB3–DB0): leave the DAC's right side, curve down around the DAC's corner and
  run left as a bus into **U1's top pins on the DAC side (pins 52–55 = PD0–PD3)**.
- So the **whole 8-bit DAC data bus is FX2 port D**, with no STC in between. The exact bit order
  still needs the multimeter, but firmware can remap any order, so it doesn't change the plan.
- **DAC pin 6** (A/B select) goes straight into a via, to the back of the board. Pins 15/16 (CS#,
  WR#) aren't clear in the photos. The rest of U1's DAC side (port A, CTL) also goes into vias. The
  back side of the board will show where those go.

### The six vias above U1 (microscope photo, pin positions measured)

With U1's text reading normally, pin 1 is bottom-left and the top row runs pin 56 (left) to pin 29
(right). Measuring each pad's position and following the traces:

| Via | Goes to U1 pin | FX2 signal |
|---|---|---|
| top-left pair (2 vias) | 40, 41 | PA0, PA1 |
| diagonal staircase (4 vias) | 42, 43, 44, 45 | PA2, PA3, PA4, PA5 |

So **six port A pins (PA0–PA5) leave through these vias**. Six is exactly what's still missing:
3 DAC controls (pin 6 A/B select, 15 CS#, 16 WR#) plus the colour inputs. The back-side bundle from
the 74HC08 area ends at this staircase. Pins 46/47 (PA6/PA7) show no trace. The via with a cross-shaped
thermal relief next to pins 33/34 is a ground/power stitch, not a signal.

### Back of the board (photo, tentative)

Positions are mirrored from the top side. Two bundles of traces stand out:
- **About 4–5 traces from the 74HC08 (U5) area to a diagonal row of vias by the USB chip (U1).** This
  suggests the colour gates are driven by the USB chip, not the STC.
- **About 7–8 parallel traces from the STC (U6) area to the USB chip area.** This is probably an
  8-bit bus between FX2 port B (the pins that read steady high in PulseView) and an STC port.
- DAC pin 6's via couldn't be followed at this resolution. Where DAC pins 6, 15 and 16 end up (U1 or
  U6) is now the deciding question.

### STC90C52RC (U6) orientation and the PB link

Standard 44-pin 8051 layout: 1–3 P1.5–P1.7, 4 RST, 5 P3.0/RXD, 7 P3.1/TXD, 14/15 XTAL, 16 GND,
18–25 P2.0–P2.7, 30–37 P0.7–P0.0, 38 VCC, 40–44 P1.0–P1.4. On this board, pins 34–44 face U1 (pin 34
at the top, 44 at the bottom), pins 1–11 face the ISP header (pin 1 at the dot corner), and pins 12–22
face the X2 crystal. Checks: the wide power trace lands on pin 38 (VCC), the crystal sits on the
XTAL side, and RXD/TXD sit on the side nearest the ISP header.

U1's PB0–PB3 (pins 25–28) run straight to STC pins 40–43 = **P1.0–P1.3**, in order (pin 28 to the
lowest trace). 8051 port 1 has internal pull-ups, which explains why port B read steady high in
PulseView. So FX2 port B ↔ STC port 1 is an 8-bit link, most likely PB4–PB7 ↔ P1.4–P1.7.

## ISP header (STC90C52RC programming / serial port)

4-pin header labelled `ISP`, pins **V R T G**: +5 V, RXD (STC serial input), TXD (STC serial
output), GND. The STC's bootloader listens here briefly at power-up. Programming through it (e.g.
with `stcgal`) erases the STC's existing program permanently, because STC flash can't be read back.
Listening only (adapter GND to G, adapter RX to T) is safe. Never connect V while the board is
powered from USB.

The header sits next to the STC and its own 24 MHz crystal (X2_B). The silkscreen says
"STC89C52"; the fitted part is the pin-compatible STC90C52RC. On the 44-pin package, R and T
should go to STC pin 5 (P3.0/RXD) and pin 7 (P3.1/TXD). Count from the dot, anticlockwise.

**Listening result:** with `serial_listen.py`, nothing was received at any likely speed (1200–57600,
250000) during or after power-up. One burst at plug-in did not repeat and decoded as noise. The STC's
program apparently doesn't use its serial port; the header is for factory programming only.

## First live result (pinctl firmware)

`dac a 0 / 128 / 255` on DB25 pin 1 (against pin 25): **−8.05 V / 0 V / +8.31 V**. The FX2 is driving the
DAC and the output stage works. Gain ≈ 0.064 V per step, centred on 128. That's well beyond ILDA's
±5 V, so software must limit values to about **50–206** for ±5 V.

`dac b 0 / 255` on DB25 pin 2: **−8.02 V / +8.58 V**. So **DAC channel A = X (DB25 pin 1)** and
**channel B = Y (DB25 pin 2)**, and the A/B select on PA1 works. (The status read-back showing PA1 = 1
while driven low is a read-back quirk, not a wiring fault.)

## Complete signal map (all measured)

| Signal | FX2 pin | ILDA DB25 pin |
|---|---|---|
| X (DAC channel A, ±8.3 V full scale) | port D + PA1 = 0 + WR# pulse on PA0 | 1 |
| Y (DAC channel B, ±8.5 V full scale) | port D + PA1 = 1 + WR# pulse on PA0 | 2 |
| Intensity / blanking | PA5 | 3 |
| Red | PA4 | 5 |
| Green | PA3 | 6 |
| Blue | PA2 | 7 |
| Ground | | 25 |

Colours are on/off: 0 V off, about +4.1 V on.

## The original driver package (xinxiuII.inf, LQloader.sys, Lhloader.sys, ezusb.sys)

The `.inf` (Xinxiu stage equipment, 2010) lists four devices:

| USB ID | Name in the .inf | Driver |
|---|---|---|
| 3333:6666 | "Xinxiu Gui22 card" (**this board, blank**) | LQloader.sys (firmware loader) |
| 9999:6666 | "iShowII Lasershow software interface card" (this board after loading) | ezusb.sys |
| 3333:5555 | "sek 7 Color USB2.0 GuiCard V20 Loader" (older card) | Lhloader.sys |
| 9999:5555 | "sek 7 Color USB2.0 GuiCard V20 (Basic)" | ezusb.sys |

All three `.sys` files are 32-bit x86 and unsigned (ezusb.sys 2001, Lhloader 2010, LQloader 2011),
so they can't load on 64-bit Windows 10/11. That's why the box stopped working.

LQloader.sys is Cypress's "ezloader" sample with the board's firmware embedded (280 Intel-hex records,
3,415 bytes at 0x0000–0x0DC8, plus the standard 792-byte helper loader). Analysis of that firmware:

- It re-enumerates as **9999:6666, strings "LaserShw" / "USB22-Card"**, with bulk EP2/EP4 OUT and
  EP6/EP8 IN (512 bytes, 64 at full speed).
- Its point routine (0x0CFE) is exactly our mapping: `IOD = x; PA1 = 0; pulse PA0; IOD = y; PA1 = 1;
  pulse PA0`. Its blank routine (0x0D5F) clears PA2–PA5. **This confirms the measured signal map.**
- Between points it **interpolates on the chip** (Bresenham-style, one DAC step at a time toward the
  next target), so the PC only sends corner points.
- Timer 0 is a tick counter; after about 15 ticks without data it calls the blank routine (beam off).
- Port B is a data bus to the STC with **PA6/PA7 as handshake lines** (routines at 0x0280–0x02E3 and
  0x06E0–0x07AB). The STC isn't involved in drawing. It most likely handles the RJ45 link or standalone
  playback.

Our own firmware (`firmware/stream.c`) replaces all of this and runs on Windows 11 with WinUSB.
Version 2 adopts the original's on-chip line drawing: a point with bit 7 of its colour byte set is
reached by a straight line of equal steps (`0x12 k`: at most k DAC units per step while lit,
`0x13 k`: the same for beam-off jumps, default 3 and 10). The status reply reports the firmware
version, so the app replaces older firmware automatically.

## Test firmware note

The first test program (pinwiggle) used the FX2's 0xA0 memory request while the 8051 was running.
That doesn't work: reads returned the program's own instruction bytes (bus contention), so writes
never reached the ports either (0xA0 while running is unreliable). `firmware/pinctl.c` replaces it: commands
travel over bulk EP2 OUT, status comes back on EP6 IN, using the FX2's built-in default descriptors
(alt setting 1), so no new USB driver is needed.

## Multimeter results

Board unplugged. Record each as `U1 52`, `U6 17`, `G`, `V`, `none`, or a resistance like `100 Ω`.

### Step 0: orientation checks
| Probe | Expect | Result |
|---|---|---|
| U1 pin 4 → ISP G | beep (GND) | |
| U1 pin 19 → ISP G | beep (GND) | |
| U1 pins 15, 16 → USB socket | the two middle pins of the USB-B socket | |
| U4 pin 5 → ISP G | beep (DGND) | |
| U4 pin 17 → ISP V | beep (+5 V) | |
| U5 pin 7 → ISP G, pin 14 → ISP V | beep, beep | |
| ISP R → U6 pin 5, ISP T → U6 pin 7 | beep, beep | |

### Step 1: DAC (U4, TLC7528)
| U4 pin | Signal | Goes to |
|---|---|---|
| 7 | DB7 | |
| 8 | DB6 | |
| 9 | DB5 | |
| 10 | DB4 | |
| 11 | DB3 | |
| 12 | DB2 | |
| 13 | DB1 | |
| 14 | DB0 | |
| 6 | DACA/DACB select | lower via of the top-left pair → U1 pin 41 (PA1) |
| 15 | CS# | tied to ground (always selected) |
| 16 | WR# | upper via of the top-left pair → U1 pin 40 (PA0) |

**Result:** the USB chip has full control of the DAC: data = port D, A/B select = PA1, WR# = PA0,
CS# permanently enabled. Writing a value: set port D and PA1, pulse PA0 low then high.

### Step 2: colour gates (U5, 74HC08)
| U5 pin | Signal | Goes to |
|---|---|---|
| 1 | gate 1 input A | U1 pin 45 (PA5), via the staircase via nearest the pins on the left |
| 2 | gate 1 input B | same via as pin 1 (inputs tied together: gate 1 is a buffer) |
| 3 | gate 1 output | DB25 pin 3 (ILDA intensity/blanking): PA5 = 1 gives +4.1 V, PA5 = 0 gives 0 V |
| 4 | gate 2 input A | U1 pin 44 (PA4), staircase via 2 |
| 5 | gate 2 input B | same (buffer) |
| 6 | gate 2 output | DB25 pin 5 (ILDA red), driven by PA4 |
| 9 | gate 3 input A | U1 pin 43 (PA3), staircase via 3 |
| 10 | gate 3 input B | same (buffer) |
| 8 | gate 3 output | DB25 pin 6 (ILDA green), driven by PA3 |
| 12 | gate 4 input A | U1 pin 42 (PA2), staircase via 4 |
| 13 | gate 4 input B | same (buffer) |
| 11 | gate 4 output | DB25 pin 7 (ILDA blue), driven by PA2 |

**Result:** all four 74HC08 gates are buffers (both inputs tied), driven by PA5, PA4, PA3 and PA2. The
four colour/blanking outputs are controlled directly by the USB chip. Still to find: which DB25 pin each
output (3, 6, 8, 11) drives, and where PA0/PA1 go (expected: DAC pins 6/15/16).

### Step 3: USB chip to STC (only if step 1 or 2 shows STC pins)
| U1 pin | FX2 signal | Goes to U6 pin |
|---|---|---|
| 25 | PB0 | STC pin 40 (P1.0) |
| 26 | PB1 | STC pin 41 (P1.1) |
| 27 | PB2 | STC pin 42 (P1.2) |
| 28 | PB3 | STC pin 43 (P1.3) |
| 29–32 | PB4–PB7 | expected STC pins 44, 1, 2, 3 (P1.4–P1.7); not yet checked |
| 36, 37, 38 | CTL0–CTL2 | |
| 40–47 | PA0–PA7 | |
| 8, 9 | RDY0, RDY1 | |
| 5 | CLKOUT | |
| 20 | IFCLK | |
