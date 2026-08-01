import tkinter as tk
from theme import VintageButton


class BindButton(VintageButton):
    """Click, then press any key - the keysym (F13, a, space...) lands in the
    target StringVar. Covers the F13-F24 pedals."""

    def __init__(self, parent, target_var, **kwargs):
        super().__init__(parent, text="Bind", command=self._arm, width=5, **kwargs)
        self.target_var = target_var
        self._armed = False

    def _arm(self):
        if self._armed:
            self._disarm()
            return
        self._armed = True
        self.label.config(text="press")
        top = self.winfo_toplevel()
        self._token = top.bind_all("<KeyPress>", self._capture, add="+")

    def _disarm(self):
        if self._token:
            try:
                self.winfo_toplevel().unbind("<KeyPress>", self._token)
            except tk.TclError:
                pass
            self._token = None
        self._armed = False
        self.label.config(text="Bind")

    def _capture(self, event):
        if not self._armed:
            return None
        keysym = event.keysym
        if keysym == "Escape":                # escape = cancel, not a bind
            self._disarm()
            return "break"
        # tk keysym -> AHK key name where they differ
        remap = {"space": "Space", "Return": "Enter", "Prior": "PgUp",
                 "Next": "PgDn", "Tab": "Tab", "BackSpace": "BackSpace"}
        self.target_var.set(remap.get(keysym, keysym))
        self._disarm()
        return "break"


# ChampTab removed in v7.25.0 — replaced by ChampionTab in champion_tab.py.
# BindButton above is still used by: combo_tab, minimap_tab, champion_tab, afkfarm_tab.
