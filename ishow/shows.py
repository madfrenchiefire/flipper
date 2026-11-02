"""Animated text shows: "MadTown Pub" and "Adam Ouellette".

Each show is a function of time (seconds) returning laser points, and loops.
Built from the single-stroke laser font plus a few effects: write-on, drop-in
with bounce, letter wave, 3D spin, zoom pulse, sparkles, a drawn frame and a
beer mug with rising bubbles.
"""
import math

from laser_font import ADVANCE, GLYPHS
from patterns import LibraryItem
from patterns import strokes_to_points as _to_points


GLYPH_H = 6
LINE_GAP = 3


# -- layout ----------------------------------------------------------------------
class Glyph:
    """One letter (or icon): its strokes in final -1..1 coordinates, plus where it sits."""

    def __init__(self, strokes, line, index, cx, cy):
        self.strokes, self.line, self.index, self.cx, self.cy = strokes, line, index, cx, cy


def layout(lines, extras=None, box=1.7, line_scale=None):
    """Centre lines of text in the box. extras: {line: [(strokes in font units, width)]} drawn
    after that line's text (e.g. an icon). line_scale: per-line size multipliers."""
    extras = extras or {}
    line_scale = line_scale or [1.0] * len(lines)
    rows = []
    for li, text in enumerate(lines):
        items = [(GLYPHS.get(ch, GLYPHS["?"]), ADVANCE) for ch in text.upper()]
        items += [(s, w + 1) for s, w in extras.get(li, [])]
        width = sum(w for _, w in items) - 1
        rows.append((items, width, line_scale[li]))
    total_h = sum(GLYPH_H * sc for _, _, sc in rows) + LINE_GAP * (len(rows) - 1)
    widest = max(w * sc for _, w, sc in rows)
    unit = box / max(widest, total_h)
    glyphs = []
    top = total_h / 2
    for li, (items, width, sc) in enumerate(rows):
        u = unit * sc
        base = top - GLYPH_H * sc
        x = -width * sc / 2
        for gi, (strokes, w) in enumerate(items):
            placed = [[((x + px * sc) * unit, (base + py * sc) * unit) for px, py in st] for st in strokes]
            glyphs.append(Glyph(placed, li, gi, (x + 2 * sc) * unit, (base + 3 * sc) * unit))
            x += w
        top = base - LINE_GAP
        del u
    return glyphs


# -- small helpers -----------------------------------------------------------------
def strokes_to_points(strokes):
    # slightly shorter pauses than still pictures: these frames change all the time anyway
    return _to_points(strokes, corner_dwell=2, jump_dwell=3)


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def phase(t, start, end):
    """0..1 progress of t through [start, end]."""
    return clamp((t - start) / (end - start))


def ease_in_out(p):
    return p * p * (3 - 2 * p)


def bounce(p):
    """Ease-out bounce, 0..1."""
    if p < 1 / 2.75:
        return 7.5625 * p * p
    if p < 2 / 2.75:
        p -= 1.5 / 2.75
        return 7.5625 * p * p + 0.75
    if p < 2.5 / 2.75:
        p -= 2.25 / 2.75
        return 7.5625 * p * p + 0.9375
    p -= 2.625 / 2.75
    return 7.5625 * p * p + 0.984375


def length(stroke):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(stroke, stroke[1:]))


def write_on(strokes, p):
    """The first fraction p (0..1) of the strokes' total length, cutting the last one mid-way."""
    total = sum(length(s) for s in strokes) or 1
    left = p * total
    out = []
    for s in strokes:
        L = length(s)
        if left >= L:
            out.append(s)
            left -= L
            continue
        if left <= 0:
            break
        part = [s[0]]
        for a, b in zip(s, s[1:]):
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            if left >= seg:
                part.append(b)
                left -= seg
            else:
                f = left / seg if seg else 0
                part.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
                left = 0
                break
        if len(part) > 1:
            out.append(part)
        break
    return out


def transform(strokes, fn):
    return [[fn(x, y) for x, y in s] for s in strokes]


