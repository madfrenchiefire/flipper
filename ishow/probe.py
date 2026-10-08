#!/usr/bin/env python3
"""Step 1: find the iShow USB box and dump everything it says about itself.

Usage:
    python probe.py                 # list every USB device
    python probe.py 0483 5740       # dump full descriptors for one VID/PID (hex)

On Windows 11 the box must first be bound to the WinUSB driver with Zadig
(https://zadig.akeo.ie) or pyusb cannot see it. On Linux it works out of the
box (run with sudo, or add a udev rule).
"""
import sys

import usb.core
import usb.util


def backend():
    """On Windows, use the libusb DLL bundled with the libusb-package pip package."""
    try:
        import libusb_package

        return libusb_package.get_libusb1_backend()
    except ImportError:
        return None  # Linux/macOS: system libusb


# VID:PID pairs that mean "this chip has no firmware yet; the old Windows
# driver uploads it every time the box is plugged in".
BLANK_CHIPS = {
    (0x04B4, 0x8613): "Cypress FX2 (CY7C68013) with no firmware",
    (0x04B4, 0x8614): "Cypress FX2LP with no firmware",
    (0x0547, 0x2131): "Anchor/Cypress EZ-USB with no firmware",
    (0x3333, 0x6666): "iShow box: CY7C68013A whose 24C01 EEPROM holds only this ID, no firmware",
}

# The iShow 2.3 box seen so far (an unregistered, self-assigned ID).
ISHOW_IDS = [(0x3333, 0x6666)]

XFER_TYPES = {0: "control", 1: "isochronous", 2: "bulk", 3: "interrupt"}


def safe_string(dev, index):
    if not index:
        return ""
    try:
        return usb.util.get_string(dev, index) or ""
    except Exception:  # needs permission or a driver on some OSes
        return "?"


def list_devices():
    for dev in usb.core.find(find_all=True, backend=backend()):
        name = " ".join(
            s for s in (safe_string(dev, dev.iManufacturer), safe_string(dev, dev.iProduct)) if s
        )
        tag = "  <- iShow box" if (dev.idVendor, dev.idProduct) in ISHOW_IDS else ""
        print(f"{dev.idVendor:04x}:{dev.idProduct:04x}  bus {dev.bus} addr {dev.address}  {name}{tag}")
    print("\nUnplug the iShow box, run again, and the line that disappears is your box.")


def dump(vid, pid):
    dev = usb.core.find(idVendor=vid, idProduct=pid, backend=backend())
    if dev is None:
        sys.exit(f"No device {vid:04x}:{pid:04x} found (Windows: did you install WinUSB with Zadig?)")

    print(f"Device {vid:04x}:{pid:04x}")
    print(f"  Manufacturer : {safe_string(dev, dev.iManufacturer)}")
    print(f"  Product      : {safe_string(dev, dev.iProduct)}")
    print(f"  Serial       : {safe_string(dev, dev.iSerialNumber)}")
    print(f"  USB version  : {dev.bcdUSB >> 8}.{(dev.bcdUSB >> 4) & 0xF}")
    print(f"  Class        : 0x{dev.bDeviceClass:02x}")

    if (vid, pid) in BLANK_CHIPS:
        print(f"\n  !! {BLANK_CHIPS[(vid, pid)]}.")
        print("  !! You must capture or extract the firmware and upload it before anything")
        print("  !! else works. See README section 'If the box has no firmware'.")

    for cfg in dev:
        print(f"\n  Configuration {cfg.bConfigurationValue}")
        for intf in cfg:
            print(
                f"    Interface {intf.bInterfaceNumber} alt {intf.bAlternateSetting}"
                f"  class 0x{intf.bInterfaceClass:02x}"
            )
            for ep in intf:
                direction = "IN " if ep.bEndpointAddress & 0x80 else "OUT"
                kind = XFER_TYPES[ep.bmAttributes & 0x03]
                print(
                    f"      EP 0x{ep.bEndpointAddress:02x} {direction} {kind:<11}"
                    f" max packet {ep.wMaxPacketSize}"
                )
    print("\nThe bulk OUT endpoint is almost certainly where point data goes.")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        dump(int(sys.argv[1], 16), int(sys.argv[2], 16))
    else:
        list_devices()
