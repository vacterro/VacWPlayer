import tkinter as tk
from tkinter import messagebox
import threading
import time

import win32api
import win32con
import win32gui

from theme import VintageButton, VintageEntry, VintageLabel, TOKENS, FONT_SM
from locales import Locale


def grid_row(parent, row, *fields, pad=(4, 1), pady=0):
    """Lay out label+entry pairs on one grid row; returns locale-widget tuples."""
    col = 0
    created = []
    for key, var, width in fields:
        lbl = VintageLabel(parent, text=Locale.tr(key), font=FONT_SM)
        lbl.grid(row=row, column=col, sticky="w", padx=(0 if col == 0 else pad[0], pad[1]), pady=pady)
        VintageEntry(parent, textvariable=var, width=width).grid(
            row=row, column=col + 1, sticky="w", pady=pady)
        created.append(("lbl", lbl, key))
        col += 2
    return created

def capture_preview_bytes(region=None):
    import cv2
    import capture
    hwnd = capture.find_window()
    if capture.is_minimized(hwnd):
        return None
    if region:
        # PERF-004: never full-frame grab for a region. Clamp to CURRENT client
        # dimensions first (no need to render the whole surface), then foreground
        # -> cheap screen-region BitBlt; anything else -> occlusion-safe
        # PrintWindow crop (crops BEFORE the BGR copy). Full-window grab is kept
        # only for the region-less preview.
        x0, y0, x1, y1 = region
        x0, y0 = max(0, x0), max(0, y0)
        cw, ch = capture.get_client_size(hwnd)
        x1 = min(cw, x1)
        y1 = min(ch, y1)
        if x1 <= x0 or y1 <= y0:
            return None
        if capture.is_foreground(hwnd):
            img = capture.grab_region(hwnd, (x0, y0, x1, y1))
        else:
            img = capture.grab_client_region(hwnd, (x0, y0, x1, y1))
        if img.size == 0:
            return None
    else:
        img = capture.grab(hwnd)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        return None
    return buf.tobytes()

