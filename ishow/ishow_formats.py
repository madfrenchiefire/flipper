"""Readers for the original iShow II content formats.

.ilf  (Quickframe, Frames)  text animations:
        [DrawingList]
        DrawingName=0
        x,y,z,colour,0,flags|x,y,z,colour,0,flags|...
        DrawingName=1
        ...
.ddr  (Drawing)  one binary frame, 5 bytes per point: x, y, corner, colour, flags

x and y are 0..255 in the box's DAC scale, with y = 0 at the TOP (screen style).
flags: bit 0 = start of a new line (jump there with the beam off), 128 = last point.
colour: 0 = beam off; 1..7 = the classic 7-colour laser palette (more in .ilf files,
whose larger palette numbers aren't decoded yet and are drawn white).
corner (.ddr): 2 = sharp corner, pause there so the corner stays crisp.

The points come out flagged for the box's on-chip line drawing, which is how the
original iShow II drove the hardware (a jump or a line to each point).
"""
from ishow_dac import Point

# 7-colour laser palette (red, green, blue, yellow, cyan, magenta, white): our best
# reading of iShow's colour numbers; the green-only setting makes all of them green.
PALETTE = {1: (1, 0, 0), 2: (0, 1, 0), 3: (0, 0, 1), 4: (1, 1, 0), 5: (0, 1, 1), 6: (1, 0, 1), 7: (1, 1, 1)}
JUMP_DWELL, START_DWELL, CORNER_DWELL = 3, 2, 3


def _xy(x, y):
    return (x - 127.5) / 127.5, (127.5 - y) / 127.5


def _rgb(c):
    if c == 0:
        return (0, 0, 0)
    return PALETTE.get(c, (1, 1, 1))


def points_from_records(records):
    """records: (x, y, colour, flags, corner) -> laser points for one frame."""
    pts = []
    for x, y, colour, flags, corner in records:
        X, Y = _xy(x, y)
        r, g, b = _rgb(colour)
        if flags & 1 or not pts:                      # start of a line: blanked jump
            pts.append(Point(X, Y, line=True))
            pts += [Point(X, Y)] * JUMP_DWELL
            if colour:
                pts += [Point(X, Y, r, g, b)] * START_DWELL
        else:
            pts.append(Point(X, Y, r, g, b, line=True))
            if corner:
                pts += [Point(X, Y, r, g, b)] * CORNER_DWELL
        if flags & 128:                               # end of the frame: beam off
            pts.append(Point(X, Y))
    return pts or [Point(0, 0)]


def _ilf_records(line):
    recs = []
    for p in line.strip().strip("|").split("|"):
        v = p.split(",")
        if len(v) >= 6:
            try:
                x, y, _z, c, _u, f = (int(a) for a in v[:6])
            except ValueError:
                continue
            recs.append((max(0, min(255, x)), max(0, min(255, y)), c, f, 0))
    return recs


def read_ilf(path, max_frames=None):
    frames = []
    with open(path, "rb") as f:
        for raw in f:
            line = raw.decode("latin-1")
            if "|" in line:
                recs = _ilf_records(line)
                if recs:
                    frames.append(points_from_records(recs))
                    if max_frames and len(frames) >= max_frames:
                        break
    return frames


def read_ddr(path, max_frames=None):
    data = open(path, "rb").read()
    recs = [(data[i], data[i + 1], data[i + 3], data[i + 4], data[i + 2] == 2)
            for i in range(0, len(data) - 4, 5)]
    return [points_from_records(recs)] if recs else []


READERS = {".ilf": read_ilf, ".ddr": read_ddr}
