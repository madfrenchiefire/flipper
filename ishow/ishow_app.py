#!/usr/bin/env python3
"""iShow Laser: desktop app for the iShow "Guicard13" USB laser box.

    python ishow_app.py            # real box
    python ishow_app.py --demo     # no hardware: a simulated box

Connect uploads our firmware to the box if it isn't running yet, status
lights show whether the box answers, and clicking a picture, a test
pattern, your own text or an imported .ild laser file shows it on the
laser. STOP (or the Esc key) blanks the beam.
"""
import argparse
import collections
import json
import subprocess
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import usb.core

import patterns
import shows
from ishow_usb import IShowUSB

APP_NAME = "iShow Laser"
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))
LIBRARY_DIR = os.path.join(BASE_DIR, "laser_files")
SETTINGS_FILE = os.path.join(BASE_DIR, "ishow_app_settings.json")

DEFAULT_SETTINGS = {"rate": 20, "limit": 5.0, "invert_x": False, "invert_y": False,
                    "swap_xy": False, "mono_green": True, "file_fps": 20, "line_step": 3,
                    "folders": [], "removed_folders": [], "file_speeds": {},
                    "text_effect": "Still", "text_speed": "Normal"}

# Where the original iShow II content can be: first the project's own copy (ishow_content, next to
# this app or the .exe), then an unpacked or installed iShow II. Found folders are linked automatically.
CONTENT_DIR = os.path.join(BASE_DIR, "ishow_content")
ISHOW_HOMES = [CONTENT_DIR, r"C:\iShowII_EN", r"C:\iShowII", r"C:\iShow",
               r"C:\Program Files\iShowII_EN", r"C:\Program Files (x86)\iShowII_EN",
               r"C:\Program Files\iShowII", r"C:\Program Files (x86)\iShowII",
               r"C:\Program Files\iShow", r"C:\Program Files (x86)\iShow"]


ISHOW_SUBFOLDERS = [os.path.join("Quickframe", "A"), os.path.join("Quickframe", "B"),
                    os.path.join("Quickframe", "C"), "Frames", "ILDAimage", "Drawing"]


def find_ishow_folders():
    """iShow II content folders (Quickframe A/B/C, Frames, ILDAimage, Drawing), from the usual
    locations. The first location that has a folder wins, so nothing is listed twice."""
    found, seen = [], set()
    for home in ISHOW_HOMES:
        for sub in ISHOW_SUBFOLDERS:
            folder = os.path.join(home, sub)
            if sub not in seen and os.path.isdir(folder):
                found.append(folder)
                seen.add(sub)
    return found


def folder_title(folder):
    name = os.path.basename(folder) or folder
    parent = os.path.basename(os.path.dirname(folder))
    if parent.lower() == "quickframe":
        return f"Quickframe {name}"
    return {"Drawing": "Drawings", "ILDAimage": "ILDA images", "Frames": "Frames"}.get(name, f"Folder: {name}")


COLLAPSE_ABOVE = 500   # sections with more files than this start collapsed (Drawing: 2,629)
PAGE = 120             # preview icons made per "Show more" click: thousands of icons make Tk crawl
ILF_FPS = 10           # default speed of iShow .ilf animations (most have only 2-12 frames)

BG, PANEL, BEAM = "#15171c", "#1f232b", "#39ff6a"
PREVIEW = 205   # size of the "Now showing" preview, in pixels
LIGHT_COLOURS = {"off": "#555a63", "ok": "#2ecc40", "warn": "#ffb000", "bad": "#ff4136"}


# ----------------------------------------------------------------------------
# USB worker: the only thread that touches the box
# ----------------------------------------------------------------------------
class LaserWorker(threading.Thread):
    def __init__(self, events):
        super().__init__(daemon=True)
        self.cmds = queue.Queue()
        self.events = events
        self.dac = None
        self.item = None
        self.t0 = 0.0

    def post(self, kind, data=None):
        self.events.put((kind, data))

    def run(self):
        last_status = 0.0
        while True:
            busy = self.dac is not None and self.item is not None
            try:
                while True:
                    cmd, arg = self.cmds.get_nowait() if busy else self.cmds.get(timeout=0.05)
                    if self._handle(cmd, arg) == "quit":
                        return
                    busy = self.dac is not None and self.item is not None
            except queue.Empty:
                pass
            if self.dac is None:
                continue
            try:
                if self.item is not None:
                    self.dac.send_frame(self.item.frame_at(time.monotonic() - self.t0))
                if time.monotonic() - last_status > 1.0:
                    self.post("status", self.dac.status())
                    last_status = time.monotonic()
            except (usb.core.USBError, RuntimeError, ValueError) as e:
                self.post("error", f"Lost contact with the box: {e}")
                self._drop()

    def _handle(self, cmd, arg):
        if cmd == "quit":
            self._close()
            return "quit"
        if cmd == "connect":
            self._close()
            settings, demo = arg
            self.post("connecting", None)
            try:
                device = None
                if demo:
                    from fake_usb_box import FakeBox
                    device = FakeBox()
                dac = IShowUSB(settings["rate"], settings["limit"], settings["invert_x"],
                               settings["invert_y"], settings["swap_xy"], settings["mono_green"],
                               device=device, line_step=settings["line_step"])
                dac.open()
                self.dac = dac
                self.post("connected", {"uploaded": dac.firmware_uploaded, "demo": demo})
            except Exception as e:  # noqa: BLE001 - reported to the user
                self.dac = None
                self.post("connect_failed", str(e))
        elif cmd == "disconnect":
            self._close()
            self.post("disconnected", None)
        elif cmd == "play":
            self.item = arg
            self.t0 = time.monotonic()
        elif cmd == "stop":
            self.item = None
            if self.dac:
                try:
                    self.dac.blank()
                except usb.core.USBError:
                    pass
        elif cmd == "settings" and self.dac:
            s = arg
            self.dac.configure(s["limit"], s["invert_x"], s["invert_y"], s["swap_xy"], s["mono_green"])
            try:
                self.dac.set_rate(s["rate"])
                self.dac.set_line_step(s["line_step"])
            except usb.core.USBError as e:
                self.post("error", str(e))
        return None

    def _drop(self):
        self.dac = None
        self.item = None

    def _close(self):
        if self.dac:
            try:
                self.dac.close()
            except Exception:  # noqa: BLE001
                pass
        self._drop()


