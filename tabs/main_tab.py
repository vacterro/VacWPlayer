import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

from theme import (VintageButton, VintageLabel, VintageEntry,
                   TOKENS, FONT_SM)
from locales import Locale

EMULATOR_EXES = [
    "HD-Player.exe",
    "BlueStacks.exe",
    "ldplayer.exe",
    "LdVBoxHeadless.exe",
    "MEmu.exe",
    "Nox.exe",
    "MuMuPlayer.exe",
    "dnplayer.exe",
]

def detect_running_emulators():
    found = []
    for exe in EMULATOR_EXES:
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq " + exe, "/NH"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                text=True)
            if exe.lower() in out.lower():
                found.append(exe)
        except subprocess.CalledProcessError:
            pass
    return found

TOGGLE_DEFAULTS = {
    "mouse_remap": True,
    "space_spam": True,
    "space_interval": 128,
    "anti_afk_hotkey": True,
    "anti_afk_interval": 5000,
    "stop_key": "s",
    "manual_aim_block": True,
    "target_exe": "HD-Player.exe",
}


def _check(parent, text, var):
    return tk.Checkbutton(
        parent, text=text, variable=var, bg=TOKENS["background"],
        fg=TOKENS["textPrimary"], activebackground=TOKENS["background"],
        activeforeground=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"],
        font=FONT_SM, highlightthickness=0, bd=0)