def spin_y(strokes, angle, depth=0.25):
    """Fake 3D turn around the vertical axis, with a touch of perspective."""
    c, s = math.cos(angle), math.sin(angle)

    def f(x, y):
        z = x * s
        k = 1 / (1 + depth * z)
        return x * c * k, y * k
    return transform(strokes, f)


def scale(strokes, k, cx=0.0, cy=0.0):
    return transform(strokes, lambda x, y: (cx + (x - cx) * k, cy + (y - cy) * k))


def sparkle(cx, cy, r):
    """A four-point twinkle star."""
    if r <= 0.004:
        return []
    d = r * 0.35
    return [[(cx - r, cy), (cx - d, cy + d), (cx, cy + r), (cx + d, cy + d), (cx + r, cy),
             (cx + d, cy - d), (cx, cy - r), (cx - d, cy - d), (cx - r, cy)]]


def circle(cx, cy, r, n=12):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n + 1)]


def all_strokes(glyphs):
    return [s for g in glyphs for s in g.strokes]


# -- the beer mug icon (font units: 5 wide, 6 tall) ------------------------------------
MUG = [
    [(0.3, 5.0), (0.6, 0.3), (3.4, 0.3), (3.7, 5.0)],                      # glass
    [(3.6, 4.0), (4.7, 4.0), (4.9, 3.4), (4.9, 1.8), (4.6, 1.2), (3.45, 1.2)],  # handle
    [(0.1, 5.0), (0.5, 5.7), (1.2, 5.4), (2.0, 5.9), (2.8, 5.4), (3.5, 5.7), (3.9, 5.0)],  # foam
]
MUG_WIDTH = 5


def mug_bubbles(mug, t):
    """Small bubbles rising inside the mug glyph (uses the mug's placed glass stroke)."""
    glass = mug.strokes[0]
    (x0, y0), (x1, _) = glass[1], glass[2]
    top = glass[0][1]
    height = top - y0
    width = x1 - x0
    out = []
    for k, (fx, speed, off) in enumerate([(0.25, 0.55, 0.0), (0.6, 0.7, 0.4), (0.42, 0.45, 0.75)]):
        p = (t * speed + off) % 1.0
        r = width * (0.05 + 0.04 * p)
        cy = y0 + height * (0.12 + 0.75 * p)
        cx = x0 + width * fx + width * 0.05 * math.sin(t * 5 + k)
        out.append(circle(cx, cy, r, 8))
    return out


# -- show 1: MadTown Pub ----------------------------------------------------------------
_MADTOWN = layout(["MADTOWN", "PUB"], extras={1: [(MUG, MUG_WIDTH)]}, box=1.55, line_scale=[1.0, 1.25])
_MT_LINE1 = [g for g in _MADTOWN if g.line == 0]
_MT_LINE2 = [g for g in _MADTOWN if g.line == 1]
_MT_MUG = _MT_LINE2[-1]
_xs = [x for s in all_strokes(_MADTOWN) for x, _ in s]
_ys = [y for s in all_strokes(_MADTOWN) for _, y in s]
_BORDER = [[(min(_xs) - 0.1, min(_ys) - 0.12), (max(_xs) + 0.1, min(_ys) - 0.12),
            (max(_xs) + 0.1, max(_ys) + 0.12), (min(_xs) - 0.1, max(_ys) + 0.12),
            (min(_xs) - 0.1, min(_ys) - 0.12)]]
MADTOWN_LENGTH = 10.0