# ----------------------------------------------------------------------------
# GUI pieces
# ----------------------------------------------------------------------------
def draw_points(canvas, points, size, pad=4, width=1, max_points=1500, polylines=None):
    """Draw a frame. polylines: already made by patterns.preview_polylines (e.g. in a thread)."""
    canvas.delete("all")
    span = size - 2 * pad
    if polylines is None:
        polylines = patterns.preview_polylines(points, max_points)
    for line in polylines:
        xy = [pad + (v + 1) / 2 * span if k % 2 == 0 else pad + (1 - v) / 2 * span
              for k, v in enumerate(line)]
        canvas.create_line(*xy, fill=BEAM, width=width, capstyle="round", joinstyle="round")


class Light(tk.Frame):
    def __init__(self, master, text):
        super().__init__(master, bg=PANEL)
        self.dot = tk.Canvas(self, width=16, height=16, bg=PANEL, highlightthickness=0)
        self.oval = self.dot.create_oval(2, 2, 14, 14, fill=LIGHT_COLOURS["off"], outline="")
        self.dot.pack(side="left")
        tk.Label(self, text=text, bg=PANEL, fg="#d8dde6", font=("Segoe UI", 9)).pack(side="left", padx=(3, 10))

    def set(self, state):
        self.dot.itemconfig(self.oval, fill=LIGHT_COLOURS[state])


class Tile(tk.Frame):
    SIZE = 104

    def __init__(self, master, item, on_click, on_menu):
        super().__init__(master, bg=PANEL, highlightthickness=2, highlightbackground=PANEL)
        self.item = item
        self.canvas = tk.Canvas(self, width=self.SIZE, height=self.SIZE, bg="black",
                                highlightthickness=0, cursor="hand2")
        self.canvas.pack(padx=4, pady=(4, 0))
        try:
            icon = getattr(item, "icon", None)    # made by the loader thread for folder files
            draw_points(self.canvas, None if icon else item.preview_frame(), self.SIZE,
                        max_points=600, polylines=icon)
        except Exception:  # noqa: BLE001 - a broken file still gets a tile
            self.canvas.create_text(self.SIZE / 2, self.SIZE / 2, text="?", fill="red")
        self.label = tk.Label(self, text=item.name, bg=PANEL, fg="#d8dde6", wraplength=self.SIZE,
                              font=("Segoe UI", 8), cursor="hand2")
        self.label.pack(padx=4, pady=(2, 4))
        for w in (self, self.canvas, self.label):
            w.bind("<Button-1>", lambda e: on_click(self))
            w.bind("<Button-3>", lambda e: on_menu(self, e))     # right-click
            w.bind("<Button-2>", lambda e: on_menu(self, e))     # right-click on a Mac

    def select(self, on):
        self.config(highlightbackground=BEAM if on else PANEL)


FPS, SPF = "frames per second", "seconds per frame"


def _num(v):
    """1.0 -> '1', 0.25 -> '0.25'"""
    return f"{v:.2f}".rstrip("0").rstrip(".")


