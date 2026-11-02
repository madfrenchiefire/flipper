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
| 6 | DACA/DACB select | |
| 15 | CS# | |
| 16 | WR# | |

### Step 2: colour gates (U5, 74HC08)
| U5 pin | Signal | Goes to |
|---|---|---|
| 1 | gate 1 input A | |
| 2 | gate 1 input B | |
| 3 | gate 1 output | (DB25 pin) |
| 4 | gate 2 input A | |
| 5 | gate 2 input B | |
| 6 | gate 2 output | (DB25 pin) |
| 9 | gate 3 input A | |
| 10 | gate 3 input B | |
| 8 | gate 3 output | (DB25 pin) |
| 12 | gate 4 input A | |
| 13 | gate 4 input B | |
| 11 | gate 4 output | (DB25 pin) |

### Step 3: USB chip to STC (only if step 1 or 2 shows STC pins)
| U1 pin | FX2 signal | Goes to U6 pin |
|---|---|---|
| 25–32 | PB0–PB7 | |
| 36, 37, 38 | CTL0–CTL2 | |
| 40–47 | PA0–PA7 | |
| 8, 9 | RDY0, RDY1 | |
| 5 | CLKOUT | |
| 20 | IFCLK | |
