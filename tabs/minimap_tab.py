import tkinter as tk
from theme import VintageButton, VintageLabel, VintageEntry, TOKENS, FONT_SM
from tabs.champ_tab import BindButton
from locales import Locale

MINIMAP_DEFAULTS = {
    "top":        {"trigger": "F17", "x": 64,  "y": 137},
    "mid":        {"trigger": "F18", "x": 116, "y": 293},
    "bot":        {"trigger": "F19", "x": 268, "y": 369},
    "top_deep":   {"trigger": "F20", "x": 206, "y": 135},
    "mid_deep":   {"trigger": "F21", "x": 233, "y": 182},
    "bot_deep":   {"trigger": "F22", "x": 282, "y": 211},
    "base":       {"trigger": "",    "x": 287, "y": 133},
    "enemy_base": {"trigger": "",    "x": 80,  "y": 80},
}

DEFAULT_ORDER = [
    "top", "mid", "bot", "top_deep", "mid_deep", "bot_deep",
    "base", "enemy_base",
]

SLOT_LABELS = {
    "top": "Top", "mid": "Mid", "bot": "Bot",
    "top_deep": "Top Deep", "mid_deep": "Mid Deep", "bot_deep": "Bot Deep",
    "base": "Base", "enemy_base": "Enemy Base",
}


