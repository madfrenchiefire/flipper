#!/usr/bin/env python3
"""Drive the iShow box using the protocol decoded from IS.exe (iShow 2.3).

iShow 2.3 does not talk USB itself. It streams frames over TCP to the box at
192.168.1.172, port 4000 (class hwmain.hwout in IS.exe). This module speaks
that protocol:

  For every chunk of up to 15000 bytes (2500 points):
    1. open a TCP connection to <box>:4000
    2. read 20 bytes; the first 4 are a little-endian int32 status.
       status <= 0 means "busy": close and try again.
    3. send an 8-byte header:
         [0] scan speed * 2   (iShow speed slider 2..60, default 20)
         [1] "je" setting     (slider 0..60, default 10)
         [2] colour setting   (slider 0..255, default 1)
         [3] 1 if the whole frame fits in one chunk, else 0
         [4..7] 04 05 06 07
    4. send the point bytes, then close the connection.

  Each point is 6 bytes:  X, Y, R, I, B, G  (all 0..255)
    X, Y : 0..255, centre 127.5
    I    : brightness, 0.299*R + 0.587*G + 0.114*B
    the last point of a frame is a blanked copy of the one before it.

  iShow re-sends the current frame over and over. The box's status reply is
  the flow control. Use play() or call send_frame() in a loop.

    python ishow_net.py --shape circle --seconds 10
    python ishow_net.py --ip 127.0.0.1 --shape square    # against fake_box.py
"""
import argparse
import socket
import struct
import time

from ishow_dac import BLANK, circle, rgb_test, square

DEFAULT_IP = "192.168.1.172"
PORT = 4000
CHUNK = 15000  # bytes per TCP connection, as in IS.exe
POINT_SIZE = 6


def _byte(v):
    return max(0, min(255, int(round(v))))


def encode_point(p, invert_x=False, invert_y=False, ttl=False):
    x = (p.x + 1) * 127.5
    y = (p.y + 1) * 127.5
    if invert_x:
        x = 255 - x
    if invert_y:
        y = 255 - y
    r, g, b = p.r * 255, p.g * 255, p.b * 255
    if ttl:  # iShow "TTL" mode: each colour fully on or off
        r, g, b = (255 if c > 0 else 0 for c in (r, g, b))
    i = (r * 299 + g * 587 + b * 114) / 1000
    return bytes((_byte(x), _byte(y), _byte(r), _byte(i), _byte(b), _byte(g)))


def encode_frame(points, **kw):
    """Point list -> the byte stream iShow sends for one frame."""
    if not points:
        points = [BLANK]
    data = bytearray()
    for p in points:
        data += encode_point(p, **kw)
    # iShow ends every frame with the last position blanked, twice.
    last_xy = bytes(data[-POINT_SIZE : -POINT_SIZE + 2])
    data[-4:] = b"\0\0\0\0"
    data += last_xy + b"\0\0\0\0"
    return bytes(data)


class IShowNet:
    def __init__(self, ip=DEFAULT_IP, port=PORT, speed=20, je=10, colour=1,
                 invert_x=False, invert_y=False, ttl=False, timeout=2.0):
        self.addr = (ip, port)
        self.speed, self.je, self.colour = speed, je, colour
        self.encode_kw = dict(invert_x=invert_x, invert_y=invert_y, ttl=ttl)
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try:
            self.blank()
        except OSError:
            pass

    def _header(self, single_chunk):
        return bytes((_byte(self.speed * 2) & 0xFF, _byte(self.je), _byte(self.colour),
                      1 if single_chunk else 0, 4, 5, 6, 7))

    def _send_chunk(self, header, chunk, deadline):
        while True:
            with socket.create_connection(self.addr, timeout=self.timeout) as s:
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                reply = b""
                while len(reply) < 20:
                    part = s.recv(20 - len(reply))
                    if not part:
                        break
                    reply += part
                status = struct.unpack_from("<i", reply.ljust(4, b"\0"))[0]
                if status > 0:
                    s.sendall(header + chunk)
                    return status
            if time.monotonic() > deadline:
                raise TimeoutError("iShow box stayed busy (status <= 0)")
            time.sleep(0.001)

    def send_frame(self, points):
        """Send one frame once. Blocks until the box has accepted all of it."""
        data = encode_frame(points, **self.encode_kw)
        header = self._header(len(data) <= CHUNK)
        deadline = time.monotonic() + 5
        for i in range(0, len(data), CHUNK):
            self._send_chunk(header, data[i : i + CHUNK], deadline)

    def play(self, points, seconds):
        """Keep showing one frame (iShow re-sends continuously too)."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.send_frame(points)

    def blank(self):
        self.send_frame([BLANK] * 10)


def main():
    from ilda import read_ilda

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default=DEFAULT_IP)
    ap.add_argument("--shape", choices=["circle", "square", "rgb"], default="circle")
    ap.add_argument("--ilda", help="play an .ild file instead of a test shape")
    ap.add_argument("--seconds", type=float, default=5)
    ap.add_argument("--fps", type=float, default=30, help="frame rate for .ild playback")
    ap.add_argument("--speed", type=int, default=20, help="iShow speed slider, 2..60")
    ap.add_argument("--invert-x", action="store_true")
    ap.add_argument("--invert-y", action="store_true")
    ap.add_argument("--ttl", action="store_true", help="on/off colours (TTL laser)")
    args = ap.parse_args()

    frames = read_ilda(args.ilda) if args.ilda else None
    with IShowNet(args.ip, speed=args.speed, invert_x=args.invert_x,
                  invert_y=args.invert_y, ttl=args.ttl) as dac:
        start = time.monotonic()
        while time.monotonic() - start < args.seconds:
            t = time.monotonic() - start
            if frames:
                pts = frames[int(t * args.fps) % len(frames)]
            elif args.shape == "rgb":
                pts = rgb_test(t)
            else:
                pts = circle() if args.shape == "circle" else square()
            dac.send_frame(pts)


if __name__ == "__main__":
    main()
