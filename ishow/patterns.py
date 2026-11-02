"""Pictures for the laser: built-in patterns, text, and .ild files.

Everything is described as strokes (polylines in -1..1 coordinates) and then
turned into laser points with blanked jumps between strokes and short
pauses ("dwell") at corners, which keeps corners sharp on real galvos.
"""
import math
import os

from ishow_dac import Point
from laser_font import text_strokes

GREEN = (0.0, 1.0, 0.0)


def _is_corner(a, b, c, min_angle=35):
    """True if the path turns by more than min_angle degrees at b."""
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 == 0 or n2 == 0:
        return True
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos)) > min_angle


# True: send only corner points and let the box's firmware draw the lines between them
# (like the original iShow firmware). False: the PC computes every point itself.
ON_CHIP_LINES = True


def strokes_to_points(strokes, color=GREEN, step=0.03, corner_dwell=3, jump_dwell=4, on_chip=None):
    """Turn polylines into a laser point list."""
    if on_chip is None:
        on_chip = ON_CHIP_LINES
    if on_chip:
        return _strokes_to_vertices(strokes, color, corner_dwell, jump_dwell)
    r, g, b = color
    pts = []
    pos = (0.0, 0.0)
    for stroke in strokes:
        if len(stroke) < 2:
            continue
        # blanked jump to the start of the stroke
        sx, sy = stroke[0]
        dist = math.hypot(sx - pos[0], sy - pos[1])
        for k in range(1, max(2, int(dist / 0.08)) + 1):
            f = k / max(2, int(dist / 0.08))
            pts.append(Point(pos[0] + (sx - pos[0]) * f, pos[1] + (sy - pos[1]) * f))
        pts += [Point(sx, sy)] * jump_dwell
        pts += [Point(sx, sy, r, g, b)] * corner_dwell
        # lit segments, with a dwell at every corner
        for i, ((x0, y0), (x1, y1)) in enumerate(zip(stroke, stroke[1:])):
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
            pts += [Point(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, r, g, b) for k in range(1, n + 1)]
            last = i == len(stroke) - 2
            if last or _is_corner(stroke[i], stroke[i + 1], stroke[i + 2]):
                pts += [Point(x1, y1, r, g, b)] * corner_dwell
        pos = stroke[-1]
        pts.append(Point(pos[0], pos[1]))  # blank before the next jump
    if not pts:
        pts = [Point(0, 0)]
    return pts


def _strokes_to_vertices(strokes, color, corner_dwell, jump_dwell):
    """Corner points only, flagged so the firmware draws straight lines between them."""
    r, g, b = color
    pts = []
    for stroke in strokes:
        if len(stroke) < 2:
            continue
        sx, sy = stroke[0]
        pts.append(Point(sx, sy, line=True))            # blanked line (jump) to the start
        pts += [Point(sx, sy)] * jump_dwell              # let the mirrors settle, beam off
        pts += [Point(sx, sy, r, g, b)] * corner_dwell   # beam on at the start
        for i in range(1, len(stroke)):
            x1, y1 = stroke[i]
            pts.append(Point(x1, y1, r, g, b, line=True))
            last = i == len(stroke) - 1
            if last or _is_corner(stroke[i - 1], stroke[i], stroke[i + 1]):
                pts += [Point(x1, y1, r, g, b)] * corner_dwell
        pts.append(Point(*stroke[-1]))                   # beam off before the next jump
    return pts or [Point(0, 0)]


# -- shapes as strokes ---------------------------------------------------------
def poly(n, radius=0.8, rotation=math.pi / 2):
    return [(radius * math.cos(rotation + 2 * math.pi * k / n),
             radius * math.sin(rotation + 2 * math.pi * k / n)) for k in range(n + 1)]


def curve(fn, n=120):
    return [fn(2 * math.pi * k / n) for k in range(n + 1)]


def star(points=5, outer=0.85, inner=0.35):
    out = []
    for k in range(2 * points + 1):
        rad = outer if k % 2 == 0 else inner
        a = math.pi / 2 + math.pi * k / points
        out.append((rad * math.cos(a), rad * math.sin(a)))
    return out


def heart(t):
    x = 16 * math.sin(t) ** 3
    y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
    return (x / 18, y / 18 + 0.1)


def spiral(turns=4, n=240):
    return [((k / n) * 0.9 * math.cos(2 * math.pi * turns * k / n),
             (k / n) * 0.9 * math.sin(2 * math.pi * turns * k / n)) for k in range(n + 1)]


def test_pattern():
    """ILDA-style alignment pattern: frame, circle, centre cross, corner ticks."""
    s = [[(-0.9, -0.9), (0.9, -0.9), (0.9, 0.9), (-0.9, 0.9), (-0.9, -0.9)],
         curve(lambda t: (0.6 * math.cos(t), 0.6 * math.sin(t))),
         [(-0.2, 0), (0.2, 0)], [(0, -0.2), (0, 0.2)]]
    return s


def grid(n=4):
    s = []
    for k in range(n + 1):
        v = -0.9 + 1.8 * k / n
        s.append([(-0.9, v), (0.9, v)] if k % 2 == 0 else [(0.9, v), (-0.9, v)])
    for k in range(n + 1):
        v = -0.9 + 1.8 * k / n
        s.append([(v, -0.9), (v, 0.9)] if k % 2 == 0 else [(v, 0.9), (v, -0.9)])
    return s