class PreviewWindow(tk.Toplevel):
    """A large, animated preview of one item. Nothing is sent to the laser."""
    SIZE = 440

    def __init__(self, app, item):
        super().__init__(app.root, bg=PANEL)
        self.app, self.item = app, item
        self.title(f"Preview \u2013 {item.name}")
        self.resizable(False, False)
        self.canvas = tk.Canvas(self, width=self.SIZE, height=self.SIZE, bg="black", highlightthickness=0)
        self.canvas.pack(padx=10, pady=(10, 6))
        self.info = tk.StringVar(value="")
        tk.Label(self, textvariable=self.info, bg=PANEL, fg="#d8dde6", font=("Segoe UI", 9),
                 justify="left", wraplength=self.SIZE).pack(anchor="w", padx=10)
        buttons = tk.Frame(self, bg=PANEL)
        buttons.pack(fill="x", padx=10, pady=10)
        self.buttons = buttons
        self.speed_row = None
        self.last_key = None
        ttk.Button(buttons, text="Show on laser", command=self._show).pack(side="left")
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda e: self.close())
        self.t0 = time.monotonic()
        self.load_error = None
        if not item.loaded:
            self.info.set("Loading the whole file\u2026")
            threading.Thread(target=self._load, daemon=True).start()
        self._tick()

    def _load(self):
        try:
            self.item.load()
        except Exception as e:  # noqa: BLE001
            self.load_error = str(e)

    def _tick(self):
        if not self.winfo_exists():
            return
        item = self.item
        t = time.monotonic() - self.t0
        pts, self.last_key, delay = item.frame_due(t, self.last_key)
        self.after(delay, self._tick)
        if self.speed_row is not None and item.frames:
            n, per = len(item.frames), 1 / item.fps
            i = int(t * item.fps)
            text = f"Frame {i % n + 1} of {n}"
            if per >= 2:
                text += f" • next in {max(0, (i + 1) * per - t):.0f} s"
            self.frame_var.set(text)
        if pts is None:          # same frame as last time: nothing to redraw
            return
        draw_points(self.canvas, pts, self.SIZE, pad=10, width=2, max_points=4000)
        if item.loaded and item.frames and len(item.frames) > 1 and self.speed_row is None:
            self._add_speed_row()
        if self.load_error:
            self.info.set(f"Couldn't read the whole file: {self.load_error}")
        elif item.loaded:
            rate = self.app.settings["rate"] * 1000
            if item.generator:
                what = "Animated picture"
            elif len(item.frames) > 1:
                what = (f"{len(item.frames)} frames, {_num(1 / item.fps)} seconds each" if item.fps < 1
                        else f"Animation: {len(item.frames)} frames at {_num(item.fps)} frames/s")
            else:
                what = "Still picture"
            lines = [what]
            if item.kind == "file":
                most = max(len(f) for f in item.frames)
                lines.append(f"Up to {most:,} points per frame \u2192 the laser redraws it about "
                             f"{rate / most:.0f} times a second at your scan speed"
                             + (" (may flicker)" if rate / most < 20 else ""))
            else:
                lines.append(f"{len(pts)} corner points; the box's chip draws the lines between them")
            self.info.set("\n".join(lines))

    def _add_speed_row(self):
        """Speed for multi-frame files, as frames per second or seconds per frame (for files that
        are really a set of separate pictures). Remembered per file and used on the laser too."""
        row = tk.Frame(self, bg=PANEL)
        row.pack(fill="x", padx=10, before=self.buttons)
        tk.Label(row, text="Speed", bg=PANEL, fg="#d8dde6", font=("Segoe UI", 9)).pack(side="left")
        self.speed_var = tk.StringVar()
        self.unit_var = tk.StringVar(value=SPF if self.item.fps < 1 else FPS)
        spin = ttk.Spinbox(row, textvariable=self.speed_var, width=6, command=self._speed_changed)
        spin.pack(side="left", padx=(6, 4))
        unit = ttk.Combobox(row, textvariable=self.unit_var, values=[FPS, SPF], state="readonly", width=17)
        unit.pack(side="left")
        for ev in ("<Return>", "<FocusOut>"):
            spin.bind(ev, lambda e: self._speed_changed())
        unit.bind("<<ComboboxSelected>>", lambda e: self._show_speed())
        ttk.Button(row, text="Default", command=self._default_speed).pack(side="right")
        self.spin = spin
        self.frame_var = tk.StringVar()
        row2 = tk.Frame(self, bg=PANEL)
        row2.pack(fill="x", padx=10, pady=(4, 0), before=self.buttons)
        tk.Label(row2, textvariable=self.frame_var, bg=PANEL, fg="#8b93a1", font=("Segoe UI", 9),
                 anchor="w").pack(side="left")
        folder = os.path.dirname(self.item.path or "")
        if folder in self.app.folder_sections:
            ttk.Button(row2, text="Use this speed for the whole folder",
                       command=lambda: self.app.set_folder_speed(folder, self.item.fps)).pack(side="right")
        self.speed_row = row
        self._show_speed()

    def _show_speed(self):
        """Put the item's current speed in the box, in the chosen unit."""
        fps = self.item.fps
        if self.unit_var.get() == SPF:
            self.spin.config(from_=0.5, to=600, increment=1)
            self.speed_var.set(_num(1 / fps))
        else:
            self.spin.config(from_=1, to=60, increment=1)
            self.speed_var.set(_num(fps))

    def _speed_changed(self):
        try:
            v = float(self.speed_var.get())
        except ValueError:
            self._show_speed()
            return
        if self.unit_var.get() == SPF:
            fps = 1 / min(600.0, max(0.1, v))
        else:
            fps = min(60.0, max(0.1, v))
        self._set_fps(fps)
        self._save_speed()

    def _default_speed(self):
        self._set_fps(self.app.default_fps(self.item.path))
        self.unit_var.set(FPS)
        self._show_speed()
        self._save_speed(reset=True)

    def _set_fps(self, fps):
        fps = round(fps, 6)
        if fps != self.item.fps:
            # keep showing the same frame instead of jumping to another one
            now = time.monotonic()
            self.t0 = now - (now - self.t0) * self.item.fps / fps
            self.item.fps = fps
            self.last_key = None

    def _save_speed(self, reset=False):
        if self.item.path and self.winfo_exists():
            self.app.set_file_speed(self.item.path, None if reset else self.item.fps)

    def _show(self):
        self.t0, self.last_key = time.monotonic(), None    # start in step with the laser
        self.app.play(self.item)
        for t in self.app.tiles:
            t.select(t.item is self.item)

    def close(self):
        item = self.item
        if item is not self.app.current and item.kind == "file" and item.path and item.loaded:
            item.frames = None   # free the memory again
        self.destroy()


class ScrollFrame(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.win, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))


