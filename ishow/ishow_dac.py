#!/usr/bin/env python3
"""Step 4: drive the iShow USB box from Python.

The byte layout is not hard-coded. It comes from protocol.json, which you fill
in from what analyze_capture.py showed you. This file handles USB, the start-up
sequence, packing points, pacing and blanking.

    python ishow_dac.py --dry-run --shape circle    # print bytes, no hardware
    python ishow_dac.py --shape square --seconds 10
    python ishow_dac.py --ilda show.ild

Use it from your own script:

    from ishow_dac import IShowDAC, Point
    with IShowDAC.from_config("protocol.json") as dac:
        dac.send_frame([Point(0, 0, 1, 0, 0), Point(0.5, 0.5, 0, 1, 0)])

Coordinates go from -1.0 to 1.0. Colours go from 0.0 to 1.0.
"""
import argparse
import json
import math
import os
import struct
import time
from dataclasses import dataclass


@dataclass
class Point:
    x: float  # -1.0 (left)  .. 1.0 (right)
    y: float  # -1.0 (bottom) .. 1.0 (top)
    r: float = 0.0  # 0.0 .. 1.0
    g: float = 0.0
    b: float = 0.0

    @property
    def i(self):  # intensity / blanking channel
        return max(self.r, self.g, self.b)


BLANK = Point(0, 0)


def _int(v):
    return int(v, 0) if isinstance(v, str) else v


# --------------------------------------------------------------------------
# Byte packing, driven by protocol.json
# --------------------------------------------------------------------------
class PointPacker:
    """Turns Points into bytes using the field layout in protocol.json."""

    def __init__(self, cfg):
        self.size = cfg["point"]["size"]
        self.fields = cfg["point"]["fields"]
        self.header = cfg.get("header", [])
        self.footer = bytes.fromhex(cfg.get("footer_hex", ""))

    @staticmethod
    def _put(buf, offset, size, endian, value):
        fmt = {1: "B", 2: "H", 4: "I"}[size]
        struct.pack_into(("<" if endian == "little" else ">") + fmt, buf, offset, value)

    def pack_point(self, p):
        buf = bytearray(self.size)
        for f in self.fields:
            name = f["name"]
            lo, hi = f.get("min", 0), f.get("max", 255)
            if name == "const":
                value = _int(f["value"])
            else:
                v = getattr(p, name)
                if name in ("x", "y"):
                    v = (v + 1) / 2  # -1..1 -> 0..1
                v = min(max(v, 0.0), 1.0)
                if f.get("invert"):
                    v = 1 - v
                value = round(lo + v * (hi - lo))
                if f.get("signed"):  # store two's complement
                    value &= (1 << (8 * f["size"])) - 1
            self._put(buf, f["offset"], f["size"], f.get("endian", "little"), value)
        return bytes(buf)

    def pack_header(self, n_points):
        out = bytearray()
        for h in self.header:
            if h["type"] == "const":
                out += bytes.fromhex(h["hex"])
            elif h["type"] == "count":  # number of points in this packet
                b = bytearray(h["size"])
                self._put(b, 0, h["size"], h.get("endian", "little"), n_points)
                out += b
            elif h["type"] == "bytes":  # number of point bytes in this packet
                b = bytearray(h["size"])
                self._put(b, 0, h["size"], h.get("endian", "little"), n_points * self.size)
                out += b
        return bytes(out)

    def pack(self, points):
        return self.pack_header(len(points)) + b"".join(map(self.pack_point, points)) + self.footer