# -- library items -------------------------------------------------------------
class LibraryItem:
    """Something that can be shown: a static picture, an animation, or an .ild file."""

    def __init__(self, name, frames=None, generator=None, fps=20, path=None, kind="pattern", first=None):
        self.name, self.fps, self.path, self.kind = name, fps, path, kind
        self.frames = frames          # list of point lists; None = not loaded yet (files)
        self.generator = generator    # fn(t) -> point list, for animations
        self.first = first            # first frame only, for previews of not-yet-loaded files

    @property
    def loaded(self):
        return self.generator is not None or self.frames is not None

    def load(self):
        """Read the whole file (can take a moment for big .ild files)."""
        if not self.loaded and self.path:
            frames = read_laser_file(self.path)
            if not frames:
                raise ValueError("no frames in file")
            self.frames = frames
        return self

    def frame_at(self, t):
        if self.generator:
            return self.generator(t)
        if self.frames is None:
            return self.first or [Point(0, 0)]
        return self.frames[int(t * self.fps) % len(self.frames)]

    def preview_frame(self):
        return self.frame_at(getattr(self, "preview_t", 0.4) if self.generator else 0)


def static(name, strokes, kind="pattern"):
    return LibraryItem(name, frames=[strokes_to_points(strokes)], kind=kind)


def animated(name, strokes_fn, kind="pattern"):
    return LibraryItem(name, generator=lambda t: strokes_to_points(strokes_fn(t)), kind=kind)


def rotating_square(t):
    return [poly(4, 0.7, t * 1.5 + math.pi / 4)]


def lissajous(t):
    return [curve(lambda a: (0.8 * math.sin(3 * a + t), 0.8 * math.sin(2 * a)), 200)]


def scanning_line(t):
    x = 0.9 * math.sin(t * 2)
    return [[(x, -0.9), (x, 0.9)]]


def builtin_items():
    return [
        static("Test pattern", test_pattern(), "test"),
        static("Grid", grid(), "test"),
        static("Corners box", [[(-0.95, -0.95), (0.95, -0.95), (0.95, 0.95), (-0.95, 0.95), (-0.95, -0.95)]], "test"),
        animated("Scan line", scanning_line, "test"),
        static("Circle", [curve(lambda t: (0.8 * math.cos(t), 0.8 * math.sin(t)))]),
        static("Square", [poly(4, 0.8, math.pi / 4)]),
        static("Triangle", [poly(3, 0.85)]),
        static("Star", [star()]),
        static("Heart", [curve(heart, 160)]),
        static("Spiral", [spiral()]),
        animated("Spinning square", rotating_square),
        animated("Lissajous", lissajous),
    ]


def text_item(lines):
    lines = [ln for ln in lines if ln.strip()][:2]
    return static(" / ".join(lines) or "(empty)", text_strokes(lines), "text")


LASER_FILE_TYPES = (".ild", ".ilf", ".ddr")   # ILDA, iShow animations, iShow drawings


def read_laser_file(path, max_frames=None):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".ild":
        from ilda import read_ilda
        return read_ilda(path, max_frames)
    from ishow_formats import READERS
    if ext not in READERS:
        raise ValueError(f"unsupported file type {ext}")
    return READERS[ext](path, max_frames)


def file_item(path, lazy=False):
    """Any supported laser file as a library item. lazy=True reads only the first frame now
    (for previews); the rest is read by item.load() when it's first shown."""
    name = os.path.splitext(os.path.basename(path))[0]
    if lazy:
        first = read_laser_file(path, max_frames=1)
        if not first:
            raise ValueError("no frames in file")
        return LibraryItem(name, fps=20, path=path, kind="file", first=first[0])
    frames = read_laser_file(path)
    if not frames:
        raise ValueError("no frames in file")
    return LibraryItem(name, frames=frames, fps=20, path=path, kind="file")


def ilda_item(path, lazy=False):
    """An .ild file as a library item. lazy=True reads only the first frame now (for previews);
    the rest is read by item.load() when it's first shown."""
    from ilda import read_ilda
    name = os.path.splitext(os.path.basename(path))[0]
    if lazy:
        first = read_ilda(path, max_frames=1)
        if not first:
            raise ValueError("no frames in file")
        return LibraryItem(name, fps=20, path=path, kind="file", first=first[0])
    frames = read_ilda(path)
    if not frames:
        raise ValueError("no frames in file")
    return LibraryItem(name, frames=frames, fps=20, path=path, kind="file")


def preview_segments(points, max_points=1500):
    """Lit line segments of a point list, for drawing a preview: [(x0, y0, x1, y1), ...].
    Very dense frames are thinned to keep previews quick to draw."""
    if len(points) > max_points:
        points = points[:: len(points) // max_points + 1]
    segs = []
    for a, b in zip(points, points[1:]):
        if max(b.r, b.g, b.b) >= 0.5 and (a.x, a.y) != (b.x, b.y):
            segs.append((a.x, a.y, b.x, b.y))
    return segs
