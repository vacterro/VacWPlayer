import tkinter as tk
from tkinter import ttk, messagebox

from theme import VintageSunken, VintageButton, VintageLabel, VintageEntry, TOKENS, FONT_SM
from tabs.champ_tab import BindButton
from locales import Locale

LEGACY_COMBOS = [
    {"trigger": "F13", "keys": "q,e,w,e,e,e,{Space}", "interval": 50, "shift": True},
    {"trigger": "F14", "keys": "w,q,e,f,{Space}", "interval": 50, "shift": True},
    {"trigger": "F15", "keys": "e,e,e,w,q,{Space},e,{Space},q,{Space}", "interval": 50, "shift": True},
]


def _check(parent, text, var):
    return tk.Checkbutton(
        parent, text=text, variable=var, bg=TOKENS["background"],
        fg=TOKENS["textPrimary"], activebackground=TOKENS["background"],
        activeforeground=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"],
        font=FONT_SM, highlightthickness=0, bd=0)


class ComboTab(tk.Frame):
    """General-mode custom combo list."""

    def _auto_save(self, *args):
        try:
            self.event_generate("<<AutoSave>>")
        except tk.TclError:
            pass

    def __init__(self, parent, config):
        super().__init__(parent, bg=TOKENS["background"])
        self.combos = [dict(c) for c in config.get("combos", [])]

        body = tk.Frame(self, bg=TOKENS["background"])
        body.pack(fill="both", expand=True, padx=4, pady=4)

        self._locale_widgets = []
        self._tree_header_keys = (("trigger", "col_trigger"), ("keys", "col_keys"),
                                  ("ms", "col_ms"), ("shift", "col_shift"))

        left = tk.Frame(body, bg=TOKENS["background"])
        left.pack(side="left", fill="both", expand=True)
        self._lbl_title = VintageLabel(left, text=Locale.tr("combos_title"))
        self._lbl_title.pack(anchor="w")
        self._locale_widgets.append(("lbl", self._lbl_title, "combos_title"))
        tree_holder = VintageSunken(left, bg_color=TOKENS["compareBack"])
        tree_holder.pack(fill="both", expand=True, pady=2)
        self.tree = ttk.Treeview(tree_holder.content,
                                 columns=("trigger", "keys", "ms", "shift"),
                                 show="headings", height=7)
        for col, w in (("trigger", 50), ("keys", 170), ("ms", 36), ("shift", 38)):
            self.tree.heading(col, text=Locale.tr(dict(self._tree_header_keys)[col]))
            self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        btns = tk.Frame(left, bg=TOKENS["background"])
        btns.pack(fill="x", pady=2)
        self._btn_add = VintageButton(btns, text=Locale.tr("add"), command=self.add_combo, width=5)
        self._btn_add.pack(side="left", padx=1)
        self._locale_widgets.append(("btn", self._btn_add, "add"))
        self._btn_delete = VintageButton(btns, text=Locale.tr("delete"), command=self.delete_combo, width=7)
        self._btn_delete.pack(side="left", padx=1)
        self._locale_widgets.append(("btn", self._btn_delete, "delete"))
        self._btn_clear = VintageButton(btns, text=Locale.tr("clear_all"), command=self.clear_all, width=9)
        self._btn_clear.pack(side="left", padx=1)
        self._locale_widgets.append(("btn", self._btn_clear, "clear_all"))
        self._btn_reset = VintageButton(btns, text=Locale.tr("reset_defaults"), command=self.reset_defaults, width=13)
        self._btn_reset.pack(side="left", padx=1)
        self._locale_widgets.append(("btn", self._btn_reset, "reset_defaults"))

        edit = tk.Frame(body, bg=TOKENS["background"])
        edit.pack(side="left", fill="y", padx=(6, 0))
        self._lbl_sel = VintageLabel(edit, text=Locale.tr("selected_combo"))
        self._lbl_sel.grid(row=0, column=0, columnspan=3, sticky="w")
        self._locale_widgets.append(("lbl", self._lbl_sel, "selected_combo"))

        self._lbl_trigger = VintageLabel(edit, text=Locale.tr("trigger_lbl"), font=FONT_SM)
        self._lbl_trigger.grid(row=1, column=0, sticky="w", pady=1)
        self._locale_widgets.append(("lbl", self._lbl_trigger, "trigger_lbl"))
        self.var_trigger = tk.StringVar()
        VintageEntry(edit, textvariable=self.var_trigger, width=8).grid(row=1, column=1, sticky="w")
        BindButton(edit, self.var_trigger).grid(row=1, column=2, sticky="w", padx=2)

        self._lbl_keys = VintageLabel(edit, text=Locale.tr("keys_lbl"), font=FONT_SM)
        self._lbl_keys.grid(row=2, column=0, sticky="w", pady=1)
        self._locale_widgets.append(("lbl", self._lbl_keys, "keys_lbl"))
        self.var_keys = tk.StringVar()
        VintageEntry(edit, textvariable=self.var_keys, width=24).grid(
            row=2, column=1, columnspan=2, sticky="w")

        self._lbl_interval = VintageLabel(edit, text=Locale.tr("interval_lbl"), font=FONT_SM)
        self._lbl_interval.grid(row=3, column=0, sticky="w", pady=1)
        self._locale_widgets.append(("lbl", self._lbl_interval, "interval_lbl"))
        self.var_interval = tk.IntVar(value=50)
        VintageEntry(edit, textvariable=self.var_interval, width=6).grid(row=3, column=1, sticky="w")

        self.var_shift = tk.BooleanVar(value=True)
        self._chk_shift = _check(edit, Locale.tr("shift_cast"), self.var_shift)
        self._chk_shift.grid(row=4, column=0, columnspan=2, sticky="w")
        self._locale_widgets.append(("chk", self._chk_shift, "shift_cast"))

        self._btn_apply = VintageButton(edit, text=Locale.tr("apply"), command=self.apply_changes, width=8)
        self._btn_apply.grid(row=5, column=0, columnspan=3, sticky="w", pady=3)
        self._locale_widgets.append(("btn", self._btn_apply, "apply"))
        self._lbl_hint = VintageLabel(edit, text=Locale.tr("combo_hint"),
                     font=FONT_SM, fg=TOKENS["textMuted"], justify="left")
        self._lbl_hint.grid(row=6, column=0, columnspan=3, sticky="w")
        self._locale_widgets.append(("lbl", self._lbl_hint, "combo_hint"))

        self.refresh_list()

    def apply_locale(self):
        for col, key in self._tree_header_keys:
            self.tree.heading(col, text=Locale.tr(key))
        for kind, widget, key in self._locale_widgets:
            if kind == "lbl":
                widget.config(text=Locale.tr(key))
            elif kind == "btn":
                widget.label.config(text=Locale.tr(key))
            elif kind == "chk":
                widget.config(text=Locale.tr(key))

    def refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(self.combos):
            self.tree.insert("", "end", iid=str(i), values=(
                c["trigger"], c["keys"], c["interval"],
                "yes" if c.get("shift", True) else "no"))

    def on_select(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        c = self.combos[int(sel[0])]
        self.var_trigger.set(c["trigger"])
        self.var_keys.set(c["keys"])
        self.var_interval.set(c["interval"])
        self.var_shift.set(c.get("shift", True))

    def add_combo(self):
        self.combos.append({"trigger": "F13", "keys": "q,w,e,{Space}",
                            "interval": 50, "shift": True})
        self.refresh_list()
        self.tree.selection_set(str(len(self.combos) - 1))
        self._auto_save()

    def delete_combo(self):
        sel = self.tree.selection()
        if not sel:
            return
        del self.combos[int(sel[0])]
        self.refresh_list()
        self._auto_save()

    def clear_all(self):
        if self.combos and not messagebox.askyesno(
                Locale.tr("clear_title"),
                Locale.tr("clear_text") % len(self.combos)):
            return
        self.combos = []
        self.refresh_list()
        self._auto_save()

    def reset_defaults(self):
        self.combos = [dict(c) for c in LEGACY_COMBOS]
        self.refresh_list()
        self._auto_save()

    def apply_changes(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(Locale.tr("apply"), Locale.tr("apply_need"))
            return
        idx = int(sel[0])
        try:
            interval = int(self.var_interval.get())
        except (tk.TclError, ValueError):
            interval = 50
        self.combos[idx] = {
            "trigger": self.var_trigger.get().strip(),
            "keys": self.var_keys.get().strip(),
            "interval": interval,
            "shift": self.var_shift.get(),
        }
        self.refresh_list()
        self.tree.selection_set(str(idx))
        self._auto_save()

    def get_data(self):
        return self.combos
