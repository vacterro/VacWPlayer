import tkinter as tk

from theme import VintageButton, VintageLabel, VintageEntry, TOKENS, FONT_SM
from tabs.champ_tab import BindButton
from locales import Locale

SLOT_KEYS = ["top", "mid", "bot", "top_deep", "mid_deep", "bot_deep",
             "base", "enemy_base"]

AFKFARM_DEFAULTS = {
    "enabled": True,
    "toggle_key": "F23",
    "move_duration": 5000,
    "follow_cursor": True,
    "combo_keys": "q,w,e,{Space}",
    "combo_interval": 128,
    "slots": ["top", "mid", "bot", "top_deep", "mid_deep", "bot_deep",
              "base", "enemy_base"],
}


class AFKFarmTab(tk.Frame):
    def _auto_save(self, *args):
        try:
            self.event_generate("<<AutoSave>>")
        except tk.TclError:
            pass

    def __init__(self, parent, saved=None):
        super().__init__(parent, bg=TOKENS["background"])

        cfg = dict(AFKFARM_DEFAULTS)
        if saved and isinstance(saved, dict):
            for k in cfg:
                if k in saved:
                    cfg[k] = saved[k]

        self._locale_widgets = []

        head = tk.Frame(self, bg=TOKENS["background"])
        head.pack(fill="x", padx=4, pady=(4, 1))

        self.var_enabled = tk.BooleanVar(value=cfg["enabled"])
        self.var_enabled.trace_add("write", self._auto_save)
        self._chk_enable = tk.Checkbutton(head, variable=self.var_enabled,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"],
                       selectcolor=TOKENS["compareBack"],
                       activebackground=TOKENS["background"],
                       activeforeground=TOKENS["textPrimary"],
                       font=FONT_SM, highlightthickness=0, bd=0)
        self._chk_enable.pack(anchor="w")
        self._locale_widgets.append(("chk", self._chk_enable, "enable"))

        self._desc = VintageLabel(head, text="",
                     font=FONT_SM, fg=TOKENS["textMuted"])
        self._desc.pack(anchor="w")
        self._locale_widgets.append(("lbl", self._desc, "farm_desc"))

        form = tk.Frame(self, bg=TOKENS["background"])
        form.pack(fill="x", padx=4, pady=2)

        r = 0
        self._lbl_toggle = VintageLabel(form, text="")
        self._lbl_toggle.grid(row=r, column=0, sticky="w", pady=1)
        self._locale_widgets.append(("lbl", self._lbl_toggle, "toggle_key"))
        self.var_toggle = tk.StringVar(value=cfg["toggle_key"])
        self.var_toggle.trace_add("write", self._auto_save)
        VintageEntry(form, textvariable=self.var_toggle, width=7).grid(row=r, column=1, sticky="w")
        BindButton(form, self.var_toggle).grid(row=r, column=2, sticky="w", padx=1)

        r += 1
        self._lbl_duration = VintageLabel(form, text="")
        self._lbl_duration.grid(row=r, column=0, sticky="w", pady=1)
        self._locale_widgets.append(("lbl", self._lbl_duration, "move_duration"))
        self.var_duration = tk.IntVar(value=int(cfg["move_duration"]))
        self.var_duration.trace_add("write", self._auto_save)
        VintageEntry(form, textvariable=self.var_duration, width=6).grid(row=r, column=1, sticky="w")

        r += 1
        self.var_follow = tk.BooleanVar(value=bool(cfg["follow_cursor"]))
        self.var_follow.trace_add("write", self._auto_save)
        self._chk_follow = tk.Checkbutton(form, variable=self.var_follow,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"],
                       selectcolor=TOKENS["compareBack"],
                       activebackground=TOKENS["background"],
                       activeforeground=TOKENS["textPrimary"],
                       font=FONT_SM, highlightthickness=0, bd=0)
        self._chk_follow.grid(row=r, column=0, columnspan=2, sticky="w", pady=1)
        self._locale_widgets.append(("chk", self._chk_follow, "follow_cursor"))

        r += 1
        self._lbl_keys = VintageLabel(form, text="")
        self._lbl_keys.grid(row=r, column=0, sticky="w", pady=1)
        self._locale_widgets.append(("lbl", self._lbl_keys, "combo_keys"))
        self.var_keys = tk.StringVar(value=cfg["combo_keys"])
        self.var_keys.trace_add("write", self._auto_save)
        VintageEntry(form, textvariable=self.var_keys, width=22).grid(row=r, column=1, columnspan=2, sticky="w")

        r += 1
        self._lbl_combo_ms = VintageLabel(form, text="")
        self._lbl_combo_ms.grid(row=r, column=0, sticky="w", pady=1)
        self._locale_widgets.append(("lbl", self._lbl_combo_ms, "combo_step_ms"))
        self.var_combo_ms = tk.IntVar(value=int(cfg["combo_interval"]))
        self.var_combo_ms.trace_add("write", self._auto_save)
        VintageEntry(form, textvariable=self.var_combo_ms, width=6).grid(row=r, column=1, sticky="w")

        r += 1
        sep = tk.Frame(form, bg=TOKENS["borderMuted"], height=1)
        sep.grid(row=r, column=0, columnspan=4, sticky="ew", pady=2)

        r += 1
        self._lbl_slots = VintageLabel(form, text="")
        self._lbl_slots.grid(row=r, column=0, columnspan=4, sticky="w", pady=(0, 2))
        self._locale_widgets.append(("lbl", self._lbl_slots, "cycle_slots"))

        r += 1
        self._slot_chks = []
        self.slot_vars = {}
        for i, key in enumerate(SLOT_KEYS):
            col_offset = (i // 3) * 2
            row_offset = i % 3
            sv = tk.BooleanVar(value=key in cfg.get("slots", SLOT_KEYS))
            sv.trace_add("write", self._auto_save)
            self.slot_vars[key] = sv
            chk = tk.Checkbutton(form, variable=sv,
                           bg=TOKENS["background"], fg=TOKENS["textPrimary"],
                           selectcolor=TOKENS["compareBack"],
                           activebackground=TOKENS["background"],
                           activeforeground=TOKENS["textPrimary"],
                           font=FONT_SM, highlightthickness=0, bd=0)
            chk.grid(row=r + row_offset, column=col_offset,
                     columnspan=2,
                     sticky="w", padx=(6 if col_offset else 0, 0))
            self._slot_chks.append((chk, key))

        btn_frame = tk.Frame(self, bg=TOKENS["background"])
        btn_frame.pack(fill="x", padx=8, pady=4)
        
        self._btn_reset = VintageButton(btn_frame, text="Reset defaults",
                      command=self.reset_defaults, width=13)
        self._btn_reset.pack(side="left")
        self._locale_widgets.append(("btn", self._btn_reset, "reset_defaults"))

        self._btn_apply = VintageButton(btn_frame, text="Apply to Engine",
                      command=self._trigger_apply, width=15)
        self._btn_apply.pack(side="right")
        self._locale_widgets.append(("btn", self._btn_apply, "apply_start"))

        self.apply_locale()

    def _trigger_apply(self):
        try:
            self.event_generate("<<ApplyStart>>")
        except tk.TclError:
            pass

    def apply_locale(self):
        for kind, widget, key in self._locale_widgets:
            if kind == "lbl":
                widget.config(text=Locale.tr(key))
            elif kind == "btn":
                widget.label.config(text=Locale.tr(key))
            elif kind == "chk":
                widget.config(text=Locale.tr(key))
        for chk, key in self._slot_chks:
            loc_key = "slots." + key
            chk.config(text=Locale.tr(loc_key, fallback=key.replace("_", " ").title()))

    def reset_defaults(self):
        self.var_enabled.set(AFKFARM_DEFAULTS["enabled"])
        self.var_toggle.set(AFKFARM_DEFAULTS["toggle_key"])
        self.var_duration.set(AFKFARM_DEFAULTS["move_duration"])
        self.var_follow.set(AFKFARM_DEFAULTS["follow_cursor"])
        self.var_keys.set(AFKFARM_DEFAULTS["combo_keys"])
        self.var_combo_ms.set(AFKFARM_DEFAULTS["combo_interval"])
        for key, sv in self.slot_vars.items():
            sv.set(key in AFKFARM_DEFAULTS.get("slots", []))
        self._auto_save()

    def get_data(self):
        try:
            duration = int(self.var_duration.get())
        except (tk.TclError, ValueError):
            duration = AFKFARM_DEFAULTS["move_duration"]
        try:
            combo_ms = int(self.var_combo_ms.get())
        except (tk.TclError, ValueError):
            combo_ms = AFKFARM_DEFAULTS["combo_interval"]
        slots = [k for k, sv in self.slot_vars.items() if sv.get()]
        return {
            "enabled": bool(self.var_enabled.get()),
            "toggle_key": self.var_toggle.get().strip(),
            "move_duration": max(500, duration),
            "follow_cursor": bool(self.var_follow.get()),
            "combo_keys": self.var_keys.get().strip(),
            "combo_interval": max(15, combo_ms),
            "slots": slots,
        }
