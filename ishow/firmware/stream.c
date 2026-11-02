/*
 * stream: point-streaming firmware for the iShow "Guicard13" board (FX2LP).
 *
 * Keeps the FX2's built-in default descriptors (RENUM = 0); the host selects
 * alternate setting 1 and talks over bulk EP2 OUT / EP6 IN.
 *
 * Packets on EP2 OUT (first byte = command):
 *   0x10 n  x y c  x y c ...   n points (n <= 170), 3 bytes each:
 *                              x, y = DAC values; c = bits for PA2..PA5
 *                              (PA2 blue, PA3 green, PA4 red, PA5 intensity)
 *   0x11 k                     set rate to k thousand points per second (1..60)
 *   0x08 0                     status reply on EP6 IN:
 *                              5A, rate, underruns lo, hi, points lo, mid, hi
 *
 * Points are output one per Timer2 tick. If no packet is waiting when one
 * runs out, every colour line is switched off (beam blanked) until data
 * arrives, so a stalled PC never leaves a still, lit beam.
 *
 * Board wiring: DAC data = port D, PA1 = DAC A/B select (A = X, B = Y),
 * PA0 = DAC WR#, DAC CS# tied low, PA2..PA5 = colour/blanking gates.
 */
#include <stdint.h>

__sfr __at (0x80) IOA;
__sfr __at (0xB0) IOD;
__sfr __at (0xB2) OEA;
__sfr __at (0xB5) OED;
__sfr __at (0x8E) CKCON;
__sfr __at (0xC8) T2CON;
__sfr __at (0xCA) RCAP2L;
__sfr __at (0xCB) RCAP2H;
__sfr __at (0xCC) TL2;
__sfr __at (0xCD) TH2;
__sbit __at (0xCF) TF2;
__sbit __at (0xCA) TR2;

__xdata __at (0xE600) volatile uint8_t CPUCS;
__xdata __at (0xE690) volatile uint8_t EP2BCH;
__xdata __at (0xE691) volatile uint8_t EP2BCL;
__xdata __at (0xE698) volatile uint8_t EP6BCH;
__xdata __at (0xE699) volatile uint8_t EP6BCL;
__xdata __at (0xE6A3) volatile uint8_t EP2CS;
__xdata __at (0xE6A5) volatile uint8_t EP6CS;
__xdata __at (0xF000) volatile uint8_t EP2BUF[512];
__xdata __at (0xF800) volatile uint8_t EP6BUF[512];

#define EP_EMPTY   0x04
#define EP_FULL    0x08
#define COLOUR_MASK 0x3C   /* PA2..PA5 */
#define SYNCDELAY __asm nop \
 nop \
 nop \
 nop \
 nop \
 nop \
 nop \
 nop __endasm

static uint8_t rate_k = 20;
static uint16_t underruns;
static uint32_t points;

static void set_rate(uint8_t k)
{
    uint16_t reload;
    if (k < 1) k = 1;
    if (k > 60) k = 60;
    rate_k = k;
    /* Timer2 counts CLKOUT/12 = 4 MHz at 48 MHz: 4000 counts per kpps. */
    reload = (uint16_t)(65536UL - 4000U / k);
    TR2 = 0;
    RCAP2L = reload & 0xFF;
    RCAP2H = reload >> 8;
    TL2 = RCAP2L;
    TH2 = RCAP2H;
    TF2 = 0;
    TR2 = 1;
}

static void output_point(uint8_t x, uint8_t y, uint8_t c)
{
    while (!TF2)
        ;
    TF2 = 0;
    IOD = x;
    IOA &= ~0x02;            /* channel A = X */
    IOA &= ~0x01;            /* WR# low */
    __asm nop \
 nop __endasm;
    IOA |= 0x01;             /* WR# high: latched */
    IOD = y;
    IOA |= 0x02;             /* channel B = Y */
    IOA &= ~0x01;
    __asm nop \
 nop __endasm;
    IOA |= 0x01;
    IOA = (IOA & ~COLOUR_MASK) | (c & COLOUR_MASK);
    points++;
}

static void send_status(void)
{
    if (EP6CS & EP_FULL)
        return;
    EP6BUF[0] = 0x5A;
    EP6BUF[1] = rate_k;
    EP6BUF[2] = underruns & 0xFF;
    EP6BUF[3] = underruns >> 8;
    EP6BUF[4] = points & 0xFF;
    EP6BUF[5] = (points >> 8) & 0xFF;
    EP6BUF[6] = (points >> 16) & 0xFF;
    EP6BCH = 0;
    SYNCDELAY;
    EP6BCL = 7;
    SYNCDELAY;
}

void main(void)
{
    uint8_t n, i, cmd, was_drawing = 0;
    uint16_t len;
    __xdata volatile uint8_t *p;

    CPUCS = (CPUCS & 0xE7) | 0x10;   /* 48 MHz */
    IOA = 0x01;                      /* WR# high, all colours off */
    OEA = 0x3F;                      /* PA0..PA5 outputs */
    OED = 0xFF;
    CKCON &= ~0x20;                  /* Timer2 at CLKOUT/12 */
    T2CON = 0x00;                    /* 16-bit auto-reload */
    set_rate(20);
    output_point(128, 128, 0);       /* centre, blanked */

    EP2BCL = 0x80;                   /* arm both EP2 OUT buffers */
    SYNCDELAY;
    EP2BCL = 0x80;
    SYNCDELAY;

    for (;;) {
        if (EP2CS & EP_EMPTY) {
            if (was_drawing) {       /* ran out of points: blank the beam */
                IOA &= ~COLOUR_MASK;
                underruns++;
                was_drawing = 0;
            }
            continue;
        }
        len = ((uint16_t)EP2BCH << 8) | EP2BCL;
        cmd = len ? EP2BUF[0] : 0;
        if (cmd == 0x10 && len >= 2) {
            n = EP2BUF[1];
            if ((uint16_t)n * 3 + 2 > len)
                n = (len - 2) / 3;
            p = &EP2BUF[2];
            for (i = 0; i < n; i++, p += 3)
                output_point(p[0], p[1], p[2]);
            was_drawing = 1;
        } else if (cmd == 0x11 && len >= 2) {
            set_rate(EP2BUF[1]);
        } else if (cmd == 0x08) {
            send_status();
        }
        EP2BCL = 0x80;               /* give the buffer back to USB */
        SYNCDELAY;
    }
}
