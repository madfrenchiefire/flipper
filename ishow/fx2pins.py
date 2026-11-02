#!/usr/bin/env python3
"""Set the iShow box's USB-chip pins by hand, to find out what each one does.

Loads firmware/pinwiggle.ihx into the FX2 (RAM only: unplugging undoes it),
then lets you drive port D (the DAC data bus) and port A (PA0-PA7, which go
to the vias by the USB chip) and see the result on the ILDA socket.

    python fx2pins.py

Commands at the prompt:
    d 128          drive port D (DAC data) with a value 0-255
    d off          release port D (inputs)
    a 3 1          drive PA3 high   (a <bit 0-7> <0|1>)
    a 3 off        release PA3
    a off          release all of port A
    s              show status (pin read-back and heartbeat)
    q              release everything and quit

LASER DISCONNECTED. Measure the ILDA socket with a multimeter instead.
"""
import os
import sys
import time

import usb.core

from fx2load import load, read_image
from probe import backend

MAILBOX = 0x3F00  # OEA, IOA, OED, IOD, heartbeat, IOA read-back, IOD read-back
FIRMWARE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firmware", "pinwiggle.ihx")


class Pins:
    def __init__(self, dev):
        self.dev = dev
        self.oea = self.ioa = self.oed = self.iod = 0

    def _write(self):
        data = bytes((self.oea, self.ioa, self.oed, self.iod))
        self.dev.ctrl_transfer(0x40, 0xA0, MAILBOX, 0, data)

    def status(self):
        mb = bytes(self.dev.ctrl_transfer(0xC0, 0xA0, MAILBOX, 0, 7))
        return {"heartbeat": mb[4], "port_a": mb[5], "port_d": mb[6]}

    def port_d(self, value):
        if value is None:
            self.oed = 0
        else:
            self.oed, self.iod = 0xFF, value & 0xFF
        self._write()

    def port_a_bit(self, bit, value):
        mask = 1 << bit
        if value is None:
            self.oea &= ~mask
        else:
            self.oea |= mask
            self.ioa = (self.ioa | mask) if value else (self.ioa & ~mask)
        self._write()

    def release_all(self):
        self.oea = self.oed = 0
        self._write()


def open_and_load():
    dev = usb.core.find(idVendor=0x3333, idProduct=0x6666, backend=backend())
    if dev is None:
        sys.exit("Box (3333:6666) not found. Replug it (to clear any earlier program) and check WinUSB.")
    segments = read_image(FIRMWARE)
    segments.append((MAILBOX, bytes(7)))  # start with every pin released
    load(dev, segments)
    time.sleep(0.2)
    pins = Pins(dev)
    beat1 = pins.status()["heartbeat"]
    time.sleep(0.05)
    beat2 = pins.status()["heartbeat"]
    if beat1 == beat2:
        sys.exit("Firmware loaded but isn't running (heartbeat not changing).")
    print("Firmware running. All pins released (inputs).")
    return pins


def main():
    pins = open_and_load()
    print(__doc__.split("Commands at the prompt:")[1])
    try:
        while True:
            parts = input("pins> ").split()
            if not parts:
                continue
            cmd = parts[0].lower()
            try:
                if cmd == "q":
                    break
                elif cmd == "s":
                    st = pins.status()
                    print(f"  port A reads {st['port_a']:08b} (PA7..PA0), port D reads "
                          f"{st['port_d']:3d} = {st['port_d']:08b}, heartbeat {st['heartbeat']}")
                elif cmd == "d" and len(parts) == 2:
                    pins.port_d(None if parts[1] == "off" else int(parts[1], 0))
                    print("  port D", "released" if parts[1] == "off" else f"= {int(parts[1], 0)}")
                elif cmd == "a" and len(parts) == 2 and parts[1] == "off":
                    pins.oea = 0
                    pins._write()
                    print("  port A released")
                elif cmd == "a" and len(parts) == 3:
                    bit = int(parts[1])
                    if not 0 <= bit <= 7:
                        raise ValueError
                    pins.port_a_bit(bit, None if parts[2] == "off" else int(parts[2]))
                    print(f"  PA{bit}", "released" if parts[2] == "off" else f"= {parts[2]}")
                else:
                    print("  ? see the command list above")
            except ValueError:
                print("  ? bad number")
    finally:
        pins.release_all()
        print("All pins released.")


if __name__ == "__main__":
    main()
