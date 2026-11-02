"""A simulated iShow box, for trying the app without hardware (demo mode).

Behaves like the real board: it ignores bulk data until firmware is uploaded
(0xA0 writes, then CPUCS released), then answers status requests and takes
point packets at the configured rate, as the real firmware does.
"""
import time

import usb.core

CPUCS = 0xE600


class FakeBox:
    is_fake = True

    def __init__(self, firmware_loaded=False):
        self.running = firmware_loaded
        self.in_reset = False
        self.rate = 20
        self.points = 0
        self.underruns = 0
        self.replies = []
        self.last_frame = []      # (x, y, colour) bytes of the last packet, for inspection

    def set_interface_altsetting(self, interface=0, alternate_setting=0):
        pass

    def ctrl_transfer(self, bm, req, value, index, data_or_len, timeout=None):
        if bm == 0x40 and req == 0xA0 and value == CPUCS:
            self.in_reset = bool(data_or_len[0] & 1)
            if not self.in_reset:
                self.running = True
            return len(data_or_len)
        if bm == 0x40:
            return len(data_or_len)
        return bytes(data_or_len)

    def _timeout(self):
        raise usb.core.USBTimeoutError("Operation timed out", errno=110, error_code=-7)

    def write(self, ep, data, timeout=None):
        if not self.running or self.in_reset:
            time.sleep((timeout or 1000) / 1000)
            self._timeout()
        data = bytes(data)
        cmd = data[0]
        if cmd == 0x10:
            n = data[1]
            self.last_frame = [tuple(data[2 + 3 * i: 5 + 3 * i]) for i in range(n)]
            self.points += n
            time.sleep(n / (self.rate * 1000))   # the real box paces us the same way
        elif cmd == 0x11:
            self.rate = max(1, min(60, data[1]))
        elif cmd == 0x08:
            p = self.points
            self.replies.append(bytes((0x5A, self.rate, self.underruns & 0xFF, self.underruns >> 8,
                                       p & 0xFF, (p >> 8) & 0xFF, (p >> 16) & 0xFF)))
        return len(data)

    def read(self, ep, length, timeout=None):
        if not self.replies:
            time.sleep((timeout or 1000) / 1000)
            self._timeout()
        return self.replies.pop(0)