class App:
    def __init__(self, root, demo=False):
        self.root, self.demo = root, demo
        self.settings = dict(DEFAULT_SETTINGS)
        self._load_settings()
        self.events = queue.Queue()
        self.worker = LaserWorker(self.events)
        self.worker.start()
        self.connected = False
        self.last_reply = 0.0
        self.current = None
        self.current_t0 = time.monotonic()
        self.preview_key = None
        self.tiles = []
        self.file_tiles = []

        root.title(APP_NAME + (" (demo mode)" if demo else ""))
        root.configure(bg=BG)
        root.geometry("1180x740")
        root.minsize(980, 640)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10), padding=6)
        style.configure("Stop.TButton", font=("Segoe UI", 12, "bold"), foreground="white",
                        background="#c0392b", padding=8)
        style.map("Stop.TButton", background=[("active", "#e74c3c")])
        style.configure("TCheckbutton", background=PANEL, foreground="#d8dde6")
        style.configure("TLabelframe", background=PANEL, foreground="#d8dde6")
        style.configure("TLabelframe.Label", background=PANEL, foreground="#d8dde6",
                        font=("Segoe UI", 10, "bold"))

        self._build_top()
        self.status_var = tk.StringVar(value="Not connected. Press Connect.")
        tk.Label(root, textvariable=self.status_var, anchor="w", bg=PANEL, fg="#aab2bf",
                 font=("Segoe UI", 9), padx=8, pady=3).pack(fill="x", side="bottom")
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self._build_left(body)
        self._build_library(body)

        root.bind("<Escape>", lambda e: self.stop())
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(50, self._poll_events)
        root.after(80, self._animate_preview)

    # -- layout ----------------------------------------------------------------
    def _build_top(self):
        bar = tk.Frame(self.root, bg=PANEL)
        bar.pack(fill="x", padx=10, pady=10)
        self.connect_btn = ttk.Button(bar, text="Connect", command=self.connect)
        self.connect_btn.pack(side="left", padx=(8, 4), pady=8)
        self.disconnect_btn = ttk.Button(bar, text="Disconnect", command=self.disconnect, state="disabled")
        self.disconnect_btn.pack(side="left", padx=4)
        tk.Frame(bar, width=20, bg=PANEL).pack(side="left")
        self.light_usb = Light(bar, "USB box")
        self.light_fw = Light(bar, "Firmware")
        self.light_link = Light(bar, "Responding")
        for lt in (self.light_usb, self.light_fw, self.light_link):
            lt.pack(side="left")
        self.driver_btn = ttk.Button(bar, text="Install driver", command=self.install_driver)
        self.driver_btn.pack(side="left", padx=(0, 10))
        if os.name != "nt":
            self.driver_btn.config(state="disabled")
        self.info_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.info_var, bg=PANEL, fg="#8b93a1",
                 font=("Segoe UI", 9)).pack(side="left", padx=10)
        ttk.Button(bar, text="■  STOP / BLANK", style="Stop.TButton",
                   command=self.stop).pack(side="right", padx=8, pady=6)

    def _build_left(self, body):
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="y", padx=(0, 10))

        now = ttk.LabelFrame(left, text="Now showing", padding=8)
        now.pack(fill="x")
        self.preview = tk.Canvas(now, width=PREVIEW, height=PREVIEW, bg="black", highlightthickness=0)
        self.preview.pack()
        self.now_var = tk.StringVar(value="(nothing – beam off)")
        tk.Label(now, textvariable=self.now_var, bg=PANEL, fg=BEAM, font=("Segoe UI", 10, "bold"),
                 wraplength=PREVIEW).pack(pady=(4, 0))

        txt = ttk.LabelFrame(left, text="Laser text (up to 2 lines)", padding=8)
        txt.pack(fill="x", pady=6)
        self.text_box = tk.Text(txt, height=2, width=30, font=("Consolas", 14), bg="black", fg=BEAM,
                                insertbackground=BEAM, wrap="none")
        self.text_box.pack(fill="x")
        self.text_box.insert("1.0", "HELLO")
        self.text_box.bind("<KeyRelease>", self._limit_text)
        fx = tk.Frame(txt, bg=PANEL)
        fx.pack(fill="x", pady=(6, 0))
        self.var_effect = tk.StringVar(value=self.settings["text_effect"])
        self.var_tspeed = tk.StringVar(value=self.settings["text_speed"])
        tk.Label(fx, text="Effect", bg=PANEL, fg="#d8dde6", font=("Segoe UI", 9)).pack(side="left")
        effect = ttk.Combobox(fx, textvariable=self.var_effect, values=shows.TEXT_EFFECTS,
                              state="readonly", width=11)
        effect.pack(side="left", padx=(4, 10))
        tk.Label(fx, text="Speed", bg=PANEL, fg="#d8dde6", font=("Segoe UI", 9)).pack(side="left")
        speed = ttk.Combobox(fx, textvariable=self.var_tspeed, values=list(shows.TEXT_SPEEDS),
                             state="readonly", width=7)
        speed.pack(side="left", padx=4)
        for box in (effect, speed):
            box.bind("<<ComboboxSelected>>", self._text_effect_changed)
        ttk.Button(fx, text="Show text", command=self.show_text).pack(side="right")

        st = ttk.LabelFrame(left, text="Settings", padding=8)
        st.pack(fill="x")
        self.var_rate = tk.IntVar(value=self.settings["rate"])
        self.var_limit = tk.DoubleVar(value=self.settings["limit"])
        self.var_fps = tk.IntVar(value=self.settings["file_fps"])
        self.var_step = tk.IntVar(value=self.settings["line_step"])
        self.var_mono = tk.BooleanVar(value=self.settings["mono_green"])
        self.var_ix = tk.BooleanVar(value=self.settings["invert_x"])
        self.var_iy = tk.BooleanVar(value=self.settings["invert_y"])
        self.var_swap = tk.BooleanVar(value=self.settings["swap_xy"])
        rows = [("Scan speed (thousand points/s)", self.var_rate, 5, 40, 1),
                ("Output limit (volts, ILDA = 5)", self.var_limit, 1.0, 8.0, 0.5),
                ("Laser file speed (frames/s)", self.var_fps, 5, 60, 1),
                ("Line detail (1 = finest, 8 = fastest)", self.var_step, 1, 8, 1)]
        for i, (label, var, lo, hi, inc) in enumerate(rows):
            tk.Label(st, text=label, bg=PANEL, fg="#d8dde6", font=("Segoe UI", 9)).grid(row=i, column=0, sticky="w")
            spin = ttk.Spinbox(st, from_=lo, to=hi, increment=inc, textvariable=var, width=6,
                               command=self.apply_settings)
            spin.grid(row=i, column=1, padx=6, pady=2)
            spin.bind("<Return>", lambda e: self.apply_settings())
            spin.bind("<FocusOut>", lambda e: self.apply_settings())
        checks = [("Green-only laser", self.var_mono), ("Mirror left/right", self.var_ix),
                  ("Flip upside down", self.var_iy), ("Swap X and Y", self.var_swap)]
        for i, (label, var) in enumerate(checks):
            ttk.Checkbutton(st, text=label, variable=var, command=self.apply_settings).grid(
                row=len(rows) + i // 2, column=i % 2, sticky="w", pady=2)

    def _build_library(self, body):
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        head = tk.Frame(right, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Click to show on the laser \u2022 right-click to preview", bg=BG, fg="#d8dde6",
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(head, text="Add laser files…", command=self.add_files).pack(side="right")
        ttk.Button(head, text="Add folder…", command=self.add_folder).pack(side="right", padx=6)
        self.scroll = ScrollFrame(right)
        self.scroll.pack(fill="both", expand=True, pady=(6, 0))

        items = patterns.builtin_items()
        self.sec_shows = self._section("Shows")
        for it in shows.show_items():
            self._add_tile(self.sec_shows, it)
        self.sec_test = self._section("Test patterns")
        self.sec_pics = self._section("Pictures")
        self.sec_files = self._section("My laser files")
        for it in items:
            self._add_tile(self.sec_test if it.kind == "test" else self.sec_pics, it)
        self.empty_files = tk.Label(self.sec_files, text="No laser files yet. Use “Add laser files”.",
                                    bg=BG, fg="#8b93a1", font=("Segoe UI", 9))
        self.folder_sections = {}
        self.parse_q = queue.Queue()
        self.ready_tiles = collections.deque()
        self.tiles_waiting = 0
        threading.Thread(target=self._parse_loop, daemon=True).start()
        self.root.after(30, self._drain_tiles)
        self._load_library_files()
        self._auto_link_ishow()
        for folder in list(self.settings["folders"]):
            self._open_folder(folder)

    def _section(self, title, on_remove=None):
        head = tk.Frame(self.scroll.inner, bg=BG)
        head.pack(fill="x", pady=(10, 4))
        label = tk.Label(head, text=title, bg=BG, fg="#8b93a1", anchor="w", font=("Segoe UI", 10, "bold"))
        label.pack(side="left")
        if on_remove:
            ttk.Button(head, text="Remove folder", command=on_remove).pack(side="right")
        frame = tk.Frame(self.scroll.inner, bg=BG)
        frame.pack(fill="x")
        frame.count = 0
        frame.head, frame.label, frame.tiles = head, label, []
        return frame

    def _add_tile(self, section, item, removable=False):
        tile = Tile(section, item, self.play_tile, self.tile_menu)
        cols = 6
        tile.grid(row=section.count // cols, column=section.count % cols, padx=4, pady=4, sticky="n")
        section.count += 1
        self.tiles.append(tile)
        section.tiles.append(tile)
        if removable:
            self.file_tiles.append(tile)
        return tile

    def _relayout_files(self):
        for t in self.file_tiles:
            t.grid_forget()
        self.sec_files.count = 0
        for t in self.file_tiles:
            t.grid(row=self.sec_files.count // 6, column=self.sec_files.count % 6, padx=4, pady=4, sticky="n")
            self.sec_files.count += 1
        if self.file_tiles:
            self.empty_files.grid_forget()
        else:
            self.empty_files.grid(row=0, column=0, columnspan=6, sticky="w")

    # -- library files ---------------------------------------------------------
    def _load_library_files(self):
        os.makedirs(LIBRARY_DIR, exist_ok=True)
        for name in sorted(os.listdir(LIBRARY_DIR)):
            if name.lower().endswith(patterns.LASER_FILE_TYPES):
                try:
                    self._add_file_item(os.path.join(LIBRARY_DIR, name))
                except Exception as e:  # noqa: BLE001
                    self.log(f"Skipped {name}: {e}")
        self._relayout_files()

    def default_fps(self, path):
        return ILF_FPS if path and path.lower().endswith(".ilf") else self.settings["file_fps"]

    def fps_for(self, path):
        return self.settings["file_speeds"].get(path) or self.default_fps(path)

    def set_file_speed(self, path, fps):
        speeds = self.settings["file_speeds"]
        if fps is None or fps == self.default_fps(path):
            speeds.pop(path, None)
        else:
            speeds[path] = round(float(fps), 6)
        self._save_settings()

    def set_folder_speed(self, folder, fps):
        """Give every multi-frame file in a linked folder the same speed (e.g. 30 s per frame)."""
        sec = self.folder_sections.get(folder)
        if sec is None:
            return
        for path in sec.paths:
            if fps == self.default_fps(path):
                self.settings["file_speeds"].pop(path, None)
            else:
                self.settings["file_speeds"][path] = round(float(fps), 6)
        for t in sec.tiles:
            t.item.fps = self.fps_for(t.item.path)
        self._save_settings()
        each = f"{_num(1 / fps)} seconds per frame" if fps < 1 else f"{_num(fps)} frames per second"
        self.log(f"{folder_title(folder)}: all {len(sec.paths)} files now play at {each}.")

    def _add_file_item(self, path):
        item = patterns.file_item(path, lazy=True)
        item.fps = self.fps_for(path)
        self._add_tile(self.sec_files, item, removable=True)

    # -- linked folders (e.g. iShow's ILDAimage folder): files stay where they are ----------
    def add_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder of .ild laser files")
        if not folder:
            return
        folder = os.path.normpath(folder)
        if folder in self.settings["folders"]:
            messagebox.showinfo(APP_NAME, "That folder is already in your library.")
            return
        if folder in self.settings["removed_folders"]:
            self.settings["removed_folders"].remove(folder)
        if not self._ild_files(folder):
            messagebox.showinfo(APP_NAME, "No laser files (.ild, .ilf, .ddr) in that folder.")
            return
        self.settings["folders"].append(folder)
        self._save_settings()
        self._open_folder(folder)

    def _auto_link_ishow(self):
        """Link the original iShow II's laser files automatically, every start, unless the user
        removed that folder."""
        skip = set(self.settings["folders"]) | set(self.settings["removed_folders"])
        new = [f for f in find_ishow_folders() if f not in skip and self._ild_files(f)]
        if not new:
            return
        self.settings["folders"] += new
        self._save_settings()
        if new:
            self.root.after(500, lambda: self.log("Found the original iShow II laser files and added them: "
                                                  + ", ".join(new)))

    @staticmethod
    def _ild_files(folder):
        try:
            return sorted((n for n in os.listdir(folder) if n.lower().endswith(patterns.LASER_FILE_TYPES)),
                          key=str.lower)
        except OSError:
            return []

    def _open_folder(self, folder):
        names = self._ild_files(folder)
        title = f"{folder_title(folder)}  ({len(names)})"
        if not names:
            title += " – not found"
        sec = self._section(title, on_remove=lambda f=folder: self.remove_folder(f))
        sec.paths = [os.path.join(folder, n) for n in names]
        sec.requested = 0          # how many of sec.paths have been sent to the loader
        sec.dead = False
        sec.more = ttk.Button(sec, command=lambda s=sec: self._request_page(s))
        sec.shown = len(names) <= COLLAPSE_ABOVE
        sec.toggle = ttk.Button(sec.head, command=lambda s=sec: self._toggle_section(s))
        sec.toggle.pack(side="right", padx=6)
        self.folder_sections[folder] = sec
        self._show_section(sec, sec.shown)

    def _show_section(self, sec, show):
        sec.shown = show
        sec.toggle.config(text="Hide" if show else f"Show ({len(sec.paths)})")
        if show:
            if not sec.requested:
                self._request_page(sec)
            sec.pack(fill="x", after=sec.head)
        else:
            sec.pack_forget()

    def _toggle_section(self, sec):
        self._show_section(sec, not sec.shown)

    def _request_page(self, sec):
        """Queue the next PAGE files of a section for the background loader."""
        start, sec.requested = sec.requested, min(len(sec.paths), sec.requested + PAGE)
        for path in sec.paths[start:sec.requested]:
            self.tiles_waiting += 1
            self.parse_q.put((sec, path))
        left = len(sec.paths) - sec.requested
        if left:
            sec.more.config(text=f"Show {min(PAGE, left)} more  ({left:,} not shown yet)")
            sec.more.grid(row=len(sec.paths) // 6 + 1, column=0, columnspan=6, sticky="w", padx=4, pady=(4, 8))
        else:
            sec.more.grid_forget()

    def _parse_loop(self):
        """Background thread: reads each file's first frame and works out its icon, so the window
        never waits on the disk. Tk widgets are only made on the main thread (_drain_tiles)."""
        while True:
            sec, path = self.parse_q.get()
            if sec.dead:
                self.ready_tiles.append((sec, path, None, None))
                continue
            try:
                item = patterns.file_item(path, lazy=True)
                item.icon = patterns.preview_polylines(item.first, 600)
                self.ready_tiles.append((sec, path, item, None))
            except Exception as e:  # noqa: BLE001 - a bad file shouldn't stop the rest
                self.ready_tiles.append((sec, path, None, str(e)))

    def _drain_tiles(self):
        """Make the icons the loader has finished, for at most ~30 ms at a time, so the window
        keeps responding while a big folder fills in."""
        end = time.perf_counter() + 0.03
        made = False
        while self.ready_tiles and time.perf_counter() < end:
            sec, path, item, err = self.ready_tiles.popleft()
            self.tiles_waiting -= 1
            made = True
            if sec.dead:
                continue
            if err:
                self.log(f"Skipped {os.path.basename(path)}: {err}")
                continue
            item.fps = self.fps_for(path)
            self._add_tile(sec, item)
        if made:
            self.log(f"Loading previews… {self.tiles_waiting:,} to go" if self.tiles_waiting
                     else "Library ready.")
        self.root.after(15 if self.ready_tiles else 60, self._drain_tiles)

    def remove_folder(self, folder):
        if not messagebox.askyesno(APP_NAME, f"Remove the folder “{folder}” from your library?\n\n"
                                             "(The files themselves are not deleted.)"):
            return
        sec = self.folder_sections.pop(folder, None)
        if folder in self.settings["folders"]:
            self.settings["folders"].remove(folder)
        if folder not in self.settings["removed_folders"]:
            self.settings["removed_folders"].append(folder)
        self._save_settings()
        if sec is not None:
            sec.dead = True        # the loader skips the rest of its files
            if self.current is not None and any(t.item is self.current for t in sec.tiles):
                self.stop()
            for t in sec.tiles:
                self.tiles.remove(t)
            sec.head.destroy()
            sec.destroy()

    def add_files(self):
        paths = filedialog.askopenfilenames(title="Add laser files",
                                            filetypes=[("Laser files", "*.ild *.ILD *.ilf *.ddr *.DDR"),
                                                       ("All files", "*.*")])
        added = 0
        for src in paths:
            try:
                patterns.file_item(src, lazy=True)   # validate before copying
                dest = os.path.join(LIBRARY_DIR, os.path.basename(src))
                base, ext = os.path.splitext(dest)
                n = 2
                while os.path.exists(dest):
                    dest = f"{base} ({n}){ext}"
                    n += 1
                shutil.copy2(src, dest)
                self._add_file_item(dest)
                added += 1
            except Exception as e:  # noqa: BLE001
                messagebox.showerror(APP_NAME, f"Couldn't read {os.path.basename(src)}:\n{e}\n\n"
                                               "Supported: ILDA (.ild) and iShow (.ilf, .ddr) files.")
        self._relayout_files()
        if added:
            self.log(f"Added {added} laser file(s).")

    def tile_menu(self, tile, event):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Preview\u2026", command=lambda: PreviewWindow(self, tile.item))
        m.add_command(label="Show on laser", command=lambda: self.play_tile(tile))
        if tile in self.file_tiles:
            m.add_separator()
            m.add_command(label=f"Remove \u201c{tile.item.name}\u201d", command=lambda: self.remove_file(tile))
        m.tk_popup(event.x_root, event.y_root)

    def remove_file(self, tile):
        if not messagebox.askyesno(APP_NAME, f"Remove “{tile.item.name}” from your laser files?"):
            return
        if self.current is tile.item:
            self.stop()
        try:
            os.remove(tile.item.path)
        except OSError:
            pass
        self.file_tiles.remove(tile)
        self.tiles.remove(tile)
        tile.destroy()
        self._relayout_files()

    # -- actions ---------------------------------------------------------------
    def connect(self):
        self.apply_settings(send=False)
        self.worker.cmds.put(("connect", (dict(self.settings), self.demo)))

    def disconnect(self):
        self.worker.cmds.put(("disconnect", None))

    def play_tile(self, tile):
        self.play(tile.item)
        for t in self.tiles:
            t.select(t is tile)

    def play(self, item):
        previous = self.current
        self.current = item
        self.current_t0 = time.monotonic()
        self.preview_key = None
        self.now_var.set(item.name)
        if previous is not None and previous is not item and previous.kind == "file" and previous.path:
            previous.frames = None          # free the memory of the file we're leaving
        if not item.loaded:
            self.worker.cmds.put(("stop", None))      # beam off while the file loads
            self.log(f"Loading {item.name}…")
            threading.Thread(target=self._load_in_background, args=(item,), daemon=True).start()
            return
        if self.connected:
            self.worker.cmds.put(("play", item))
            self.log(f"Showing: {item.name}")
        else:
            self.log(f"Previewing {item.name}. Connect to show it on the laser.")

    # -- driver install (Windows) ------------------------------------------------------------
    def install_driver(self):
        if not messagebox.askokcancel(APP_NAME,
                "This installs Windows' own WinUSB driver for the laser box (USB 3333:6666), "
                "the same thing Zadig does.\n\n"
                "Windows will ask for permission. A certificate that is trusted only on this PC "
                "is created to approve the driver; its private key is deleted straight away.\n\n"
                "Continue?"):
            return
        self.driver_btn.config(state="disabled")
        self.log("Installing the driver\u2026 (approve the Windows prompt)")
        threading.Thread(target=self._run_driver_install, daemon=True).start()

    def _run_driver_install(self):
        log = os.path.join(tempfile.gettempdir(), "ishow_driver_install.log")
        try:
            os.remove(log)
        except OSError:
            pass
        if getattr(sys, "frozen", False):
            exe, args = sys.executable, ["--install-driver", "--log", log]
        else:
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "winusb_install.py")
            exe, args = sys.executable, [script, "--install", "--log", log]
        arglist = " ".join(f'"{a}"' if " " in a else a for a in args).replace("'", "''")
        ps = (f"Start-Process -FilePath '{exe}' -ArgumentList '{arglist}' "
              "-Verb RunAs -Wait -WindowStyle Hidden")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            with open(log, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        if r.returncode != 0 and not text:
            self.events.put(("driver", (False, "Cancelled, or Windows didn't allow it.\n" + r.stderr.strip()[-400:])))
        elif "RESULT: OK" in text:
            self.events.put(("driver", (True, text)))
        else:
            self.events.put(("driver", (False, text[-1500:] or "No result was reported.")))

    def _load_in_background(self, item):
        try:
            item.load()
            self.events.put(("loaded", item))
        except Exception as e:  # noqa: BLE001
            self.events.put(("load_failed", (item, str(e))))

    def stop(self):
        self.current = None
        self.now_var.set("(nothing – beam off)")
        self.preview.delete("all")
        for t in self.tiles:
            t.select(False)
        self.worker.cmds.put(("stop", None))
        self.log("Stopped. Beam blanked.")

    def show_text(self):
        lines = self.text_box.get("1.0", "end").splitlines()[:2]
        if not any(ln.strip() for ln in lines):
            messagebox.showinfo(APP_NAME, "Type some text first.")
            return
        for t in self.tiles:
            t.select(False)
        self.play(shows.text_effect_item(lines, self.var_effect.get(), self.var_tspeed.get()))

    def _text_effect_changed(self, event=None):
        self.settings["text_effect"] = self.var_effect.get()
        self.settings["text_speed"] = self.var_tspeed.get()
        self._save_settings()
        if self.current is not None and self.current.kind == "text":
            self.show_text()          # the text on the laser now picks up the new effect

    def _limit_text(self, event=None):
        lines = self.text_box.get("1.0", "end-1c").split("\n")
        if len(lines) > 2:
            self.text_box.delete("3.0", "end")

    def apply_settings(self, send=True):
        try:
            s = {"rate": int(self.var_rate.get()), "limit": float(self.var_limit.get()),
                 "file_fps": int(self.var_fps.get()), "mono_green": bool(self.var_mono.get()),
                 "line_step": int(self.var_step.get()),
                 "invert_x": bool(self.var_ix.get()), "invert_y": bool(self.var_iy.get()),
                 "swap_xy": bool(self.var_swap.get())}
        except (tk.TclError, ValueError):
            return
        s["rate"] = max(5, min(40, s["rate"]))
        s["limit"] = max(1.0, min(8.0, s["limit"]))
        s["file_fps"] = max(5, min(60, s["file_fps"]))
        s["line_step"] = max(1, min(8, s["line_step"]))
        if s["limit"] > 5.0 and self.settings["limit"] <= 5.0 and send:
            if not messagebox.askyesno(APP_NAME, "Output above 5 V is beyond the ILDA standard and can "
                                                 "overdrive the laser's mirrors.\n\nUse it anyway?"):
                self.var_limit.set(self.settings["limit"])
                return
        self.settings = {**self.settings, **s}     # keep folders, file speeds, text effect…
        s = self.settings
        for t in self.tiles:
            if t.item.path:
                t.item.fps = self.fps_for(t.item.path)
        self._save_settings()
        if send:
            self.worker.cmds.put(("settings", dict(s)))

    def log(self, text):
        self.status_var.set(text)

    # -- worker events and timers ------------------------------------------------
    def _poll_events(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                self._on_event(kind, data)
        except queue.Empty:
            pass
        if self.connected:
            age = time.monotonic() - self.last_reply
            self.light_link.set("ok" if age < 2.5 else "warn" if age < 6 else "bad")
        self.root.after(100, self._poll_events)

    def _on_event(self, kind, data):
        if kind == "driver":
            ok, text = data
            self.driver_btn.config(state="normal")
            if ok:
                self.log("Driver installed.")
                messagebox.showinfo(APP_NAME, "Driver installed.\n\nUnplug the laser box, plug it back in, "
                                              "then press Connect.")
            else:
                self.log("Driver install failed.")
                messagebox.showerror(APP_NAME, "The driver install didn't work:\n\n" + text +
                                     "\n\nYou can still install it the old way with Zadig "
                                     "(WinUSB for Unknown device 3333 6666).")
            return
        if kind == "loaded":
            if data is self.current:
                self.play(data)
            return
        if kind == "load_failed":
            item, err = data
            if item is self.current:
                self.stop()
            messagebox.showerror(APP_NAME, f"Couldn't read {item.name}:\n{err}")
            return
        if kind == "connecting":
            self.log("Connecting…")
            self.connect_btn.config(state="disabled")
            for lt in (self.light_usb, self.light_fw, self.light_link):
                lt.set("warn")
        elif kind == "connected":
            self.connected = True
            self.last_reply = time.monotonic()
            for lt in (self.light_usb, self.light_fw, self.light_link):
                lt.set("ok")
            self.connect_btn.config(state="normal", text="Reconnect")
            self.disconnect_btn.config(state="normal")
            how = "uploaded firmware" if data["uploaded"] else "firmware was already running"
            self.log(f"Connected ({how}){' – DEMO, no hardware' if data['demo'] else ''}.")
            if self.current is not None:
                self.worker.cmds.put(("play", self.current))
        elif kind == "connect_failed":
            self.connected = False
            self.connect_btn.config(state="normal", text="Connect")
            self.light_usb.set("bad" if "not found" in data else "ok")
            self.light_fw.set("bad")
            self.light_link.set("off")
            self.log("Connect failed: " + data)
            messagebox.showerror(APP_NAME, "Couldn't connect to the laser box:\n\n" + data)
        elif kind == "disconnected":
            self._set_disconnected("Disconnected.")
        elif kind == "status":
            self.last_reply = time.monotonic()
            self.info_var.set(f"{data['rate']}k pts/s • {data['points']:,} points sent • "
                              f"{data['underruns']} gaps")
        elif kind == "error":
            self._set_disconnected(data)
            self.light_link.set("bad")
            self.light_fw.set("warn")

    def _set_disconnected(self, msg):
        self.connected = False
        self.connect_btn.config(state="normal", text="Connect")
        self.disconnect_btn.config(state="disabled")
        for lt in (self.light_usb, self.light_fw, self.light_link):
            lt.set("off")
        self.info_var.set("")
        self.log(msg)

    def _animate_preview(self):
        delay = 100
        if self.current is not None:
            try:
                pts, self.preview_key, delay = self.current.frame_due(
                    time.monotonic() - self.current_t0, self.preview_key)
                if pts is not None:
                    draw_points(self.preview, pts, PREVIEW, pad=8, width=2)
            except Exception:  # noqa: BLE001
                delay = 100
        self.root.after(delay, self._animate_preview)

    # -- settings file -----------------------------------------------------------
    def _load_settings(self):
        try:
            with open(SETTINGS_FILE) as f:
                self.settings.update({k: v for k, v in json.load(f).items() if k in DEFAULT_SETTINGS})
        except (OSError, ValueError):
            pass

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(self.settings, f, indent=2)
        except OSError:
            pass

    def quit(self):
        self.worker.cmds.put(("quit", None))
        self.worker.join(timeout=2)
        self.root.destroy()


def main():
    if "--install-driver" in sys.argv:          # the .exe re-runs itself elevated for this
        import winusb_install
        sys.argv = [sys.argv[0], "--install"] + [a for a in sys.argv[1:] if a != "--install-driver"]
        winusb_install.main()
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="use a simulated box (no hardware needed)")
    args = ap.parse_args()
    root = tk.Tk()
    App(root, demo=args.demo)
    root.mainloop()


if __name__ == "__main__":
    main()