def show_image_popup(parent, title, data=None, file=None):
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=TOKENS["background"])
    img = tk.PhotoImage(data=data) if data is not None else tk.PhotoImage(file=file)
    w = img.width()
    if w > 0:
        zoom = max(1, min(6, 320 // w))
        if zoom > 1:
            img = img.zoom(zoom, zoom)
    label = tk.Label(win, image=img, bg=TOKENS["background"])
    label.image = img
    label.pack(padx=8, pady=8)
    win.bind("<Escape>", lambda e: win.destroy())
    win.resizable(False, False)
    win.focus_set()

def pick_window_title_blocking(timeout_sec=15):
    while win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000:
        time.sleep(0.02)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000:
            pt = win32gui.GetCursorPos()
            hwnd = win32gui.WindowFromPoint(pt)
            if not hwnd:
                return None
            root_hwnd = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
            title = win32gui.GetWindowText(root_hwnd or hwnd)
            while win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000:
                time.sleep(0.02)
            return title or None
        time.sleep(0.02)
    return None

def _await_click_edge(get_state, cancel, deadline, get_pos=None, poll=0.02, stale=None):
    """Wait for a fresh left-button PRESS edge, ignoring the click that may have
    launched the picker (CORE-010). Returns the cursor position at the edge, or
    None on cancel / timeout / stale.

    The Pick button is itself clicked with the LEFT mouse button, and that press
    is still physically held for a few ms when the worker thread starts. Sampling
    the button's CURRENT state would capture that launching click (over the
    picker UI, not a target window). So a press is only accepted once the button
    has been observed RELEASED at least once - i.e. a deliberate, later click on
    a real window.

    `stale()` - if provided and returns True, the wait is abandoned immediately
    (T-W2-PERF-006): a newer pick was started, so this worker must not outlive
    its generation.

    get_state() -> bool: True while the left button is down.
    get_pos()  -> (x, y): cursor position at the edge (defaults to
    win32gui.GetCursorPos)."""
    if get_pos is None:
        get_pos = win32gui.GetCursorPos
    released_seen = False
    prev_down = False
    while time.time() < deadline:
        if cancel.is_set():
            return None
        if stale is not None and stale():
            return None
        down = False
        try:
            down = bool(get_state())
        except Exception:
            pass
        if not down:
            released_seen = True
        if released_seen and not prev_down and down:
            try:
                return get_pos()
            except Exception:
                return None
        prev_down = down
        time.sleep(poll)
    return None


class VintageWindowPicker(tk.Frame):
    def __init__(self, parent, label, initial_title, label_key=None):
        super().__init__(parent, bg=TOKENS["background"])
        self.label_key = label_key
        self.label = VintageLabel(self, text=label, width=14)
        self.label.pack(side="left")
        self.title_var = tk.StringVar(value=initial_title or "")
        VintageEntry(self, textvariable=self.title_var, width=22).pack(side="left", padx=2)
        self.pick_btn = VintageButton(self, text=Locale.tr("pick_btn"), command=self._start_pick, width=10)
        self.pick_btn.pack(side="left", padx=2)
        # W2-012: generation token + cancel event for stale workers.
        self._gen = 0
        self._cancel = threading.Event()
        # W2-012: cancel in-flight workers on destroy.
        self.bind("<Destroy>", self._on_destroy)

    def apply_locale(self):
        if self.label_key:
            self.label.config(text=Locale.tr(self.label_key))
        self.pick_btn.label.config(text=Locale.tr("pick_btn"))

    def get(self):
        return self.title_var.get()

    def _on_destroy(self, event=None):
        """W2-012: signal all in-flight workers to stop; they must not
        call after() on a destroyed widget."""
        self._cancel.set()
        self._gen = -1  # invalidate any queued callbacks

    def _start_pick(self):
        # W2-012: bump generation and reset cancel so any in-flight worker
        # from a previous click sees its token expired and skips writing.
        self._cancel.clear()
        self._gen += 1
        gen = self._gen
        self.pick_btn.label.config(text=Locale.tr("pick_prompt"))
        threading.Thread(target=self._worker, args=(gen,), daemon=True).start()

    def _worker(self, gen):
        # W2-012: long-blocking call with periodic cancel check.
        # CORE-010: ignore the Pick-button press that launched us - wait for a
        # fresh click edge on a target window instead of grabbing the launcher.
        deadline = time.time() + 15.0

        def _get_state():
            return bool(win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000)

        # T-W2-PERF-006: a newer pick (or destroy) must invalidate THIS worker's
        # long blocking wait instantly, not just the final _apply write.
        def _stale():
            return self._gen != gen or self._cancel.is_set()

        pt = _await_click_edge(_get_state, self._cancel, deadline, stale=_stale)
        if self._gen != gen or self._cancel.is_set():
            return
        title = None
        if pt is not None:
            try:
                hwnd = win32gui.WindowFromPoint(pt)
                if hwnd:
                    root_hwnd = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
                    title = win32gui.GetWindowText(root_hwnd or hwnd) or None
            except Exception:
                pass
        # W2-012: recheck generation on the Tk thread, not only before scheduling.
        def _apply():
            if self._gen == gen and not self._cancel.is_set():
                self._finish(title)
        try:
            self.after(0, _apply)
        except tk.TclError:
            pass  # widget destroyed before we could schedule

    def _finish(self, title):
        self.pick_btn.label.config(text=Locale.tr("pick_btn_2"))
        if title:
            self.title_var.set(title)
        else:
            messagebox.showinfo(Locale.tr("pick_title"), Locale.tr("pick_none"))

class VintageRegionEditor(tk.Frame):
    # label_width/entry_width are tunable: the Auto Continue tab nests this in
    # a narrow detail panel where the defaults would push Preview off-window.
    def __init__(self, parent, label, initial, label_width=16, entry_width=5):
        super().__init__(parent, bg=TOKENS["background"])
        initial = initial or [0, 0, 0, 0]
        self.vars = [tk.IntVar(value=v) for v in initial]
        VintageLabel(self, text=label, width=label_width).pack(side="left")
        for v in self.vars:
            VintageEntry(self, textvariable=v, width=entry_width).pack(side="left", padx=1)
        VintageButton(self, text=Locale.tr("preview"), command=self._preview, width=8).pack(side="left", padx=4)

    def get(self):
        return [v.get() for v in self.vars]

    def _preview(self):
        data = capture_preview_bytes(self.get())
        if data is None:
            messagebox.showwarning(Locale.tr("preview"), Locale.tr("preview_warn"))
            return
        show_image_popup(self, Locale.tr("region_preview"), data=data)