# --------------------------------------------------------------------------
# The device
# --------------------------------------------------------------------------
class IShowDAC:
    def __init__(self, cfg, dry_run=False):
        self.cfg = cfg
        self.packer = PointPacker(cfg)
        self.dry_run = dry_run
        self.pps = cfg.get("points_per_second", 20000)
        self.max_points = cfg.get("max_points_per_packet", 1000)
        self.out_ep = _int(cfg["out_endpoint"])
        self.status_ep = _int(cfg["status_endpoint"]) if cfg.get("status_endpoint") else None
        self.dev = None

    @classmethod
    def from_config(cls, path="protocol.json", **kw):
        with open(path) as f:
            cfg = json.load(f)
        cfg["_dir"] = os.path.dirname(os.path.abspath(path))
        return cls(cfg, **kw)

    # -- connection ---------------------------------------------------------
    def open(self):
        if self.dry_run:
            print("[dry-run] would open USB device", self.cfg["vid"], self.cfg["pid"])
            return self
        import usb.core
        import usb.util

        vid, pid = _int(self.cfg["vid"]), _int(self.cfg["pid"])
        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            raise RuntimeError(
                f"iShow box {vid:04x}:{pid:04x} not found. On Windows, bind it to WinUSB with Zadig."
            )
        intf = self.cfg.get("interface", 0)
        try:
            if self.dev.is_kernel_driver_active(intf):
                self.dev.detach_kernel_driver(intf)
        except (NotImplementedError, usb.core.USBError):
            pass  # Windows / no kernel driver
        try:
            self.dev.set_configuration()
        except usb.core.USBError:
            pass  # already configured
        usb.util.claim_interface(self.dev, intf)
        self._run_init_sequence()
        return self

    def _run_init_sequence(self):
        """Replay the vendor control transfers iShow sent at start-up."""
        session = self.cfg.get("session_file")
        if not session:
            return
        with open(os.path.join(self.cfg.get("_dir", "."), session)) as f:
            steps = json.load(f).get("init_control_transfers", [])
        for step in steps:
            bm, req, val, idx, length = struct.unpack("<BBHHH", bytes.fromhex(step["setup"]))
            if bm & 0x80:
                self.dev.ctrl_transfer(bm, req, val, idx, length, timeout=1000)
            else:
                self.dev.ctrl_transfer(bm, req, val, idx, bytes.fromhex(step["data"]), timeout=1000)
            time.sleep(0.002)

    def close(self):
        try:
            self.blank()
        finally:
            if self.dev is not None:
                import usb.util

                usb.util.dispose_resources(self.dev)
                self.dev = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # -- output -------------------------------------------------------------
    def _write(self, data):
        if self.dry_run:
            print(f"[dry-run] EP 0x{self.out_ep:02x} <- {len(data)} B: {data[:48].hex(' ')}"
                  + (" ..." if len(data) > 48 else ""))
            return
        self.dev.write(self.out_ep, data, timeout=1000)
        if self.status_ep is not None:
            self.dev.read(self.status_ep, 64, timeout=1000)

    def send_frame(self, points):
        """Send one frame. Blocks for roughly as long as the frame takes to draw."""
        if not points:
            points = [BLANK]
        start = time.perf_counter()
        for i in range(0, len(points), self.max_points):
            self._write(self.packer.pack(points[i : i + self.max_points]))
        # Pace ourselves if the box doesn't push back on its own.
        if self.cfg.get("software_pacing", True) and not self.dry_run:
            remaining = len(points) / self.pps - (time.perf_counter() - start)
            if remaining > 0:
                time.sleep(remaining)

    def blank(self):
        self.send_frame([BLANK] * 20)


# --------------------------------------------------------------------------
# Test shapes
# --------------------------------------------------------------------------
def _with_blanking(path, color, dwell=8):
    """Laser-friendly path: blank move to the start, dwell at corners."""
    r, g, b = color
    first = path[0]
    pts = [Point(first[0], first[1])] * dwell
    for x, y in path:
        pts.append(Point(x, y, r, g, b))
    pts += [Point(path[-1][0], path[-1][1], r, g, b)] * dwell
    return pts


def circle(n=300, radius=0.5, color=(0, 1, 0)):
    return _with_blanking(
        [(radius * math.cos(2 * math.pi * k / n), radius * math.sin(2 * math.pi * k / n))
         for k in range(n + 1)],
        color,
    )


def polygon(corners, color=(1, 0, 0), per_edge=40, dwell=6):
    path = []
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
        path += [(x0, y0)] * dwell  # dwell so corners are sharp
        path += [(x0 + (x1 - x0) * t / per_edge, y0 + (y1 - y0) * t / per_edge) for t in range(per_edge)]
    path.append(corners[0])
    return _with_blanking(path, color)


def square(size=0.5, color=(1, 0, 0)):
    s = size
    return polygon([(-s, -s), (s, -s), (s, s), (-s, s)], color)


def rgb_test(t):
    """Three overlapping shapes, one per colour, slowly rotating."""
    pts = []
    for k, color in enumerate([(1, 0, 0), (0, 1, 0), (0, 0, 1)]):
        a = t + k * 2 * math.pi / 3
        cx, cy = 0.3 * math.cos(a), 0.3 * math.sin(a)
        pts += [Point(p.x * 0.5 + cx, p.y * 0.5 + cy, p.r, p.g, p.b) for p in circle(120, 0.5, color)]
    return pts


def main():
    from ilda import read_ilda

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "protocol.json"))
    ap.add_argument("--shape", choices=["circle", "square", "rgb"], default="circle")
    ap.add_argument("--ilda", help="play an .ild file instead of a test shape")
    ap.add_argument("--seconds", type=float, default=5)
    ap.add_argument("--fps", type=float, default=30, help="frame rate for .ild playback")
    ap.add_argument("--dry-run", action="store_true", help="print the bytes instead of using USB")
    args = ap.parse_args()

    dac = IShowDAC.from_config(args.config, dry_run=args.dry_run)
    frames = read_ilda(args.ilda) if args.ilda else None
    with dac:
        end = time.time() + args.seconds
        n = 0
        while time.time() < end:
            if frames:
                pts = frames[int(n * args.fps / 30) % len(frames)]
            elif args.shape == "rgb":
                pts = rgb_test(time.time())
            else:
                pts = circle() if args.shape == "circle" else square()
            dac.send_frame(pts)
            n += 1
            if args.dry_run and n >= 2:
                break


if __name__ == "__main__":
    main()
