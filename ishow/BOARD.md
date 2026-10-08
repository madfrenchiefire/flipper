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

## ISP header (STC90C52RC programming / serial port)

4-pin header labelled `ISP`, pins **V R T G**: +5 V, RXD (STC serial input), TXD (STC serial
output), GND. The STC's bootloader listens here briefly at power-up. Programming through it (e.g.
with `stcgal`) erases the STC's existing program permanently, because STC flash can't be read back.
Listening only (adapter GND to G, adapter RX to T) is safe. Never connect V while the board is
powered from USB.

## Multimeter results

| From | To | Result |
|---|---|---|
| DAC 7–14 (DB7–DB0) | U1 52–56, 1–3 (PD0–PD7)? | |
| DAC 6 (A/B select) | ? | |
| DAC 15 (CS#) | ? | |
| DAC 16 (WR#) | ? | |
| 74HC08 inputs 1, 2, 4, 5, 9, 10, 12, 13 | ? | |
