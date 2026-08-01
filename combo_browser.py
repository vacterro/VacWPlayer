import tkinter as tk
import champions
from theme import (VintageSunken, VintageButton, VintageLabel, VintageEntry,
                   TOKENS, FONT_SM)


class ComboBrowser(tk.Toplevel):
    def __init__(self, parent, on_apply=None):
        super().__init__(parent)
        self.on_apply = on_apply
        self.title("Combo Browser")
        self.configure(bg=TOKENS["background"])
        self.resizable(False, False)

        top = tk.Frame(self, bg=TOKENS["background"])
        top.pack(fill="x", padx=4, pady=(4, 1))
        VintageLabel(top, text="Search:", font=FONT_SM).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._filter())
        VintageEntry(top, textvariable=self.search_var, width=20).pack(side="left", padx=2)

        body = tk.Frame(self, bg=TOKENS["background"])
        body.pack(fill="both", expand=True, padx=4, pady=1)

        list_frame = VintageSunken(body, bg_color=TOKENS["compareBack"])
        list_frame.pack(side="left", fill="y")

        self.listbox = tk.Listbox(list_frame.content, width=22, height=20,
                                  bg=TOKENS["compareBack"], fg=TOKENS["textPrimary"],
                                  font=FONT_SM, bd=0, highlightthickness=0,
                                  selectbackground=TOKENS["selection"],
                                  selectforeground=TOKENS["textPrimary"])
        self.listbox.pack(padx=1, pady=1)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        detail = tk.Frame(body, bg=TOKENS["background"])
        detail.pack(side="left", fill="both", expand=True, padx=(4, 0))

        self.detail_text = tk.Text(detail, width=40, height=20,
                                   bg=TOKENS["compareBack"], fg=TOKENS["textPrimary"],
                                   font=("Consolas", 9), bd=0, highlightthickness=0,
                                   wrap="none", state="disabled")
        self.detail_text.pack(fill="both", expand=True)

        btn_row = tk.Frame(self, bg=TOKENS["background"])
        btn_row.pack(fill="x", padx=4, pady=(2, 4))
        VintageButton(btn_row, text="▶ Apply",
                      command=self._apply, width=8).pack(side="left")
        VintageButton(btn_row, text="✕", command=self.destroy,
                      width=2).pack(side="right")

        self.all_entries = []
        self._load_roster()
        self.listbox.selection_set(0)
        self._show_detail(0)

        self.bind("<Escape>", lambda e: self.destroy())

    def _load_roster(self):
        self.all_entries = []
        for name in champions.ROSTER:
            slug = champions.slug(name)
            default = champions.default_for(name)
            sourced = default.get("sourced", False)
            self.all_entries.append((name, slug, default, sourced))
        for entry in self.all_entries:
            self.listbox.insert("end", entry[0])

    def _filter(self):
        q = self.search_var.get().lower()
        self.listbox.delete(0, "end")
        for entry in self.all_entries:
            if q in entry[0].lower():
                self.listbox.insert("end", entry[0])

    def _on_select(self, event):
        sel = self.listbox.curselection()
        if not sel:
            return
        self._show_detail(sel[0])

    def _show_detail(self, idx):
        name = self.listbox.get(idx)
        entry = next((e for e in self.all_entries if e[0] == name), None)
        if not entry:
            return
        _, slug, default, sourced = entry
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", "end")

        self._append("Champion: %s (%s)\n" % (name, slug))
        self._append("Source: %s\n\n" % ("Known guide" if sourced else "Placeholder — edit it"))

        for slot in ("wave", "jungle", "pvp"):
            trigger = default.get("trigger_" + slot, "")
            keys = default.get("keys_" + slot, "")
            interval = default.get("interval", 50)
            self._append("[%s]\n" % slot.upper())
            self._append("  Trigger: %s\n" % (trigger or "(none)"))
            self._append("  Keys:    %s\n" % keys)
            self._append("  Step ms: %d\n\n" % interval)

        self.detail_text.config(state="disabled")

    def _append(self, text):
        self.detail_text.insert("end", text)

    def _apply(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        if self.on_apply:
            self.on_apply(name)
        self.destroy()
