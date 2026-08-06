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
    "mouse_move_instead_hold": False,
    "mouse_toggle_hold": False,
    "release_toggle_on_keys": False,
    "keep_movement_on_death": False,
    "rmb_hold_pvp": True,
    "space_spam": True,
    "space_interval": 128,
    "anti_afk_hotkey": True,
    "anti_afk_interval": 5000,
    "stop_key": "s",
    "manual_aim_block": True,
    "guard_outside_game": True,
    "exit_when_bs_gone": True,
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
        self.var_move_instead_hold = tk.BooleanVar(value=toggles["mouse_move_instead_hold"])
        self.var_move_instead_hold.trace_add("write", self._auto_save)
        self.var_move_instead_hold.trace_add("write", self._exclusive_mouse_modes)
        self.var_toggle_hold = tk.BooleanVar(value=toggles["mouse_toggle_hold"])
        self.var_toggle_hold.trace_add("write", self._auto_save)
        self.var_toggle_hold.trace_add("write", self._exclusive_mouse_modes)
        self.var_toggle_hold.trace_add("write", self._sync_release_on_keys)
        self.var_release_on_keys = tk.BooleanVar(value=toggles["release_toggle_on_keys"])
        self.var_release_on_keys.trace_add("write", self._auto_save)
        self.var_keep_move = tk.BooleanVar(value=toggles["keep_movement_on_death"])
        self.var_keep_move.trace_add("write", self._auto_save)
        self.var_rmb_pvp = tk.BooleanVar(value=toggles["rmb_hold_pvp"])
        self.var_rmb_pvp.trace_add("write", self._auto_save)
        self.var_space = tk.BooleanVar(value=toggles["space_spam"])
        self.var_space.trace_add("write", self._auto_save)
        self.var_afk = tk.BooleanVar(value=toggles["anti_afk_hotkey"])
        self.var_afk.trace_add("write", self._auto_save)
        self.var_manual = tk.BooleanVar(value=toggles["manual_aim_block"])
        self.var_manual.trace_add("write", self._auto_save)
        self.var_guard = tk.BooleanVar(value=toggles["guard_outside_game"])
        self.var_guard.trace_add("write", self._auto_save)
        self.var_exit_bs = tk.BooleanVar(value=toggles["exit_when_bs_gone"])
        self.var_exit_bs.trace_add("write", self._auto_save)
        self._chk_remap = _check(tog, Locale.tr("toggle_mouse_remap"), self.var_remap)
        self._chk_remap.grid(row=0, column=0, sticky="w")
        self._chk_move_instead_hold = _check(tog, Locale.tr("toggle_mouse_move_instead_hold"), self.var_move_instead_hold)
        self._chk_move_instead_hold.grid(row=0, column=1, sticky="w", padx=(6, 0))
        self._chk_toggle_hold = _check(tog, Locale.tr("toggle_mouse_toggle_hold"), self.var_toggle_hold)
        self._chk_toggle_hold.grid(row=3, column=0, sticky="w")
        self._chk_release_on_keys = _check(tog, Locale.tr("toggle_release_on_keys"), self.var_release_on_keys)
        self._chk_release_on_keys.grid(row=3, column=1, sticky="w", padx=(6, 0))
        self._sync_release_on_keys()
        self._chk_rmb_pvp = _check(tog, Locale.tr("toggle_rmb_pvp"), self.var_rmb_pvp)
        self._chk_rmb_pvp.grid(row=4, column=0, columnspan=2, sticky="w")
        self._chk_keep_move = _check(tog, Locale.tr("toggle_keep_move_death"), self.var_keep_move)
        self._chk_keep_move.grid(row=5, column=0, columnspan=2, sticky="w")
        self._chk_space = _check(tog, Locale.tr("toggle_space_spam"), self.var_space)
        self._chk_space.grid(row=1, column=0, sticky="w")
        self._chk_afk = _check(tog, Locale.tr("toggle_anti_afk"), self.var_afk)
        self._chk_afk.grid(row=1, column=1, sticky="w", padx=(6, 0))
        self._chk_manual = _check(tog, Locale.tr("toggle_manual_aim"), self.var_manual)
        self._chk_manual.grid(row=2, column=0, sticky="w")
        self._chk_guard = _check(tog, Locale.tr("toggle_guard_outside"), self.var_guard)
        self._chk_guard.grid(row=2, column=1, sticky="w", padx=(6, 0))
        self._chk_exit_bs = _check(tog, Locale.tr("toggle_exit_bs_gone"), self.var_exit_bs)
        self._chk_exit_bs.grid(row=6, column=0, columnspan=2, sticky="w")
        for w, k in ((self._chk_remap, "toggle_mouse_remap"),
                     (self._chk_move_instead_hold, "toggle_mouse_move_instead_hold"),
                     (self._chk_toggle_hold, "toggle_mouse_toggle_hold"),
                     (self._chk_release_on_keys, "toggle_release_on_keys"),
                     (self._chk_keep_move, "toggle_keep_move_death"),
                     (self._chk_rmb_pvp, "toggle_rmb_pvp"),
                     (self._chk_space, "toggle_space_spam"),
                     (self._chk_afk, "toggle_anti_afk"),
                     (self._chk_manual, "toggle_manual_aim"),
                     (self._chk_guard, "toggle_guard_outside"),
                     (self._chk_exit_bs, "toggle_exit_bs_gone")):
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

    def _sync_release_on_keys(self, *args):
        """'Keys release hold' and 'Keep movement after death' only make sense
        while LMB Toggles is on.

        Grey them out (and force them off) when toggle-hold is disabled, so the
        config can never carry a release/keep flag that does nothing.
        """
        chk = getattr(self, "_chk_release_on_keys", None)
        if chk is None:
            return
        keep = getattr(self, "_chk_keep_move", None)
        if self.var_toggle_hold.get():
            chk.config(state="normal")
            if keep:
                keep.config(state="normal")
        else:
            chk.config(state="disabled")
            self.var_release_on_keys.set(False)
            if keep:
                keep.config(state="disabled")
                self.var_keep_move.set(False)

    def _exclusive_mouse_modes(self, *args):
        """Click-to-move and toggle-hold are alternative LMB behaviours.

        Whichever checkbox the user just ticked wins: the other one is
        turned off, so the two can never stay in conflict.
        """
        if getattr(self, "_syncing_mouse", False):
            return
        changed = args[0] if args else ""
        self._syncing_mouse = True
        try:
            if changed == self.var_toggle_hold._name and self.var_toggle_hold.get():
                self.var_move_instead_hold.set(False)
            elif changed == self.var_move_instead_hold._name and self.var_move_instead_hold.get():
                self.var_toggle_hold.set(False)
        finally:
            self._syncing_mouse = False

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
            "mouse_move_instead_hold": self.var_move_instead_hold.get(),
            "mouse_toggle_hold": self.var_toggle_hold.get(),
            "release_toggle_on_keys": self.var_release_on_keys.get(),
            "keep_movement_on_death": self.var_keep_move.get(),
            "rmb_hold_pvp": self.var_rmb_pvp.get(),
            "space_spam": self.var_space.get(),
            "space_interval": space_ms,
            "anti_afk_hotkey": self.var_afk.get(),
            "anti_afk_interval": afk_ms,
            "stop_key": self.var_stop.get().strip(),
            "manual_aim_block": self.var_manual.get(),
            "guard_outside_game": self.var_guard.get(),
            "exit_when_bs_gone": self.var_exit_bs.get(),
            "target_exe": self.var_exe.get().strip() or "HD-Player.exe",
        }

