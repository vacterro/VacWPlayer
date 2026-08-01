import tkinter as tk
from tkinter import ttk, messagebox

from theme import VintageSunken, VintageButton, VintageLabel, VintageEntry, TOKENS, FONT_SM
from tabs.champ_tab import BindButton

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

        left = tk.Frame(body, bg=TOKENS["background"])
        left.pack(side="left", fill="both", expand=True)
        VintageLabel(left, text="Combos (General mode):").pack(anchor="w")
        tree_holder = VintageSunken(left, bg_color=TOKENS["compareBack"])
        tree_holder.pack(fill="both", expand=True, pady=2)
        self.tree = ttk.Treeview(tree_holder.content,
                                 columns=("trigger", "keys", "ms", "shift"),
                                 show="headings", height=7)
        for col, w in (("trigger", 50), ("keys", 170), ("ms", 36), ("shift", 38)):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        btns = tk.Frame(left, bg=TOKENS["background"])
        btns.pack(fill="x", pady=2)
        VintageButton(btns, text="Add", command=self.add_combo, width=5).pack(side="left", padx=1)
        VintageButton(btns, text="Delete", command=self.delete_combo, width=7).pack(side="left", padx=1)
        VintageButton(btns, text="Clear all", command=self.clear_all, width=9).pack(side="left", padx=1)
        VintageButton(btns, text="Reset defaults", command=self.reset_defaults, width=13).pack(side="left", padx=1)

        edit = tk.Frame(body, bg=TOKENS["background"])
        edit.pack(side="left", fill="y", padx=(6, 0))
        VintageLabel(edit, text="Selected combo:").grid(row=0, column=0, columnspan=3, sticky="w")

        VintageLabel(edit, text="Trigger:", font=FONT_SM).grid(row=1, column=0, sticky="w", pady=1)
        self.var_trigger = tk.StringVar()
        VintageEntry(edit, textvariable=self.var_trigger, width=8).grid(row=1, column=1, sticky="w")
        BindButton(edit, self.var_trigger).grid(row=1, column=2, sticky="w", padx=2)

        VintageLabel(edit, text="Keys:", font=FONT_SM).grid(row=2, column=0, sticky="w", pady=1)
        self.var_keys = tk.StringVar()
        VintageEntry(edit, textvariable=self.var_keys, width=24).grid(
            row=2, column=1, columnspan=2, sticky="w")

        VintageLabel(edit, text="Interval:", font=FONT_SM).grid(row=3, column=0, sticky="w", pady=1)
        self.var_interval = tk.IntVar(value=50)
        VintageEntry(edit, textvariable=self.var_interval, width=6).grid(row=3, column=1, sticky="w")

        self.var_shift = tk.BooleanVar(value=True)
        _check(edit, "Shift-cast q/w/e/r", self.var_shift).grid(
            row=4, column=0, columnspan=2, sticky="w")

        VintageButton(edit, text="Apply", command=self.apply_changes,
                      width=8).grid(row=5, column=0, columnspan=3, sticky="w", pady=3)
        VintageLabel(edit, text="key:ms sets that step's own\ndelay, e.g. q,e:120,{Space}:200",
                     font=FONT_SM, fg=TOKENS["textMuted"], justify="left").grid(
            row=6, column=0, columnspan=3, sticky="w")

        self.refresh_list()

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
                "Clear combos", "Delete all %d custom combos?" % len(self.combos)):
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
            messagebox.showinfo("Apply", "Select a combo first (or Add one).")
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
