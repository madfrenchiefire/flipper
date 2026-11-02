"""Play iShow II "Sections" (.sec files): the original software's shows.

A section is a list of steps. Each step shows one picture for a while, moved by an effect:

    [SectionContent]
    17|1000|hbanandro.ect|257|        picture 17, time 1000, effect "hbanandro.ect"
    ...
    [DrawingList]                     the pictures, same format as .ilf files
    DrawingName=0
    x,y,z,colour,0,flags|...
    [EffectList]                      the effects the steps use
    EffectName=hbanandro.ect
    ro:128,128,167                    rotate about the centre at speed +39
    hb:169                            move left/right at speed +41

How this player reads them (from iShow II's Effect Edit window, which gives every effect
0..255 sliders centred on 128; the exact maths of the original isn't known, so the motion is
our best match rather than a copy):

    hb / vb     move left-right / up-down, bouncing between the edges
    hr / vr     3D turn about the vertical / horizontal axis
    hs / vs     stretch in and out horizontally / vertically
    ro:x,y,s    rotate about point (x, y)            (128,128 = the centre)
    zoom:x,y,s  zoom in and out about point (x, y)
    sd:a,b,s    slow draw: draw the picture on (a < b) or wipe it off (a > b)
    co:s        change colour (a green-only laser stays green)

The last number is always the speed: 128 = still, further from 128 = faster, below 128 =
the other direction. A step's time is how many times the picture is redrawn; we take
REDRAWS_PER_SECOND of those per second (70 -> 1.4 s per picture, 3 -> fast animation).
"""
import math
import os
import re

from ishow_dac import Point
from ishow_formats import PALETTE, _ilf_records, points_from_records

REDRAWS_PER_SECOND = 50.0
MIN_STEP = 1 / 30            # a step is shown for at least one of our frames

_STEP = re.compile(r"^\s*(\d+)\|(\d+)\|([^|]*)\|(\d+)\|?\s*$")


class Section:
    def __init__(self, name, pictures, steps, effects):
        self.name = name
        self.pictures = pictures      # list of point lists
        self.steps = steps            # [(picture index, seconds, [(code, [numbers])])]
        self.length = sum(s for _, s, _ in steps) or 1.0
        self.effects = effects

    def step_at(self, t):
        """(step number from 0, seconds left in it)"""
        t %= self.length
        for i, (_, secs, _) in enumerate(self.steps):
            if t < secs:
                return i, secs - t
            t -= secs
        return len(self.steps) - 1, 0.0

    def frame_at(self, t):
        t %= self.length
        for idx, secs, fx in self.steps:
            if t < secs:
                pts = self.pictures[idx]
                return apply_effects(pts, fx, t, secs) if fx else pts
            t -= secs
        idx, secs, fx = self.steps[-1]
        return self.pictures[idx]


def _parse_effect_lines(lines):
    effects, name = {}, None
    for line in lines:
        line = line.strip()
        if line.startswith("EffectName="):
            name = line[len("EffectName="):].strip().lower()
            effects[name] = []
        elif name is not None and ":" in line:
            code, _, nums = line.partition(":")
            try:
                values = [int(v) for v in nums.split(",") if v.strip()]
            except ValueError:
                continue
            code = code.strip().lower()
            if code in ("hb", "vb", "hr", "vr", "hs", "vs", "ro", "zoom", "sd", "co") and values:
                effects[name].append((code, values))
    return effects


def load_effect_folder(folder):
    """The .ect files next to the sections (used when a section doesn't carry its own copy)."""
    out = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for n in names:
        if n.lower().endswith(".ect"):
            try:
                with open(os.path.join(folder, n), "rb") as f:
                    out.update(_parse_effect_lines(f.read().decode("latin-1").splitlines()))
            except OSError:
                pass
    return out


def read_sec(path, effect_folder=None):
    with open(path, "rb") as f:
        lines = f.read().decode("latin-1").splitlines()
    part, rows, pictures, fx_lines = None, [], [], []
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            part = s.lower()
            continue
        if part == "[sectioncontent]":
            m = _STEP.match(s)
            if m:
                rows.append((int(m.group(1)), int(m.group(2)), m.group(3).strip()))
        elif part == "[drawinglist]" and "|" in s:
            recs = _ilf_records(s)
            if recs:
                pictures.append(points_from_records(recs))
        elif part == "[effectlist]":
            fx_lines.append(s)
    effects = load_effect_folder(effect_folder) if effect_folder else {}
    effects.update(_parse_effect_lines(fx_lines))          # the section's own copies win
    steps, names = [], []
    for idx, time, fx_name in rows:
        if 0 <= idx < len(pictures):
            fx = effects.get(fx_name.lower(), []) if fx_name.lower() not in ("", "null") else []
            steps.append((idx, max(MIN_STEP, time / REDRAWS_PER_SECOND), fx))
            names.append(os.path.splitext(fx_name)[0].strip() if fx else "")
    if not steps:
        raise ValueError("no playable steps in this section")
    name = os.path.splitext(os.path.basename(path))[0]
    sec = Section(name, pictures, steps, effects)
    sec.effect_names = names
    return sec