class MainTab(tk.Frame):
    """Global input toggles + target exe + auto-accept."""

    def _auto_save(self, *args):
        try:
            self.event_generate("<<AutoSave>>")
        except tk.TclError:
            pass

    def __init__(self, parent, config):
        super().__init__(parent, bg=TOKENS["background"])
        toggles = dict(TOGGLE_DEFAULTS)
        toggles.update(config.get("toggles", {}))

        self._locale_widgets = []

        tog = tk.Frame(self, bg=TOKENS["background"])
        tog.pack(fill="x", padx=4, pady=(4, 2))

        self.var_remap = tk.BooleanVar(value=toggles["mouse_remap"])
        self.var_remap.trace_add("write", self._auto_save)
        self.var_space = tk.BooleanVar(value=toggles["space_spam"])
        self.var_space.trace_add("write", self._auto_save)
        self.var_afk = tk.BooleanVar(value=toggles["anti_afk_hotkey"])
        self.var_afk.trace_add("write", self._auto_save)
        self.var_manual = tk.BooleanVar(value=toggles["manual_aim_block"])
        self.var_manual.trace_add("write", self._auto_save)
        self._chk_remap = _check(tog, Locale.tr("toggle_mouse_remap"), self.var_remap)
        self._chk_remap.grid(row=0, column=0, sticky="w")
        self._chk_space = _check(tog, Locale.tr("toggle_space_spam"), self.var_space)
        self._chk_space.grid(row=0, column=1, sticky="w", padx=(6, 0))
        self._chk_afk = _check(tog, Locale.tr("toggle_anti_afk"), self.var_afk)
        self._chk_afk.grid(row=1, column=0, sticky="w")
        self._chk_manual = _check(tog, Locale.tr("toggle_manual_aim"), self.var_manual)
        self._chk_manual.grid(row=1, column=1, sticky="w", padx=(6, 0))
        for w, k in ((self._chk_remap, "toggle_mouse_remap"),
                     (self._chk_space, "toggle_space_spam"),
                     (self._chk_afk, "toggle_anti_afk"),
                     (self._chk_manual, "toggle_manual_aim")):
            self._locale_widgets.append(("chk", w, k))

        row2 = tk.Frame(self, bg=TOKENS["background"])
        row2.pack(fill="x", padx=4, pady=1)
        self._lbl_stop = VintageLabel(row2, text=Locale.tr("stop_lbl"), font=FONT_SM)
        self._lbl_stop.pack(side="left")
        self._locale_widgets.append(("lbl", self._lbl_stop, "stop_lbl"))
        self.var_stop = tk.StringVar(value=toggles["stop_key"])
        self.var_stop.trace_add("write", self._auto_save)
        VintageEntry(row2, textvariable=self.var_stop, width=3).pack(side="left", padx=1)
        self._lbl_spc = VintageLabel(row2, text=Locale.tr("spc_ms_lbl"), font=FONT_SM)
        self._lbl_spc.pack(side="left", padx=(6, 0))
        self._locale_widgets.append(("lbl", self._lbl_spc, "spc_ms_lbl"))
        self.var_space_ms = tk.IntVar(value=int(toggles["space_interval"]))
        self.var_space_ms.trace_add("write", self._auto_save)
        VintageEntry(row2, textvariable=self.var_space_ms, width=5).pack(side="left", padx=2)
        self._lbl_afk = VintageLabel(row2, text=Locale.tr("afk_ms_lbl"), font=FONT_SM)
        self._lbl_afk.pack(side="left", padx=(6, 0))
        self._locale_widgets.append(("lbl", self._lbl_afk, "afk_ms_lbl"))
        self.var_afk_ms = tk.IntVar(value=int(toggles["anti_afk_interval"]))
        self.var_afk_ms.trace_add("write", self._auto_save)
        VintageEntry(row2, textvariable=self.var_afk_ms, width=6).pack(side="left", padx=2)
        self._lbl_exe = VintageLabel(row2, text=Locale.tr("exe_lbl"), font=FONT_SM)
        self._lbl_exe.pack(side="left", padx=(6, 0))
        self._locale_widgets.append(("lbl", self._lbl_exe, "exe_lbl"))
        self.var_exe = tk.StringVar(value=toggles["target_exe"])
        self.var_exe.trace_add("write", self._auto_save)
        self.exe_combo = ttk.Combobox(row2, textvariable=self.var_exe,
                                       values=EMULATOR_EXES, width=14,
                                       font=FONT_SM)
        self.exe_combo.pack(side="left", padx=2)
        self.exe_detect = VintageButton(row2, text=Locale.tr("detect"), command=self._detect_exe, width=7)
        self.exe_detect.pack(side="left", padx=1)
        self._locale_widgets.append(("btn", self.exe_detect, "detect"))

        sep = tk.Frame(self, bg=TOKENS["borderMuted"], height=1)
        sep.pack(fill="x", padx=4, pady=4)

    def apply_locale(self):
        for kind, widget, key in self._locale_widgets:
            if kind == "lbl":
                widget.config(text=Locale.tr(key))
            elif kind == "btn":
                widget.label.config(text=Locale.tr(key))
            elif kind == "chk":
                widget.config(text=Locale.tr(key))

    def _detect_exe(self):
        found = detect_running_emulators()
        if not found:
            messagebox.showinfo(Locale.tr("detect_title"), Locale.tr("detect_none"))
            return
        if len(found) == 1:
            self.var_exe.set(found[0])
        else:
            self.var_exe.set(found[0])
            messagebox.showinfo(Locale.tr("detect_title"),
                Locale.tr("detect_running") % (", ".join(found), found[0]))

    def get_data(self):
        return []  # no combos here anymore

    def get_toggles(self):
        try:
            space_ms = int(self.var_space_ms.get())
        except (tk.TclError, ValueError):
            space_ms = TOGGLE_DEFAULTS["space_interval"]
        try:
            afk_ms = int(self.var_afk_ms.get())
        except (tk.TclError, ValueError):
            afk_ms = TOGGLE_DEFAULTS["anti_afk_interval"]
        return {
            "mouse_remap": self.var_remap.get(),
            "space_spam": self.var_space.get(),
            "space_interval": space_ms,
            "anti_afk_hotkey": self.var_afk.get(),
            "anti_afk_interval": afk_ms,
            "stop_key": self.var_stop.get().strip(),
            "manual_aim_block": self.var_manual.get(),
            "target_exe": self.var_exe.get().strip() or "HD-Player.exe",
        }

    def get_autoaccept(self):
        return {"enabled": False}
