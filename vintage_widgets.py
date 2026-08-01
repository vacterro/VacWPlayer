import tkinter as tk
from tkinter import messagebox
import threading
import time

import win32api
import win32con
import win32gui

from theme import VintageButton, VintageEntry, VintageLabel, TOKENS
from locales import Locale

def capture_preview_bytes(region=None):
    import cv2
    import capture
    hwnd = capture.find_window()
    if capture.is_minimized(hwnd):
        return None
    img = capture.grab(hwnd)
    if region:
        x0, y0, x1, y1 = region
        x0, y0 = max(0, x0), max(0, y0)
        x1 = min(img.shape[1], x1)
        y1 = min(img.shape[0], y1)
        img = img[y0:y1, x0:x1]
        if img.size == 0:
            return None
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

    def apply_locale(self):
        if self.label_key:
            self.label.config(text=Locale.tr(self.label_key))
        self.pick_btn.label.config(text=Locale.tr("pick_btn"))

    def get(self):
        return self.title_var.get()

    def _start_pick(self):
        self.pick_btn.label.config(text=Locale.tr("pick_prompt"))
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        title = pick_window_title_blocking()
        self.after(0, lambda: self._finish(title))

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