# -- effects --------------------------------------------------------------------------------
def _speed(v):
    """-1..1 from a 0..255 slider centred on 128."""
    return (v - 128) / 127.0


def _centre(values):
    if len(values) >= 3:
        return (values[0] - 127.5) / 127.5, (127.5 - values[1]) / 127.5
    return 0.0, 0.0


def _swing(lo, hi, cycles):
    """Offset that starts at 0 (where the picture is drawn), swings out to hi, back across to
    lo, and so on: lo/hi are how far the picture can move each way and stay on screen."""
    if hi < lo:                                   # bigger than the screen: no room to move
        return 0.0
    w = math.sin(2 * math.pi * cycles)
    return w * (hi if w > 0 else -lo)


def _extent(pts):
    xs = [p.x for p in pts] or [0.0]
    ys = [p.y for p in pts] or [0.0]
    return min(xs), max(xs), min(ys), max(ys)


def apply_effects(pts, effects, t, step_len):
    """The picture as it looks t seconds into a step that lasts step_len seconds."""
    x0, x1, y0, y1 = _extent(pts)
    sx = sy = 1.0          # stretch / zoom
    turn_h = turn_v = 0.0  # 3D turns
    rot = None             # (angle, cx, cy)
    zoom = None            # (k, cx, cy)
    dx = dy = 0.0
    draw = None            # slow draw: fraction of the picture shown
    colour_step = None
    for code, v in effects:
        s = _speed(v[-1])
        if code == "hb":            # bounce between the left and right edges, wherever it starts
            dx += _swing(-1.0 - x0, 1.0 - x1, 0.5 * s * t)
        elif code == "vb":
            dy += _swing(-1.0 - y0, 1.0 - y1, 0.5 * s * t)
        elif code == "hr":
            turn_h += 2 * math.pi * 0.6 * s * t
        elif code == "vr":
            turn_v += 2 * math.pi * 0.6 * s * t
        elif code == "hs":
            sx *= 0.6 + 0.4 * math.cos(2 * math.pi * 0.6 * s * t)
        elif code == "vs":
            sy *= 0.6 + 0.4 * math.cos(2 * math.pi * 0.6 * s * t)
        elif code == "ro":
            cx, cy = _centre(v)
            rot = (2 * math.pi * 0.5 * s * t, cx, cy)
        elif code == "zoom":
            cx, cy = _centre(v)
            zoom = (0.55 + 0.45 * math.cos(2 * math.pi * 0.5 * s * t), cx, cy)
        elif code == "sd":
            a, b = (v[0], v[1]) if len(v) >= 3 else (0, 255)
            p = min(1.0, t / max(0.2, step_len * 0.7))    # done after 70% of the step, then holds
            draw = p if a <= b else 1 - p
        elif code == "co":
            colour_step = int(t * (1 + 6 * abs(_speed(v[0]))))
    ch, sh = math.cos(turn_h), math.sin(turn_h)
    cv, sv = math.cos(turn_v), math.sin(turn_v)
    out = []
    for p in pts:
        x, y = p.x * sx, p.y * sy
        if turn_h:
            z = x * sh
            k = 1 / (1 + 0.25 * z)
            x, y = x * ch * k, y * k
        if turn_v:
            z = y * sv
            k = 1 / (1 + 0.25 * z)
            x, y = x * k, y * cv * k
        if rot:
            a, cx, cy = rot
            ca, sa = math.cos(a), math.sin(a)
            x, y = cx + (x - cx) * ca - (y - cy) * sa, cy + (x - cx) * sa + (y - cy) * ca
        if zoom:
            k, cx, cy = zoom
            x, y = cx + (x - cx) * k, cy + (y - cy) * k
        x = max(-1.0, min(1.0, x + dx))
        y = max(-1.0, min(1.0, y + dy))
        r, g, b = p.r, p.g, p.b
        if colour_step is not None and max(r, g, b) > 0:
            r, g, b = PALETTE[1 + colour_step % 7]
        out.append(Point(x, y, r, g, b, line=p.line))
    if draw is not None:
        n = int(len(out) * draw)
        out = out[:n] + [Point(out[n - 1].x, out[n - 1].y)] if n > 0 else [Point(0, 0)]
    return out


def section_item(path, effect_folder=None):
    """A section as a library show (looping)."""
    from patterns import LibraryItem
    sec = read_sec(path, effect_folder)
    item = LibraryItem(sec.name, generator=sec.frame_at, path=path, kind="show")
    item.preview_t = min(sec.length * 0.3, 20.0)
    item.section = sec
    return item
