import tkinter as tk

import champions
from theme import VintageButton, VintageLabel, VintageEntry, VintageSunken, TOKENS, FONT_MAIN, FONT_SM


class ChampionPicker(tk.Toplevel):
    """Modal list of the whole roster with a type-to-filter box.

    on_pick(name) fires once; champions already added are hidden so the same
    champion can't get two tabs.
    """

    def __init__(self, parent, on_pick, already=()):
        super().__init__(parent)
        self.title("Add champion")
        self.configure(bg=TOKENS["background"])
        self.resizable(False, False)
        self.on_pick = on_pick
        self.already = {champions.slug(a) for a in already}
        self.pool = [n for n in champions.ROSTER
                     if champions.slug(n) not in self.already]

        VintageLabel(self, text="Search:", font=FONT_SM).pack(anchor="w", padx=8, pady=(8, 0))
        self.var_search = tk.StringVar()
        entry = VintageEntry(self, textvariable=self.var_search, width=30)
        entry.pack(anchor="w", padx=8, pady=2)
        self.var_search.trace_add("write", lambda *_: self._refresh())

        holder = VintageSunken(self, bg_color=TOKENS["compareBack"])
        holder.pack(fill="both", expand=True, padx=8, pady=4)
        self.listbox = tk.Listbox(
            holder.content, bg=TOKENS["compareBack"], fg=TOKENS["textPrimary"],
            font=FONT_MAIN, bd=0, highlightthickness=0, height=14, width=30,
            selectbackground=TOKENS["selection"], selectforeground=TOKENS["textPrimary"],
            activestyle="none")
        self.listbox.pack(fill="both", expand=True, padx=2, pady=2)
        self.listbox.bind("<Double-Button-1>", lambda e: self._pick())
        self.listbox.bind("<Return>", lambda e: self._pick())

        self.hint = VintageLabel(self, text="", fg=TOKENS["textMuted"], font=FONT_SM)
        self.hint.pack(anchor="w", padx=8)

        row = tk.Frame(self, bg=TOKENS["background"])
        row.pack(fill="x", padx=8, pady=6)
        VintageButton(row, text="Add", command=self._pick, width=8).pack(side="left")
        VintageButton(row, text="Cancel", command=self.destroy, width=8).pack(side="left", padx=4)

        self._refresh()
        entry.entry.focus_set()
        self.bind("<Escape>", lambda e: self.destroy())
        # Modal: the picker owns input until it closes, so a stray pedal press
        # can't land in a Bind button behind it.
        self.transient(parent)
        self.grab_set()

    def _visible(self):
        q = self.var_search.get().strip().lower()
        if not q:
            return self.pool
        return [n for n in self.pool if q in n.lower()]

    def _refresh(self):
        names = self._visible()
        self.listbox.delete(0, "end")
        for n in names:
            mark = "" if champions.is_sourced(n) else "  *"
            self.listbox.insert("end", n + mark)
        if names:
            self.listbox.selection_set(0)
        self.hint.config(text="%d of %d shown   * = placeholder combo"
                              % (len(names), len(self.pool)))

    def _pick(self):
        names = self._visible()
        sel = self.listbox.curselection()
        if not names or not sel:
            return
        name = names[sel[0]]
        self.destroy()
        self.on_pick(name)