class MinimapTab(tk.Frame):
    _drag_source = None
    _drag_indicator = None

    def __init__(self, parent, saved=None):
        super().__init__(parent, bg=TOKENS["background"])

        self._custom_counter = 0
        self._rows = {}  # key -> dict of StringVar/IntVar + widgets

        # Build slot dict from saved + defaults
        self.slots = self._merge_slots(saved)

        head = tk.Frame(self, bg=TOKENS["background"])
        head.pack(fill="x", padx=4, pady=(4, 1))
        self._lbl_title = VintageLabel(head, text=Locale.tr("minimap_title"))
        self._lbl_title.pack(anchor="w")
        self._lbl_sub = VintageLabel(head, text=Locale.tr("minimap_sub"),
                     font=FONT_SM, fg=TOKENS["textMuted"])
        self._lbl_sub.pack(anchor="w")
        self._locale_widgets = [
            ("lbl", self._lbl_title, "minimap_title"),
            ("lbl", self._lbl_sub, "minimap_sub"),
        ]

        # Scrollable area
        self._canvas = tk.Canvas(self, bg=TOKENS["background"], highlightthickness=0)
        self._canvas.pack(side="left", fill="both", expand=True, padx=4)
        self._canvas.bind("<Configure>", self._resize_canvas)

        scroll = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        scroll.pack(side="right", fill="y")
        self._canvas.configure(yscrollcommand=scroll.set)

        self._form = tk.Frame(self._canvas, bg=TOKENS["background"])
        def _on_form_cfg(e):
            sig = (e.width, e.height)
            if getattr(self, "_last_form_sig", None) == sig:
                return
            self._last_form_sig = sig
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._form.bind("<Configure>", _on_form_cfg)
        self._form_id = self._canvas.create_window((0, 0), window=self._form, anchor="nw")

        # Mousewheel scroll
        def _mw(event):
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", _mw, add="+"))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

        # Header
        self._draw_header()

        self._rebuild_form()

        btn_frame = tk.Frame(self, bg=TOKENS["background"])
        btn_frame.pack(fill="x", padx=4, pady=2)
        self._btn_add = VintageButton(btn_frame, text=Locale.tr("add_lbl"), command=self.add_slot,
                      width=7)
        self._btn_add.pack(side="left", padx=1)
        self._locale_widgets.append(("btn", self._btn_add, "add_lbl"))
        self._btn_reset = VintageButton(btn_frame, text=Locale.tr("reset_defaults"),
                      command=self.reset_defaults, width=13)
        self._btn_reset.pack(side="left", padx=6)
        self._locale_widgets.append(("btn", self._btn_reset, "reset_defaults"))
        self._btn_apply = VintageButton(btn_frame, text=Locale.tr("apply_to_engine"),
                      command=self._trigger_apply, width=15)
        self._btn_apply.pack(side="right", padx=1)
        self._locale_widgets.append(("btn", self._btn_apply, "apply_to_engine"))

    def _draw_header(self):
        hdr_fg = TOKENS["textSecondary"]
        self._hdr_name = VintageLabel(self._form, text=Locale.tr("name_lbl"), font=FONT_SM, fg=hdr_fg)
        self._hdr_name.grid(row=0, column=0, sticky="w", padx=1)
        self._hdr_hotkey = VintageLabel(self._form, text=Locale.tr("hotkey_lbl"), font=FONT_SM, fg=hdr_fg)
        self._hdr_hotkey.grid(row=0, column=1, sticky="w", padx=(2, 1))
        VintageLabel(self._form, text="X", font=FONT_SM, fg=hdr_fg
                     ).grid(row=0, column=3, sticky="w", padx=(4, 1))
        VintageLabel(self._form, text="Y", font=FONT_SM, fg=hdr_fg
                     ).grid(row=0, column=4, sticky="w", padx=1)

    def apply_locale(self):
        self._hdr_name.config(text=Locale.tr("name_lbl"))
        self._hdr_hotkey.config(text=Locale.tr("hotkey_lbl"))
        for kind, widget, key in self._locale_widgets:
            if kind == "lbl":
                widget.config(text=Locale.tr(key))
            elif kind == "btn":
                widget.label.config(text=Locale.tr(key))
        for key, r in self._rows.items():
            lbl = r.get("name_lbl")
            if lbl:
                lbl.config(text=Locale.tr("slots." + key, fallback=key.replace("_", " ").title()) + ":")

    def _trigger_apply(self):
        try:
            self.event_generate("<<ApplyStart>>")
        except tk.TclError:
            pass

    # --- data merging --------------------------------------------------------
    def _merge_slots(self, saved):
        slots = {}
        loaded_order = None
        if saved and isinstance(saved, dict):
            loaded_order = saved.get("_order")
            for k, v in saved.items():
                if k == "_order" or not isinstance(v, dict):
                    continue
                d = dict(MINIMAP_DEFAULTS.get(k, {"trigger": "", "x": 0, "y": 0}))
                for kk in ("trigger", "x", "y"):
                    if kk in v:
                        d[kk] = v[kk]
                slots[k] = d
        for k, d in MINIMAP_DEFAULTS.items():
            if k not in slots:
                slots[k] = dict(d)
        self._loaded_order = loaded_order
        return slots

    def _resolve_order(self):
        if self._loaded_order:
            order = [k for k in self._loaded_order if k in self.slots]
            order += [k for k in self.slots if k not in order]
        else:
            order = [k for k in DEFAULT_ORDER if k in self.slots]
            order += [k for k in self.slots if k not in order]
        return order

    # --- row management ------------------------------------------------------
    def _rebuild_form(self):
        if self._drag_indicator:
            try:
                self._canvas.delete(self._drag_indicator)
            except tk.TclError:
                pass
            self._drag_indicator = None
        self._drag_source = None
        # Destroy all children of _form
        for w in list(self._form.winfo_children()):
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._rows.clear()

        # Re-draw header
        self._draw_header()

        order = self._resolve_order()
        for row_idx, key in enumerate(order, start=1):
            self._add_row(row_idx, key, track=True)

    def _auto_save(self, *args):
        try:
            self.event_generate("<<AutoSave>>")
        except tk.TclError:
            pass

    def _drag_begin(self, event, key):
        self._drag_source = key
        self._drag_start_y = event.y_root
        event.widget.configure(cursor="fleur")

    def _drag_motion(self, event, key):
        if self._drag_source is None:
            return
        # Draw indicator line on canvas
        if self._drag_indicator:
            try:
                self._canvas.delete(self._drag_indicator)
            except tk.TclError:
                self._drag_indicator = None
        y_in_form = event.y_root - self._form.winfo_rooty()
        y_in_form = max(4, min(self._form.winfo_height() - 2, y_in_form))
        self._drag_indicator = self._canvas.create_line(
            4, y_in_form + 10, self._canvas.winfo_width() - 4, y_in_form + 10,
            fill=TOKENS.get("accent", "#ffcc00"), width=2)

    def _drag_drop(self, event, key):
        if self._drag_source is None:
            return
        if self._drag_indicator:
            try:
                self._canvas.delete(self._drag_indicator)
            except tk.TclError:
                pass
            self._drag_indicator = None
        # Determine target position from mouse y
        order = self._resolve_order()
        if key not in order:
            self._drag_source = None
            return
        src_idx = order.index(key)
        y_in_form = event.y_root - self._form.winfo_rooty()
        row_h = 30
        target_row = max(0, min(len(order), int((y_in_form - 25) / row_h)))
        # Clamp to valid range
        target_row = max(0, min(len(order), target_row))
        if target_row != src_idx and target_row != src_idx + 1:
            order.remove(key)
            target_row = min(target_row, len(order))
            order.insert(target_row, key)
            self._loaded_order = list(order)
        self._drag_source = None
        self._rebuild_form()
        self._auto_save()

    def _add_row(self, row, key, track=False):
        d = self.slots.get(key, {"trigger": "", "x": 0, "y": 0})
        label = Locale.tr("slots." + key, fallback=SLOT_LABELS.get(key, key))

        if label:
            name_lbl = VintageLabel(self._form, text=label + ":", width=10)
            name_lbl.grid(row=row, column=0, sticky="w", pady=2)
            name_lbl.bind("<Button-1>", lambda e, k=key: self._drag_begin(e, k))
            name_lbl.bind("<B1-Motion>", lambda e, k=key: self._drag_motion(e, k))
            name_lbl.bind("<ButtonRelease-1>", lambda e, k=key: self._drag_drop(e, k))
            name_entry = None
        else:
            name_entry = VintageEntry(self._form, width=10)
            name_entry.grid(row=row, column=0, sticky="w", pady=2)
            # Bind drag on the entry too
            name_entry.bind("<Button-1>", lambda e, k=key: self._drag_begin(e, k))
            name_entry.bind("<B1-Motion>", lambda e, k=key: self._drag_motion(e, k))
            name_entry.bind("<ButtonRelease-1>", lambda e, k=key: self._drag_drop(e, k))
            name_lbl = None

        tv = tk.StringVar(value=d.get("trigger", ""))
        tv.trace_add("write", self._auto_save)
        trig_entry = VintageEntry(self._form, textvariable=tv, width=8)
        trig_entry.grid(row=row, column=1, sticky="w", pady=2)
        bind_btn = BindButton(self._form, tv)
        bind_btn.grid(row=row, column=2, sticky="w", padx=2)

        xv = tk.IntVar(value=int(d.get("x", 0)))
        xv.trace_add("write", self._auto_save)
        x_entry = VintageEntry(self._form, textvariable=xv, width=5)
        x_entry.grid(row=row, column=3, sticky="w", pady=2)

        yv = tk.IntVar(value=int(d.get("y", 0)))
        yv.trace_add("write", self._auto_save)
        y_entry = VintageEntry(self._form, textvariable=yv, width=5)
        y_entry.grid(row=row, column=4, sticky="w", pady=2)

        remove_btn = None
        if not label:
            remove_btn = VintageButton(self._form, text="X", width=2,
                                       command=lambda k=key: self.remove_slot(k))
            remove_btn.grid(row=row, column=5, sticky="w", padx=2)

        if track:
            self._rows[key] = {
                "name_entry": name_entry, "name_lbl": name_lbl, "trigger_var": tv,
                "x_var": xv, "y_var": yv, "remove_btn": remove_btn,
            }

    # --- public API ----------------------------------------------------------
    def add_slot(self):
        self._custom_counter += 1
        key = "custom_%d" % self._custom_counter
        self.slots[key] = {"trigger": "", "x": 0, "y": 0}
        row = len(self._rows) + 1
        self._add_row(row, key, track=True)
        self._auto_save()

    def remove_slot(self, key):
        if key not in self._rows:
            return
        self.slots.pop(key, None)
        self._rows.pop(key, None)
        self._rebuild_form()
        self._auto_save()

    def reset_defaults(self):
        self.slots = {k: dict(v) for k, v in MINIMAP_DEFAULTS.items()}
        self._loaded_order = None
        self._custom_counter = 0
        self._rebuild_form()
        self._auto_save()

    def get_data(self):
        # Read current values from live vars
        for key, r in list(self._rows.items()):
            try:
                x = int(r["x_var"].get())
            except (tk.TclError, ValueError):
                x = 0
            try:
                y = int(r["y_var"].get())
            except (tk.TclError, ValueError):
                y = 0
            self.slots[key] = {
                "trigger": r["trigger_var"].get().strip(),
                "x": x,
                "y": y,
            }

        order = self._resolve_order()
        out = {}
        for k in order:
            if k in self.slots:
                out[k] = dict(self.slots[k])
        # Also include any slots not in current order
        for k, v in self.slots.items():
            if k not in out:
                out[k] = dict(v)
        out["_order"] = order
        return out

    def _resize_canvas(self, event):
        if getattr(self, "_last_canvas_width", None) == event.width:
            return
        self._last_canvas_width = event.width
        try:
            self._canvas.itemconfig(self._form_id, width=event.width)
        except (tk.TclError, IndexError, AttributeError):
            pass
