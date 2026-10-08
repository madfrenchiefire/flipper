#!/usr/bin/env python3
"""Load a program into the iShow box's Cypress FX2 chip (RAM only).

The FX2 forgets the program when unplugged, so this can't damage the box:
unplug it and it is back to the blank 3333:6666 state.

    python fx2load.py fx2lafw-sigrok-fx2-8ch.fw      # sigrok logic analyzer
    python fx2load.py myfirmware.ihx                 # Intel HEX also works

Uses vendor request 0xA0, which the FX2 hardware answers even with no
firmware: hold the 8051 in reset (CPUCS = 1), write the program into
internal RAM, release reset (CPUCS = 0). The chip then re-enumerates as
whatever the new program says it is.
"""
import argparse
import sys
import time

import usb.core

from probe import backend

CPUCS = 0xE600
CHUNK = 1024
RAM_END = 0x4000  # FX2LP internal program/data RAM: 0x0000-0x3FFF


def read_image(path):
    """Return [(address, bytes)] from an Intel HEX (.ihx/.hex) or raw binary (.fw/.bin)."""
    with open(path, "rb") as f:
        blob = f.read()
    if not blob.lstrip().startswith(b":"):
        return [(0, blob)]  # raw image, loaded at address 0 (sigrok .fw files)

    segments = []
    base = 0
    for n, line in enumerate(blob.decode("ascii").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        rec = bytes.fromhex(line[1:])
        if sum(rec) & 0xFF:
            raise ValueError(f"{path}:{n}: bad checksum")
        length, addr, rtype, data = rec[0], int.from_bytes(rec[1:3], "big"), rec[3], rec[4:-1]
        if len(data) != length:
            raise ValueError(f"{path}:{n}: bad length")
        if rtype == 0:
            segments.append((base + addr, data))
        elif rtype == 1:
            break
        elif rtype == 2:
            base = int.from_bytes(data, "big") << 4
        elif rtype == 4:
            base = int.from_bytes(data, "big") << 16
    # Merge adjacent records so we send fewer, larger transfers.
    merged = []
    for addr, data in sorted(segments):
        if merged and merged[-1][0] + len(merged[-1][1]) == addr:
            merged[-1] = (merged[-1][0], merged[-1][1] + data)
        else:
            merged.append((addr, bytes(data)))
    return merged


def load(dev, segments):
    for addr, data in segments:
        if addr + len(data) > RAM_END:
            raise ValueError(f"segment at 0x{addr:04x} runs past internal RAM (0x{RAM_END:04x})")
    dev.ctrl_transfer(0x40, 0xA0, CPUCS, 0, b"\x01")  # hold 8051 in reset
    for addr, data in segments:
        for off in range(0, len(data), CHUNK):
            dev.ctrl_transfer(0x40, 0xA0, addr + off, 0, data[off : off + CHUNK])
    try:
        dev.ctrl_transfer(0x40, 0xA0, CPUCS, 0, b"\x00")  # run
    except usb.core.USBError:
        pass  # the chip may drop off the bus as it re-enumerates


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", help=".ihx/.hex (Intel HEX) or .fw/.bin (raw, from address 0)")
    ap.add_argument("--vid", default="3333")
    ap.add_argument("--pid", default="6666")
    args = ap.parse_args()

    segments = read_image(args.image)
    total = sum(len(d) for _, d in segments)
    dev = usb.core.find(idVendor=int(args.vid, 16), idProduct=int(args.pid, 16), backend=backend())
    if dev is None:
        sys.exit(f"No device {args.vid}:{args.pid}. Is the box plugged in, with WinUSB installed (Zadig)?")
    print(f"Loading {total} bytes in {len(segments)} segment(s) into the FX2...")
    load(dev, segments)
    time.sleep(2)
    print("Done. The box now runs the new program (until it is unplugged).")
    print("Run 'python probe.py' to see the ID it re-enumerated as.")


if __name__ == "__main__":
    main()