def madtown_pub(t):
    t %= MADTOWN_LENGTH
    line1 = all_strokes(_MT_LINE1)
    line2 = all_strokes(_MT_LINE2)
    strokes = []
    if t < 3.6:                                        # write it on
        strokes += write_on(line1, ease_in_out(phase(t, 0.0, 2.0)))
        strokes += write_on(line2, ease_in_out(phase(t, 2.0, 3.4)))
    elif t < 9.3:
        text = line1 + line2
        if 5.6 <= t < 7.6:                             # one full 3D spin
            text = spin_y(text, 2 * math.pi * ease_in_out(phase(t, 5.6, 7.6)))
        elif t >= 7.6:                                 # gentle pulse
            text = scale(text, 1 + 0.05 * math.sin((t - 7.6) * 2 * math.pi * 1.2))
        strokes += text
        if t < 5.6 or t >= 7.6:
            strokes += mug_bubbles(_MT_MUG, t)
        strokes += write_on(_BORDER, ease_in_out(phase(t, 3.6, 4.8)))
        if t >= 7.6:                                   # sparkles on the corners of the frame
            for k, (x, y) in enumerate(_BORDER[0][:4]):
                r = 0.07 * max(0.0, math.sin((t - 7.6) * 4 + k * 1.6))
                strokes += sparkle(x, y, r)
    else:                                              # un-write it
        p = 1 - phase(t, 9.3, 10.0)
        strokes += write_on(line1 + line2 + _BORDER, p)
    return strokes_to_points(strokes)


# -- show 2: Adam Ouellette ----------------------------------------------------------------
_ADAM = layout(["ADAM", "OUELLETTE"], box=1.6, line_scale=[1.35, 1.0])
_AD_LINE1 = [g for g in _ADAM if g.line == 0]
_AD_LINE2 = [g for g in _ADAM if g.line == 1]
_ad_xs = [x for s in all_strokes(_AD_LINE2) for x, _ in s]
_ad_ys = [y for s in all_strokes(_AD_LINE2) for _, y in s]
_UNDERLINE_Y = min(_ad_ys) - 0.1
_UNDER_HALF = (max(_ad_xs) - min(_ad_xs)) / 2 + 0.05
ADAM_LENGTH = 10.0


def adam_ouellette(t):
    t %= ADAM_LENGTH
    strokes = []
    if t < 9.3:
        # ADAM: letters drop in from above, one after another, with a bounce
        for g in _AD_LINE1:
            p = phase(t, 0.25 * g.index, 0.25 * g.index + 0.9)
            if p <= 0:
                continue
            drop = (1 - bounce(p)) * 1.4
            strokes += transform(g.strokes, lambda x, y, d=drop: (x, y + d))
        # OUELLETTE writes on
        if t < 4.0:
            strokes += write_on(all_strokes(_AD_LINE2), ease_in_out(phase(t, 1.8, 3.8)))
        else:
            strokes += all_strokes(_AD_LINE2)
        # a wave runs through all the letters
        if 4.0 <= t < 6.5:
            amp = 0.07 * math.sin(math.pi * phase(t, 4.0, 6.5))
            waved = []
            for g in _ADAM:
                dy = amp * math.sin(t * 7 - g.cx * 6)
                waved += transform(g.strokes, lambda x, y, d=dy: (x, y + d))
            strokes = waved
        # one 3D spin
        if 6.5 <= t < 8.3:
            strokes = spin_y(all_strokes(_ADAM), 2 * math.pi * ease_in_out(phase(t, 6.5, 8.3)))
        # underline sweeps out from the middle, then a star twinkles at its end
        if t >= 8.3:
            half = _UNDER_HALF * ease_in_out(phase(t, 8.3, 8.8))
            if half > 0.01:
                strokes.append([(-half, _UNDERLINE_Y), (half, _UNDERLINE_Y)])
            strokes += sparkle(_UNDER_HALF + 0.08, _UNDERLINE_Y,
                               0.09 * math.sin(math.pi * phase(t, 8.6, 9.3)))
    else:                                              # shrink away to the centre
        k = 1 - ease_in_out(phase(t, 9.3, 10.0))
        under = [[(-_UNDER_HALF, _UNDERLINE_Y), (_UNDER_HALF, _UNDERLINE_Y)]]
        strokes = scale(all_strokes(_ADAM) + under, k)
    return strokes_to_points(strokes)


def show_items():
    items = [LibraryItem("MadTown Pub", generator=madtown_pub, kind="show"),
             LibraryItem("Adam Ouellette", generator=adam_ouellette, kind="show")]
    items[0].preview_t = 5.0    # icons show the finished sign, not the first letter
    items[1].preview_t = 9.0
    return items
