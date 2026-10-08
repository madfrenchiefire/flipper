"""Minimal reader for .ild (ILDA Image Data Transfer) files.

Supports formats 0, 1, 4, 5 (points) and 2 (palette). Returns a list of
frames, each a list of ishow_dac.Point.
"""
import colorsys
import struct

from ishow_dac import Point

# Stand-in for the ILDA default 64-colour palette: a hue sweep, then whites.
DEFAULT_PALETTE = [colorsys.hsv_to_rgb(k / 56, 1, 1) for k in range(56)] + [(1, 1, 1)] * 8

RECORD = {  # format -> (bytes per record, has z, true colour)
    0: (8, True, False),
    1: (6, False, False),
    4: (10, True, True),
    5: (8, False, True),
}


def read_ilda(path):
    with open(path, "rb") as f:
        data = f.read()
    palette = list(DEFAULT_PALETTE)
    frames = []
    pos = 0
    while pos + 32 <= len(data) and data[pos : pos + 4] == b"ILDA":
        fmt = data[pos + 7]
        count = struct.unpack_from(">H", data, pos + 24)[0]
        pos += 32
        if count == 0:  # end-of-file header
            break
        if fmt == 2:
            palette = [tuple(c / 255 for c in data[pos + 3 * k : pos + 3 * k + 3]) for k in range(count)]
            pos += 3 * count
            continue
        if fmt not in RECORD:
            raise ValueError(f"Unsupported ILDA format {fmt}")
        size, has_z, true_colour = RECORD[fmt]
        frame = []
        for k in range(count):
            rec = data[pos + k * size : pos + (k + 1) * size]
            x, y = struct.unpack_from(">hh", rec, 0)
            o = 6 if has_z else 4
            status = rec[o]
            if status & 0x40:  # blanked
                r = g = b = 0.0
            elif true_colour:
                b, g, r = (c / 255 for c in rec[o + 1 : o + 4])
            else:
                r, g, b = palette[rec[o + 1] % len(palette)]
            frame.append(Point(x / 32768, y / 32768, r, g, b))
        pos += count * size
        frames.append(frame)
    return frames
