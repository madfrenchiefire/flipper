#!/usr/bin/env python3
"""Drive the iShow "Guicard13" USB box directly, with our own FX2 firmware.

No iShow software or driver needed: this loads firmware/stream.ihx into the
box's Cypress FX2 (RAM only) and streams points to it over USB.

    python ishow_usb.py --shape circle --seconds 10
    python ishow_usb.py --shape rgb
    python ishow_usb.py --ilda show.ild
    python ishow_usb.py --test-range          # slow corner tour, for checking limits

From your own script:

    from ishow_usb import IShowUSB
    from ishow_dac import Point
    with IShowUSB() as dac:
        while True:
            dac.send_frame([Point(-0.5, 0, r=1), Point(0.5, 0, r=1)])

Coordinates are -1.0 .. 1.0; colours 0.0 .. 1.0 (this board's colours are
on/off, so anything >= 0.5 counts as on).

SAFETY: this board's X/Y outputs swing about +/-8.3 V at full scale, beyond
the ILDA +/-5 V standard. The default `limit=5.0` keeps the output within
+/-5 V. Raise it only if you know your projector accepts more.
"""
import argparse
import os
import sys
import time

import usb.core
import usb.util

from fx2load import load, read_image
from ishow_dac import BLANK, Point, circle, rgb_test, square
from probe import backend

FIRMWARE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firmware", "stream.ihx")
EP_OUT, EP_IN = 0x02, 0x86
MAX_POINTS = 170                 # 2 + 170 * 3 = 512 bytes per USB packet
VOLTS_PER_STEP = 16.4 / 255      # measured: 0 -> -8.05 V, 255 -> +8.31 V

# Colour lines (port A bits), from the board mapping in BOARD.md.
BLUE, GREEN, RED, INTENSITY = 0x04, 0x08, 0x10, 0x20


class IShowUSB:
    def __init__(self, rate_kpps=20, limit=5.0, invert_x=False, invert_y=False, swap_xy=False):
        half = min(127, round(limit / VOLTS_PER_STEP))  # steps either side of centre
        self.lo, self.hi = 128 - half, 128 + half
        self.rate = rate_kpps
        self.invert_x, self.invert_y, self.swap_xy = invert_x, invert_y, swap_xy
        self.dev = None

    # -- connection ---------------------------------------------------------
    def open(self):
        dev = usb.core.find(idVendor=0x3333, idProduct=0x6666, backend=backend())
        if dev is None:
            raise RuntimeError("iShow box (3333:6666) not found. Is it plugged in, with WinUSB (Zadig)?")
        try:
            dev.set_configuration()
        except usb.core.USBError:
            pass
        usb.util.claim_interface(dev, 0)
        dev.set_interface_altsetting(interface=0, alternate_setting=1)
        load(dev, read_image(FIRMWARE))   # always reload: resets the box to a known state
        time.sleep(0.3)
        self.dev = dev
        self.set_rate(self.rate)
        st = self.status()
        print(f"iShow box ready: {st['rate']} kpps, output limited to "
              f"+/-{(self.hi - 128) * VOLTS_PER_STEP:.1f} V")
        return self

    def close(self):
        if self.dev is None:
            return
        try:
            self.blank()
        finally:
            usb.util.dispose_resources(self.dev)
            self.dev = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # -- protocol ------------------------------------------------------------
    def set_rate(self, kpps):
        self.rate = max(1, min(60, int(kpps)))
        self.dev.write(EP_OUT, bytes((0x11, self.rate)), timeout=1000)

    def status(self):
        self.dev.write(EP_OUT, bytes((0x08, 0)), timeout=1000)
        r = bytes(self.dev.read(EP_IN, 64, timeout=1000))
        if len(r) < 7 or r[0] != 0x5A:
            raise RuntimeError(f"unexpected status reply {r.hex(' ')}")
        return {"rate": r[1], "underruns": r[2] | r[3] << 8, "points": r[4] | r[5] << 8 | r[6] << 16}

    def _scale(self, v, invert):
        v = max(-1.0, min(1.0, v))
        if invert:
            v = -v
        return round(self.lo + (v + 1) / 2 * (self.hi - self.lo))

    def encode(self, p):
        x, y = (p.y, p.x) if self.swap_xy else (p.x, p.y)
        c = (RED if p.r >= 0.5 else 0) | (GREEN if p.g >= 0.5 else 0) | (BLUE if p.b >= 0.5 else 0)
        if c:
            c |= INTENSITY
        return bytes((self._scale(x, self.invert_x), self._scale(y, self.invert_y), c))

    def send_frame(self, points):
        """Queue a frame. Blocks while the box's buffers are full (that's the pacing)."""
        if not points:
            points = [BLANK]
        for i in range(0, len(points), MAX_POINTS):
            chunk = points[i : i + MAX_POINTS]
            self.dev.write(EP_OUT, bytes((0x10, len(chunk))) + b"".join(map(self.encode, chunk)),
                           timeout=2000)

    def blank(self):
        self.send_frame([BLANK] * 20)


def corner_tour():
    """Slow, blanked tour of the corners and centre, for checking the output range."""
    pts = []
    for x, y in [(0, 0), (-1, -1), (1, -1), (1, 1), (-1, 1), (0, 0)]:
        pts += [Point(x, y)] * 2000   # about 0.1 s per corner at 20 kpps
    return pts


def main():
    from ilda import read_ilda

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", choices=["circle", "square", "rgb"], default="circle")
    ap.add_argument("--ilda", help="play an .ild file")
    ap.add_argument("--seconds", type=float, default=5)
    ap.add_argument("--fps", type=float, default=30, help="frame rate for .ild playback")
    ap.add_argument("--rate", type=int, default=20, help="points per second, in thousands (1-60)")
    ap.add_argument("--limit", type=float, default=5.0, help="max output voltage (default 5 = ILDA)")
    ap.add_argument("--invert-x", action="store_true")
    ap.add_argument("--invert-y", action="store_true")
    ap.add_argument("--swap-xy", action="store_true")
    ap.add_argument("--test-range", action="store_true", help="blanked corner tour (no laser light)")
    args = ap.parse_args()

    frames = read_ilda(args.ilda) if args.ilda else None
    with IShowUSB(args.rate, args.limit, args.invert_x, args.invert_y, args.swap_xy) as dac:
        start = time.monotonic()
        while time.monotonic() - start < args.seconds:
            t = time.monotonic() - start
            if args.test_range:
                pts = corner_tour()
            elif frames:
                pts = frames[int(t * args.fps) % len(frames)]
            elif args.shape == "rgb":
                pts = rgb_test(t)
            elif args.shape == "square":
                pts = square()
            else:
                pts = circle()
            dac.send_frame(pts)
        st = dac.status()
        print(f"Done: {st['points']} points output, {st['underruns']} underruns.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, usb.core.USBError) as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        pass

