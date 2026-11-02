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
import json
import os
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import usb.core

import patterns
from ishow_usb import IShowUSB

APP_NAME = "iShow Laser"
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))
LIBRARY_DIR = os.path.join(BASE_DIR, "laser_files")
SETTINGS_FILE = os.path.join(BASE_DIR, "ishow_app_settings.json")

DEFAULT_SETTINGS = {"rate": 20, "limit": 5.0, "invert_x": False, "invert_y": False,
                    "swap_xy": False, "mono_green": True, "file_fps": 20, "line_step": 3}

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
def draw_points(canvas, points, size, pad=4, width=1):
    canvas.delete("all")
    span = size - 2 * pad
    for x0, y0, x1, y1 in patterns.preview_segments(points):
        canvas.create_line(pad + (x0 + 1) / 2 * span, pad + (1 - y0) / 2 * span,
                           pad + (x1 + 1) / 2 * span, pad + (1 - y1) / 2 * span,
                           fill=BEAM, width=width, capstyle="round")


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

    def __init__(self, master, item, on_click, on_remove=None):
        super().__init__(master, bg=PANEL, highlightthickness=2, highlightbackground=PANEL)
        self.item = item
        self.canvas = tk.Canvas(self, width=self.SIZE, height=self.SIZE, bg="black",
                                highlightthickness=0, cursor="hand2")
        self.canvas.pack(padx=4, pady=(4, 0))
        try:
            draw_points(self.canvas, item.preview_frame(), self.SIZE)
        except Exception:  # noqa: BLE001 - a broken file still gets a tile
            self.canvas.create_text(self.SIZE / 2, self.SIZE / 2, text="?", fill="red")
        self.label = tk.Label(self, text=item.name, bg=PANEL, fg="#d8dde6", wraplength=self.SIZE,
                              font=("Segoe UI", 8), cursor="hand2")
        self.label.pack(padx=4, pady=(2, 4))
        for w in (self, self.canvas, self.label):
            w.bind("<Button-1>", lambda e: on_click(self))
            if on_remove:
                w.bind("<Button-3>", lambda e: self._menu(e, on_remove))

    def _menu(self, event, on_remove):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label=f"Remove “{self.item.name}”", command=lambda: on_remove(self))
        m.tk_popup(event.x_root, event.y_root)

    def select(self, on):
        self.config(highlightbackground=BEAM if on else PANEL)


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
        txt.pack(fill="x", pady=8)
        self.text_box = tk.Text(txt, height=2, width=30, font=("Consolas", 14), bg="black", fg=BEAM,
                                insertbackground=BEAM, wrap="none")
        self.text_box.pack(fill="x")
        self.text_box.insert("1.0", "HELLO")
        self.text_box.bind("<KeyRelease>", self._limit_text)
        ttk.Button(txt, text="Show text on laser", command=self.show_text).pack(fill="x", pady=(6, 0))

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
        tk.Label(head, text="Click a picture to show it on the laser", bg=BG, fg="#d8dde6",
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(head, text="Add laser files (.ild)…", command=self.add_files).pack(side="right")
        self.scroll = ScrollFrame(right)
        self.scroll.pack(fill="both", expand=True, pady=(6, 0))

        items = patterns.builtin_items()
        self.sec_test = self._section("Test patterns")
        self.sec_pics = self._section("Pictures")
        self.sec_files = self._section("My laser files  (right-click a file to remove it)")
        for it in items:
            self._add_tile(self.sec_test if it.kind == "test" else self.sec_pics, it)
        self.empty_files = tk.Label(self.sec_files, text="No laser files yet. Use “Add laser files”.",
                                    bg=BG, fg="#8b93a1", font=("Segoe UI", 9))
        self._load_library_files()

    def _section(self, title):
        tk.Label(self.scroll.inner, text=title, bg=BG, fg="#8b93a1", anchor="w",
                 font=("Segoe UI", 10, "bold")).pack(fill="x", pady=(10, 4))
        frame = tk.Frame(self.scroll.inner, bg=BG)
        frame.pack(fill="x")
        frame.count = 0
        return frame

    def _add_tile(self, section, item, removable=False):
        tile = Tile(section, item, self.play_tile, self.remove_file if removable else None)
        cols = 6
        tile.grid(row=section.count // cols, column=section.count % cols, padx=4, pady=4, sticky="n")
        section.count += 1
        self.tiles.append(tile)
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
            if name.lower().endswith(".ild"):
                try:
                    self._add_file_item(os.path.join(LIBRARY_DIR, name))
                except Exception as e:  # noqa: BLE001
                    self.log(f"Skipped {name}: {e}")
        self._relayout_files()

    def _add_file_item(self, path):
        item = patterns.ilda_item(path)
        item.fps = self.settings["file_fps"]
        self._add_tile(self.sec_files, item, removable=True)

    def add_files(self):
        paths = filedialog.askopenfilenames(title="Add laser files",
                                            filetypes=[("ILDA laser files", "*.ild *.ILD"), ("All files", "*.*")])
        added = 0
        for src in paths:
            try:
                patterns.ilda_item(src)          # validate before copying
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
                                               "Only ILDA (.ild) files are supported.")
        self._relayout_files()
        if added:
            self.log(f"Added {added} laser file(s).")

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
        self.current = item
        self.current_t0 = time.monotonic()
        self.now_var.set(item.name)
        if self.connected:
            self.worker.cmds.put(("play", item))
            self.log(f"Showing: {item.name}")
        else:
            self.log(f"Previewing {item.name}. Connect to show it on the laser.")

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
        self.play(patterns.text_item(lines))

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
        self.settings = s
        for t in self.file_tiles:
            t.item.fps = s["file_fps"]
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
        if self.current is not None:
            try:
                pts = self.current.frame_at(time.monotonic() - self.current_t0)
                draw_points(self.preview, pts, PREVIEW, pad=8, width=2)
            except Exception:  # noqa: BLE001
                pass
        self.root.after(60, self._animate_preview)

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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="use a simulated box (no hardware needed)")
    args = ap.parse_args()
    root = tk.Tk()
    App(root, demo=args.demo)
    root.mainloop()


if __name__ == "__main__":
    main()
