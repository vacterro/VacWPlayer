import tkinter as tk
from theme import VintageButton
from locales import Locale


class BindButton(VintageButton):
    """Click, then press any key - the keysym (F13, a, space...) lands in the
    target StringVar. Covers the F13-F24 pedals."""

    # Mouse buttons a combo trigger can be bound to. MButton is the middle
    # button; XButton1/XButton2 are the side buttons. LMB/RMB are excluded -
    # they are the movement/attack remap, not combo triggers.
    _MOUSE_KEYS = {2: "MButton", 6: "XButton1", 7: "XButton2", 8: "XButton1", 9: "XButton2"}
    _BIND_SEQUENCES = ("<KeyPress>", "<ButtonPress-2>", "<ButtonPress-6>",
                       "<ButtonPress-7>", "<ButtonPress-8>", "<ButtonPress-9>")

    def __init__(self, parent, target_var, **kwargs):
        super().__init__(parent, text=Locale.tr("bind"), command=self._arm, width=5, **kwargs)
        self.target_var = target_var
        self._armed = False
        self._tokens = []

    def _arm(self):
        if self._armed:
            self._disarm()
            return
        self._armed = True
        self.label.config(text=Locale.tr("press_key"))
        top = self.winfo_toplevel()
        for seq in self._BIND_SEQUENCES:
            try:
                tok = top.bind_all(seq, self._capture, add="+")
                self._tokens.append((seq, tok))
            except tk.TclError:
                pass

    def _disarm(self):
        top = self.winfo_toplevel()
        for seq, tok in self._tokens:
            try:
                top.unbind(seq, tok)
            except tk.TclError:
                pass
        self._tokens = []
        self._armed = False
        self.label.config(text=Locale.tr("bind"))

    # VK -> physical key name. Tk's event.keycode is the Windows VK code,
    # which is layout-independent: the physical Q key reports VK 0x51 whether
    # QWERTY or ЙЦУКЕН is active, so the bound key always lands on the same
    # physical key.
    _VK_TO_KEY = {}
    for _i in range(10):
        _VK_TO_KEY[0x30 + _i] = str(_i)
    # VK codes are the base physical key regardless of Shift, so store letters
    # lowercase to match what users type by hand - keeps multi-bind dedupe and
    # the AHK generator seeing one canonical form (q, not Q).
    for _i in range(26):
        _VK_TO_KEY[0x41 + _i] = chr(0x61 + _i)
    for _i in range(24):
        _VK_TO_KEY[0x70 + _i] = "F%d" % (_i + 1)
    del _i

    _KEYSYM_FALLBACK = {"space": "Space", "Return": "Enter", "Prior": "PgUp",
                        "Next": "PgDn", "Tab": "Tab", "BackSpace": "BackSpace"}

    def _capture(self, event):
        if not self._armed:
            return None
        num = getattr(event, "num", None)
        if num in self._MOUSE_KEYS:
            # Mouse button press: MButton (2) or side buttons (6-9).
            self._set_bind(self._MOUSE_KEYS[num])
            return "break"
        keysym = event.keysym
        if keysym == "Escape":                # escape = cancel, not a bind
            self._disarm()
            return "break"
        vk = getattr(event, "keycode", 0)
        key = self._VK_TO_KEY.get(vk) if vk else None
        if key is None:
            # Not a typeable key (F13 pedals, Space, Enter...): fall back to
            # keysym, which for these named keys is layout-independent.
            key = self._KEYSYM_FALLBACK.get(keysym, keysym)
        self._set_bind(key)
        return "break"

    def _set_bind(self, key):
        current = self.target_var.get().strip()
        # Multi-bind: an existing comma-separated list gets the new key
        # appended (F13,F16,MButton) instead of being overwritten; dedupe
        # exact hits case-insensitively (Q vs q are the same key).
        existing = [t.strip().lower() for t in current.split(",") if t.strip()]
        if key.lower() not in existing:
            if current:
                key = current + "," + key
            self.target_var.set(key)
        self._disarm()


# ChampTab removed in v7.25.0 — replaced by ChampionTab in champion_tab.py.
# BindButton above is still used by: combo_tab, minimap_tab, champion_tab, afkfarm_tab.
