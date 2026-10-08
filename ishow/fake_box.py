#!/usr/bin/env python3
"""A stand-in for the iShow box, for testing ishow_net.py without hardware.

    python fake_box.py            # listens on 127.0.0.1:4000
    python ishow_net.py --ip 127.0.0.1 --shape square

Prints a line per chunk it receives: the header and the point range.
"""
import socket
import struct


def main(host="127.0.0.1", port=4000):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen()
    print(f"fake iShow box on {host}:{port}")
    while True:
        conn, _ = srv.accept()
        with conn:
            conn.sendall(struct.pack("<i", 1).ljust(20, b"\0"))  # status 1 = ready
            data = b""
            while chunk := conn.recv(65536):
                data += chunk
        if len(data) < 8:
            continue
        hdr, pts = data[:8], data[8:]
        n = len(pts) // 6
        xs, ys = pts[0::6], pts[1::6]
        lit = sum(1 for k in range(n) if any(pts[6 * k + 2 : 6 * k + 6]))
        print(f"header {hdr.hex(' ')} | {n} points, {lit} lit | "
              f"x {min(xs, default=0)}..{max(xs, default=0)} y {min(ys, default=0)}..{max(ys, default=0)}")


if __name__ == "__main__":
    main()
