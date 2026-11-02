/*
 * pinctl: FX2 test firmware for the iShow "Guicard13" board.
 *
 * Commands arrive on bulk endpoint 2 OUT as (op, value) byte pairs.
 * The FX2's built-in default USB descriptors are kept (RENUM stays 0),
 * so no USB driver change is needed; the host just selects alternate
 * setting 1, where EP2 OUT and EP6 IN are bulk endpoints.
 *
 *   0x01 v  OEA = v        port A direction (1 = output)
 *   0x02 v  IOA = v        port A value
 *   0x03 v  OED = v        port D direction
 *   0x04 v  IOD = v        port D value
 *   0x05 v  DAC A = v      port D = v, PA1 = 0, pulse WR# (PA0)
 *   0x06 v  DAC B = v      port D = v, PA1 = 1, pulse WR# (PA0)
 *   0x08 x  status         reply on EP6 IN: 5A, IOA, IOD, OEA, OED, count
 *
 * Board wiring: DAC data = port D, DAC A/B select = PA1, DAC WR# = PA0,
 * DAC CS# tied low, colour gates = PA2..PA5.
 */
#include <stdint.h>

__sfr __at (0x80) IOA;
__sfr __at (0xB0) IOD;
__sfr __at (0xB2) OEA;
__sfr __at (0xB5) OED;

__xdata __at (0xE600) volatile uint8_t CPUCS;
__xdata __at (0xE690) volatile uint8_t EP2BCH;
__xdata __at (0xE691) volatile uint8_t EP2BCL;
__xdata __at (0xE698) volatile uint8_t EP6BCH;
__xdata __at (0xE699) volatile uint8_t EP6BCL;
__xdata __at (0xE6A3) volatile uint8_t EP2CS;
__xdata __at (0xE6A5) volatile uint8_t EP6CS;
__xdata __at (0xF000) volatile uint8_t EP2BUF[512];
__xdata __at (0xF800) volatile uint8_t EP6BUF[512];

#define EP_EMPTY 0x04
#define EP_FULL  0x08
#define SYNCDELAY __asm nop \
 nop \
 nop \
 nop \
 nop \
 nop \
 nop \
 nop __endasm

static uint8_t count;

static void dac_write(uint8_t channel_b, uint8_t value)
{
    IOD = value;
    OED = 0xFF;
    if (channel_b)
        IOA |= 0x02;
    else
        IOA &= ~0x02;
    IOA |= 0x01;          /* WR# idle high */
    OEA |= 0x03;
    IOA &= ~0x01;         /* WR# low: DAC follows the data */
    __asm nop \
 nop \
 nop \
 nop __endasm;
    IOA |= 0x01;          /* WR# high: value latched */
}

static void send_status(void)
{
    if (EP6CS & EP_FULL)
        return;
    EP6BUF[0] = 0x5A;
    EP6BUF[1] = IOA;
    EP6BUF[2] = IOD;
    EP6BUF[3] = OEA;
    EP6BUF[4] = OED;
    EP6BUF[5] = count;
    EP6BCH = 0;
    SYNCDELAY;
    EP6BCL = 6;
    SYNCDELAY;
}

static void handle(uint8_t op, uint8_t v)
{
    switch (op) {
    case 0x01: OEA = v; break;
    case 0x02: IOA = v; break;
    case 0x03: OED = v; break;
    case 0x04: IOD = v; break;
    case 0x05: dac_write(0, v); break;
    case 0x06: dac_write(1, v); break;
    case 0x08: send_status(); break;
    }
}

void main(void)
{
    uint16_t n, i;

    OEA = 0;              /* every pin starts as an input */
    OED = 0;
    IOA = 0x01;
    CPUCS = (CPUCS & 0xE7) | 0x10;   /* 48 MHz */

    EP2BCL = 0x80;        /* arm both EP2 OUT buffers */
    SYNCDELAY;
    EP2BCL = 0x80;
    SYNCDELAY;

    for (;;) {
        if (!(EP2CS & EP_EMPTY)) {
            n = ((uint16_t)EP2BCH << 8) | EP2BCL;
            for (i = 0; i + 1 < n; i += 2)
                handle(EP2BUF[i], EP2BUF[i + 1]);
            count++;
            EP2BCL = 0x80;    /* give the buffer back to USB */
            SYNCDELAY;
        }
    }
}
