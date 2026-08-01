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
        _check(tog, "Mouse remap (LMB=move hold, RMB=tap)", self.var_remap).grid(
            row=0, column=0, sticky="w")
        _check(tog, "Space spam while held", self.var_space).grid(
            row=0, column=1, sticky="w", padx=(6, 0))
        _check(tog, "Anti-AFK (Ctrl+G toggles in game)", self.var_afk).grid(
            row=1, column=0, sticky="w")
        _check(tog, "Manual q/w/e/r/d/f pauses combos", self.var_manual).grid(
            row=1, column=1, sticky="w", padx=(6, 0))

        row2 = tk.Frame(self, bg=TOKENS["background"])
        row2.pack(fill="x", padx=4, pady=1)
        VintageLabel(row2, text="Stop:", font=FONT_SM).pack(side="left")
        self.var_stop = tk.StringVar(value=toggles["stop_key"])
        self.var_stop.trace_add("write", self._auto_save)
        VintageEntry(row2, textvariable=self.var_stop, width=3).pack(side="left", padx=1)
        VintageLabel(row2, text="Spc ms:", font=FONT_SM).pack(side="left", padx=(6, 0))
        self.var_space_ms = tk.IntVar(value=int(toggles["space_interval"]))
        self.var_space_ms.trace_add("write", self._auto_save)
        VintageEntry(row2, textvariable=self.var_space_ms, width=5).pack(side="left", padx=2)
        VintageLabel(row2, text="AFK ms:", font=FONT_SM).pack(side="left", padx=(6, 0))
        self.var_afk_ms = tk.IntVar(value=int(toggles["anti_afk_interval"]))
        self.var_afk_ms.trace_add("write", self._auto_save)
        VintageEntry(row2, textvariable=self.var_afk_ms, width=6).pack(side="left", padx=2)
        VintageLabel(row2, text="Exe:", font=FONT_SM).pack(side="left", padx=(6, 0))
        self.var_exe = tk.StringVar(value=toggles["target_exe"])
        self.var_exe.trace_add("write", self._auto_save)
        self.exe_combo = ttk.Combobox(row2, textvariable=self.var_exe,
                                       values=EMULATOR_EXES, width=14,
                                       font=FONT_SM)
        self.exe_combo.pack(side="left", padx=2)
        self.exe_detect = VintageButton(row2, text="Detect", command=self._detect_exe, width=7)
        self.exe_detect.pack(side="left", padx=1)

        sep = tk.Frame(self, bg=TOKENS["borderMuted"], height=1)
        sep.pack(fill="x", padx=4, pady=4)

    def _detect_exe(self):
        found = detect_running_emulators()
        if not found:
            messagebox.showinfo("Detect",
                "No known emulators running.\n"
                "Start your emulator and try again.")
            return
        if len(found) == 1:
            self.var_exe.set(found[0])
        else:
            self.var_exe.set(found[0])
            messagebox.showinfo("Detect",
                "Running: " + ", ".join(found) + "\n"
                "Set to \"" + found[0] + "\".\n"
                "Pick another from the list if needed.")

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
