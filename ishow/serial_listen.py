#!/usr/bin/env python3
"""Listen to the STC chip's serial output on the ISP header (read-only).

Wiring (box UNPLUGGED while you connect):
    adapter GND -> G
    adapter RX  -> T
    leave adapter TX and the V pin unconnected

    python serial_listen.py COM5 9600      # one speed: start this, THEN plug in the box
    python serial_listen.py COM5 scan      # try each likely speed, replug the box for each

Speeds a 24 MHz 8051 can make accurately: 1200, 2400, 4800, 9600, 14400, 19200,
57600 and 250000 (DMX). 115200 is not possible with this crystal.
"""
import sys
import time

import serial  # pip install pyserial

LIKELY = [9600, 4800, 19200, 57600, 2400, 1200, 14400, 250000, 38400]


def listen(port, baud, seconds):
    with serial.Serial(port, baud, timeout=0.2) as s:
        s.reset_input_buffer()
        print(f"--- {baud} baud: plug in / power-cycle the box now ({seconds:.0f} s) ---")
        end = time.monotonic() + seconds
        got = bytearray()
        while time.monotonic() < end:
            chunk = s.read(256)
            if chunk:
                got += chunk
                text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                print(f"{chunk.hex(' ')}   |{text}|")
        if not got:
            print("(nothing received)")
        return got


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    port, speed = sys.argv[1], sys.argv[2]
    if speed != "scan":
        listen(port, int(speed), 30)
        return
    results = {}
    for baud in LIKELY:
        input(f"\nUnplug the box, then press Enter to listen at {baud} baud...")
        results[baud] = listen(port, baud, 10)
    print("\nSummary:")
    for baud, got in results.items():
        printable = sum(32 <= b < 127 or b in (10, 13) for b in got)
        note = f"{len(got)} bytes, {printable} readable" if got else "nothing"
        print(f"  {baud:6d} baud: {note}")
    print("The right speed is usually the one with mostly readable text.")


if __name__ == "__main__":
    main()
