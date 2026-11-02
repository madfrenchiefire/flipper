#!/usr/bin/env python3
"""Set the iShow box's USB-chip pins by hand, to find out what each one does.

Loads firmware/pinctl.ihx into the FX2 (RAM only: unplugging undoes it) and
sends it commands over USB bulk endpoint 2. Port D drives the DAC data bus,
PA0 is the DAC's WR#, PA1 its A/B select, PA2-PA5 the colour gates.

    python fx2pins.py

Commands at the prompt:
    dac a 200      write 200 to DAC channel A (PA1 low), pulse WR# (PA0)
    dac b 50       write 50 to DAC channel B (PA1 high)
    a 3 1          drive PA3 high   (a <bit 0-7> <0|1>)
    a 3 off        release PA3
    a off          release all of port A
    d 128          drive port D with a value 0-255 (no WR# pulse)
    d off          release port D
    s              show status (pin read-back)
    q              release everything and quit

LASER DISCONNECTED. Measure the ILDA socket with a multimeter instead.
"""
import os
import sys
import time

import usb.core
import usb.util

from fx2load import load, read_image
from probe import backend

FIRMWARE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firmware", "pinctl.ihx")
EP_OUT, EP_IN = 0x02, 0x86
OP_OEA, OP_IOA, OP_OED, OP_IOD, OP_DAC_A, OP_DAC_B, OP_STATUS = 1, 2, 3, 4, 5, 6, 8


class Pins:
    def __init__(self, dev):
        self.dev = dev
        self.oea, self.ioa = 0, 0x01  # firmware starts with WR# (PA0) latched high, all inputs
        self.oed = self.iod = 0

    def send(self, *pairs):
        data = bytes(b for pair in pairs for b in pair)
        self.dev.write(EP_OUT, data, timeout=1000)

    def status(self):
        self.send((OP_STATUS, 0))
        r = bytes(self.dev.read(EP_IN, 64, timeout=1000))
        if len(r) < 6 or r[0] != 0x5A:
            raise RuntimeError(f"unexpected status reply {r.hex(' ')}")
        return {"port_a": r[1], "port_d": r[2], "oea": r[3], "oed": r[4], "packets": r[5]}

    def port_d(self, value):
        if value is None:
            self.oed = 0
            self.send((OP_OED, 0))
        else:
            self.oed, self.iod = 0xFF, value & 0xFF
            self.send((OP_IOD, self.iod), (OP_OED, 0xFF))

    def port_a_bit(self, bit, value):
        mask = 1 << bit
        if value is None:
            self.oea &= ~mask
        else:
            self.oea |= mask
            self.ioa = (self.ioa | mask) if value else (self.ioa & ~mask)
        self.send((OP_IOA, self.ioa), (OP_OEA, self.oea))

    def dac_write(self, channel, value):
        """The firmware does the whole TLC7528 write itself (data, select, WR# pulse)."""
        self.send((OP_DAC_B if channel == "b" else OP_DAC_A, value & 0xFF))
        self.oea |= 0x03
        self.ioa = (self.ioa | 0x03) if channel == "b" else ((self.ioa | 0x01) & ~0x02)
        self.oed, self.iod = 0xFF, value & 0xFF

    def release_all(self):
        self.oea = self.oed = 0
        self.send((OP_OEA, 0), (OP_OED, 0))


def open_and_load():
    dev = usb.core.find(idVendor=0x3333, idProduct=0x6666, backend=backend())
    if dev is None:
        sys.exit("Box (3333:6666) not found. Replug it (to clear any earlier program) and check WinUSB.")
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    usb.util.claim_interface(dev, 0)
    dev.set_interface_altsetting(interface=0, alternate_setting=1)  # bulk EP2 OUT / EP6 IN
    load(dev, read_image(FIRMWARE))
    time.sleep(0.3)
    pins = Pins(dev)
    try:
        st = pins.status()
    except Exception as e:
        sys.exit(f"Firmware loaded but didn't answer ({e}). Replug the box and try again.")
    print(f"Firmware running (status reply OK, port D reads {st['port_d']}). All pins released.")
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
                    print(f"  port A reads {st['port_a']:08b} (PA7..PA0, outputs {st['oea']:08b}), "
                          f"port D reads {st['port_d']:3d} = {st['port_d']:08b} (outputs {st['oed']:08b})")
                elif cmd == "dac" and len(parts) == 3 and parts[1] in ("a", "b"):
                    pins.dac_write(parts[1], int(parts[2], 0))
                    print(f"  DAC {parts[1].upper()} = {int(parts[2], 0)}")
                elif cmd == "d" and len(parts) == 2:
                    pins.port_d(None if parts[1] == "off" else int(parts[1], 0))
                    print("  port D", "released" if parts[1] == "off" else f"= {int(parts[1], 0)}")
                elif cmd == "a" and len(parts) == 2 and parts[1] == "off":
                    pins.oea = 0
                    pins.send((OP_OEA, 0))
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
