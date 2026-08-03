import tkinter as tk
from tkinter import ttk

import champions
from theme import VintageButton, VintageLabel, VintageEntry, TOKENS, FONT_SM, FONT_MAIN
from tabs.champ_tab import BindButton
from locales import Locale

# ── simple tooltip ─────────────────────────────────────────────────
class _ToolTip:
    """Thin tooltip that appears on hover with the full combo."""
    def __init__(self, widget):
        self.widget = widget
        self._tw = None
        self._after = None
        widget.bind("<Enter>", self._enter)
        widget.bind("<Leave>", self._leave)
        widget.bind("<Motion>", self._motion)

    def _enter(self, e):
        self._schedule()

    def _leave(self, e):
        # Same guard as tabs.death_tab.ToolTip: a Leave fired while the pointer
        # is still inside the widget means the tip popped up underneath it, and
        # acting on it starts a hide/show flicker loop.
        try:
            x = self.widget.winfo_pointerx() - self.widget.winfo_rootx()
            y = self.widget.winfo_pointery() - self.widget.winfo_rooty()
            if (0 <= x < self.widget.winfo_width()
                    and 0 <= y < self.widget.winfo_height()):
                return
        except tk.TclError:
            pass
        self._unschedule()
        self._hide()

    def _motion(self, e):
        self._x, self._y = e.x_root, e.y_root

    def _schedule(self):
        self._unschedule()
        self._after = self.widget.after(400, self._show)

    def _unschedule(self):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self):
        self._hide()
        text = getattr(self.widget, "_tip_text", "")
        if not text:
            return
        self._tw = tw = tk.Toplevel(self.widget)
        tw.overrideredirect(True)
        tw.geometry("+%d+%d" % (self._x + 12, self._y + 8))
        tk.Label(tw, text=text, justify="left", bg="#FFFFE0", fg="#000",
                 font=("Consolas", 8), padx=4, pady=2, borderwidth=1,
                 relief="solid").pack()

    def _hide(self):
        if self._tw:
            self._tw.destroy()
            self._tw = None


class ChampionTab(tk.Frame):
    """Single tab with champion dropdown + config for selected champion.

    Replaces per-champion notebook tabs.  Saves directly into config["champions"]
    via the callback.
    """

    def __init__(self, parent, champions_data, on_select=None, on_remove=None):
        super().__init__(parent, bg=TOKENS["background"])
        self.champions_data = champions_data
        self.on_select = on_select
        self.on_remove = on_remove
        self._current_key = None
        self._vars = {}
        self._locale_widgets = []
        self._champ_locale = []

        head = tk.Frame(self, bg=TOKENS["background"])
        head.pack(fill="x", padx=4, pady=(4, 2))

        self._lbl_champion = VintageLabel(head, text=Locale.tr("champion"))
        self._lbl_champion.pack(side="left")
        self._locale_widgets.append(("lbl", self._lbl_champion, "champion"))
        self.var_champ = tk.StringVar()
        self.var_champ.trace_add("write", self._on_champ_change)
        self.champ_combo = ttk.Combobox(head, textvariable=self.var_champ,
                                         width=14, font=FONT_SM, state="readonly")
        self.champ_combo.pack(side="left", padx=4)
        self.btn_add = VintageButton(head, text="+", command=self._pick_champion, width=2)
        self.btn_add.pack(side="left")
        self.btn_remove = VintageButton(head, text=Locale.tr("remove_lbl"), command=self._remove_current,
                                        width=7)
        self.btn_remove.pack(side="right", padx=(2, 0))
        self._locale_widgets.append(("btn", self.btn_remove, "remove_lbl"))
        self.btn_reset = VintageButton(head, text=Locale.tr("reset_lbl"), command=self._reset_current,
                                       width=6)
        self.btn_reset.pack(side="right")
        self._locale_widgets.append(("btn", self.btn_reset, "reset_lbl"))

        sep = tk.Frame(self, bg=TOKENS["borderMuted"], height=1)
        sep.pack(fill="x", padx=4)

        self.form = tk.Frame(self, bg=TOKENS["background"])
        self.form.pack(fill="x", padx=4, pady=4)

        self._info_lbl = VintageLabel(self.form, text=Locale.tr("select_hint"),
                                       fg=TOKENS["textMuted"])
        self._info_lbl.pack(anchor="w", pady=10)
        self._locale_widgets.append(("lbl", self._info_lbl, "select_hint"))

        self._champ_form = None

        self.refresh_list()

    def apply_locale(self):
        for kind, widget, key in self._locale_widgets:
            if kind == "lbl":
                widget.config(text=Locale.tr(key))
            elif kind == "btn":
                widget.label.config(text=Locale.tr(key))
        for kind, widget, key in self._champ_locale:
            if kind == "lbl":
                widget.config(text=Locale.tr(key))
            elif kind == "chk":
                widget.config(text=Locale.tr(key))

    def refresh_list(self):
        names = []
        for _, entry in self.champions_data.items():
            if isinstance(entry, dict):
                n = entry.get("display_name", "?")
                names.append(n)
            else:
                names.append("?")
        self.champ_combo["values"] = names
        current = self.var_champ.get()
        if current and current in names:
            self.var_champ.set(current)
        elif names:
            self.var_champ.set(names[0])

    def _on_champ_change(self, *args):
        name = self.var_champ.get()
        if not name:
            return
        key = champions.slug(name)
        if key == self._current_key:
            return
        self._save_current()
        self._current_key = key
        self._build_form(name, key)
        if self.on_select:
            self.on_select(key)

    def _get_entry(self, key):
        return self.champions_data.get(key, {})

    def _build_form(self, name, key):
        if self._champ_form:
            self._champ_form.destroy()
        self._info_lbl.pack_forget()
        self._vars.clear()
        self._champ_locale = []

        entry = self._get_entry(key)
        defaults = champions.default_for(name)
        cfg = dict(defaults)
        if isinstance(entry, dict):
            cfg.update(entry)

        self._champ_form = tk.Frame(self.form, bg=TOKENS["background"])
        self._champ_form.pack(fill="x")

        # preset storage: list of 3 dicts {keys, name} per slot
        self._presets = {}

        for row, slot in enumerate(("wave", "jungle", "pvp")):
            tv = tk.StringVar(value=cfg.get("trigger_" + slot, ""))
            kv = tk.StringVar(value=cfg.get("keys_" + slot, ""))
            mv = tk.BooleanVar(value=cfg.get("move_when_pressed_" + slot, False))
            self._vars["trigger_" + slot] = tv
            self._vars["keys_" + slot] = kv
            self._vars["move_when_pressed_" + slot] = mv

            # load & normalize presets for this slot
            self._presets[slot] = self._normalize_presets(cfg.get("presets_" + slot, []))

            slot_lbl = VintageLabel(self._champ_form, text=Locale.tr("slot_" + slot))
            slot_lbl.grid(row=row, column=0, sticky="w", pady=1)
            self._champ_locale.append(("lbl", slot_lbl, "slot_" + slot))
            VintageEntry(self._champ_form, textvariable=tv, width=6).grid(
                row=row, column=1, sticky="w", pady=1)
            BindButton(self._champ_form, tv).grid(row=row, column=2, sticky="w", padx=1)
            VintageEntry(self._champ_form, textvariable=kv, width=22).grid(
                row=row, column=3, sticky="w", padx=(4, 0), pady=1)
            
            # Move when pressed checkbox: also hold RButton (move) with the combo
            move_chk = tk.Checkbutton(self._champ_form, text=Locale.tr("champ_move_when_pressed"),
                           variable=mv,
                           bg=TOKENS["background"], fg=TOKENS["textPrimary"],
                           selectcolor=TOKENS["compareBack"],
                           activebackground=TOKENS["background"],
                           activeforeground=TOKENS["textPrimary"],
                           font=FONT_SM, highlightthickness=0, bd=0)
            move_chk.grid(row=row, column=4, sticky="w", padx=2)
            self._champ_locale.append(("chk", move_chk, "champ_move_when_pressed"))

            # --- 3 preset buttons with trigger label ---
            pframe = tk.Frame(self._champ_form, bg=TOKENS["background"])
            pframe.grid(row=row, column=5, sticky="w", padx=(3, 2))
            self._build_preset_buttons(pframe, slot, kv, tv)



        row2 = tk.Frame(self._champ_form, bg=TOKENS["background"])
        row2.grid(row=3, column=0, columnspan=6, sticky="w", pady=4)
        self._lbl_interval = VintageLabel(row2, text=Locale.tr("interval_ms_lbl"))
        self._lbl_interval.pack(side="left")
        self._champ_locale.append(("lbl", self._lbl_interval, "interval_ms_lbl"))
        self._var_interval = tk.IntVar(value=int(cfg.get("interval", 50)))
        VintageEntry(row2, textvariable=self._var_interval, width=5).pack(side="left", padx=2)

        self._var_shift = tk.BooleanVar(value=cfg.get("use_shift", True))
        self._chk_shift = tk.Checkbutton(row2, text=Locale.tr("shift_modifier"), variable=self._var_shift,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"],
                       selectcolor=TOKENS["compareBack"],
                       activebackground=TOKENS["background"],
                       activeforeground=TOKENS["textPrimary"],
                       font=FONT_SM, highlightthickness=0, bd=0)
        self._chk_shift.pack(side="left", padx=(8, 2))
        self._champ_locale.append(("chk", self._chk_shift, "shift_modifier"))

        self._var_uiop = tk.BooleanVar(value=cfg.get("qwer_as_uiop", False))
        self._chk_uiop = tk.Checkbutton(row2, text=Locale.tr("qwer_uiop"), variable=self._var_uiop,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"],
                       selectcolor=TOKENS["compareBack"],
                       activebackground=TOKENS["background"],
                       activeforeground=TOKENS["textPrimary"],
                       font=FONT_SM, highlightthickness=0, bd=0)
        self._chk_uiop.pack(side="left", padx=2)
        self._champ_locale.append(("chk", self._chk_uiop, "qwer_uiop"))

        if defaults.get("sourced"):
            note_key, colour = "combo_sourced", TOKENS["textMuted"]
        else:
            note_key, colour = "combo_placeholder", TOKENS["warning"]
        self._lbl_note = VintageLabel(row2, text=Locale.tr(note_key), fg=colour, font=FONT_SM)
        self._lbl_note.pack(side="left", padx=8)
        self._champ_locale.append(("lbl", self._lbl_note, note_key))

        self._refresh_preset_visuals()

    def _normalize_presets(self, raw):
        """Normalize to list of 3 dicts {keys, name}. Handles old string format."""
        if not isinstance(raw, list):
            raw = []
        result = []
        for item in raw[:3]:
            if isinstance(item, str):
                result.append({"keys": item, "name": ""})
            elif isinstance(item, dict):
                result.append({"keys": item.get("keys", ""), "name": item.get("name", "")})
            else:
                result.append({"keys": "", "name": ""})
        while len(result) < 3:
            result.append({"keys": "", "name": ""})
        return result

    def _build_preset_buttons(self, parent, slot, keys_var, trigger_var):
        """Three preset buttons with trigger-key label, names, tooltips, per-slot reset."""
        # trigger key label (F13/F14/F15) — updates live via trace
        trig_lbl = VintageLabel(parent, text=trigger_var.get() or "?",
                                font=FONT_SM, fg=TOKENS["textMuted"])
        trig_lbl.pack(side="left", padx=(0, 2))
        trigger_var.trace_add("write", lambda *a: trig_lbl.config(
            text=trigger_var.get() or "?"))

        for i in range(3):
            row = tk.Frame(parent, bg=TOKENS["background"])
            row.pack(side="left")
            preset = self._presets[slot][i]
            label = preset["name"] or str(i + 1)
            btn = VintageButton(row, text=label, width=len(label) if len(label) <= 10 else 10)
            btn.pack(side="left", padx=1)
            btn._p_slot = slot
            btn._p_idx = i
            tip = preset["keys"] if preset["keys"] else ""
            btn._tip_text = tip
            btn.content._tip_text = tip  # _ToolTip reads from content
            btn.command = lambda s=slot, idx=i: self._apply_preset(s, idx, keys_var)
            # right-click: save current keys to this slot
            for w in (btn, btn.inner, btn.content, btn.label):
                w.bind("<Button-3>",
                       lambda e, s=slot, idx=i: self._save_preset(s, idx, keys_var))
            # middle-click: edit name (no conflict with left-click apply)
            for w in (btn, btn.inner, btn.content, btn.label):
                w.bind("<Button-2>",
                       lambda e, s=slot, idx=i: self._edit_preset_name(s, idx))
            # tooltip on the content frame (covers whole button face)
            _ToolTip(btn.content)
            # ↺ reset button for this preset (darker bg to distinguish)
            reset = VintageButton(row, text="↺", width=1,
                                  command=lambda s=slot, idx=i: self._reset_preset(s, idx))
            reset.bg_normal = TOKENS["surface"]
            reset.bg_pressed = TOKENS["surfaceRaised"]
            reset._paint(TOKENS["surface"])
            reset.pack(side="left", padx=(0, 1))

        # trace keys_var to re-check active state on every keystroke
        keys_var.trace_add("write", lambda *a: self._refresh_preset_visuals())

    def _reset_preset(self, slot, idx):
        """Clear keys and name for one preset slot only."""
        self._presets[slot][idx]["keys"] = ""
        self._presets[slot][idx]["name"] = ""
        self._refresh_preset_visuals()

    def _apply_preset(self, slot, idx, keys_var):
        """Apply preset keys to the keys field."""
        keys = self._presets[slot][idx]["keys"]
        if keys:
            keys_var.set(keys)

    def _save_preset(self, slot, idx, keys_var):
        """Save current keys value into this preset slot."""
        keys = keys_var.get().strip()
        self._presets[slot][idx]["keys"] = keys
        self._refresh_preset_visuals()

    def _edit_preset_name(self, slot, idx):
        """Open small dialog to rename a preset slot."""
        current = self._presets[slot][idx]["name"]
        win = tk.Toplevel(self.winfo_toplevel())
        win.title(Locale.tr("rename_preset"))
        win.configure(bg=TOKENS["background"])
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        tk.Label(win, text=Locale.tr("preset_name"), bg=TOKENS["background"],
                 fg=TOKENS["textPrimary"], font=FONT_SM).pack(padx=8, pady=(6, 2))
        var = tk.StringVar(value=current)
        entry = tk.Entry(win, textvariable=var, bg=TOKENS["compareBack"],
                         fg=TOKENS["textPrimary"], font=FONT_MAIN, bd=0,
                         highlightthickness=1, highlightbackground=TOKENS["borderHighlight"],
                         insertbackground=TOKENS["textPrimary"], width=18)
        entry.pack(padx=8, pady=2)
        entry.select_range(0, "end")
        entry.focus_set()

        def ok():
            name = var.get().strip()
            self._presets[slot][idx]["name"] = name
            self._refresh_preset_visuals()
            win.destroy()

        def on_key(e):
            if e.keysym == "Return":
                ok()
            elif e.keysym == "Escape":
                win.destroy()

        entry.bind("<KeyPress>", on_key)
        btn_frame = tk.Frame(win, bg=TOKENS["background"])
        btn_frame.pack(pady=(2, 6))
        VintageButton(btn_frame, text=Locale.tr("ok"), command=ok, width=6).pack(side="left", padx=2)
        VintageButton(btn_frame, text=Locale.tr("cancel"), command=win.destroy, width=6).pack(side="left", padx=2)

    def _refresh_preset_visuals(self):
        """Update preset button labels, tooltips, and dim-state."""
        if not self._champ_form or not hasattr(self, '_presets'):
            return
        for child in self._champ_form.winfo_children():
            if isinstance(child, tk.Frame):
                self._update_preset_frame(child)

    def _update_preset_frame(self, frame):
        for child in frame.winfo_children():
            if isinstance(child, VintageButton) and hasattr(child, '_p_slot'):
                slot = child._p_slot
                idx = child._p_idx
                presets = self._presets.get(slot)
                if not presets or idx >= len(presets):
                    continue
                preset = presets[idx]
                keys = preset["keys"]
                name = preset["name"]
                # update button text & width
                display = name or str(idx + 1)
                w = min(len(display), 10) if name else 1
                child.label.config(text=display, width=w)
                # update tooltip (set on both btn and btn.content for _ToolTip)
                tip = keys if keys else ""
                child._tip_text = tip
                child.content._tip_text = tip

                # Check if this preset matches the current keys field
                current_keys = self._vars.get("keys_" + slot, tk.StringVar()).get()
                is_active = bool(keys) and keys == current_keys

                # Store original bg_normal on first pass
                if not hasattr(child, '_bg_normal_orig'):
                    child._bg_normal_orig = child.bg_normal

                if is_active:
                    child.bg_normal = TOKENS["accentTealDeep"]
                    child.bg_hover = TOKENS["accentTealDeep"]
                    child._paint(TOKENS["accentTealDeep"])
                    child.label.config(fg=TOKENS["textPrimary"])
                else:
                    child.bg_normal = child._bg_normal_orig
                    child.bg_hover = TOKENS["surfaceAlt"]
                    child._paint(child._bg_normal_orig)
                    fg = TOKENS["textPrimary"] if keys else TOKENS["textMuted"]
                    child.label.config(fg=fg)

    def _save_current(self):
        if not self._current_key or not self._vars:
            return
        out = {k: v.get() for k, v in self._vars.items()}
        if self._var_interval:
            try:
                out["interval"] = int(self._var_interval.get())
            except (tk.TclError, ValueError):
                out["interval"] = 50
        if hasattr(self, "_var_shift") and self._var_shift:
            out["use_shift"] = self._var_shift.get()
        if hasattr(self, "_var_uiop") and self._var_uiop:
            out["qwer_as_uiop"] = self._var_uiop.get()
        name = self.var_champ.get()
        if name:
            out["display_name"] = name
        # Save presets as list of dicts
        for slot in ("wave", "jungle", "pvp"):
            out["presets_" + slot] = list(self._presets.get(slot, [
                {"keys": "", "name": ""}, {"keys": "", "name": ""}, {"keys": "", "name": ""}]))
        self.champions_data[self._current_key] = out

    def _pick_champion(self):
        from champ_picker import ChampionPicker
        already = []
        for _, entry in self.champions_data.items():
            if isinstance(entry, dict) and entry.get("display_name"):
                already.append(entry["display_name"])
        ChampionPicker(self.winfo_toplevel(), self._on_picked,
                       already=already)

    def _on_picked(self, name):
        key = champions.slug(name)
        if key in self.champions_data:
            self.var_champ.set(name)
            return
        import champions as ch
        self.champions_data[key] = dict(ch.default_for(name), display_name=name)
        self.refresh_list()
        self.var_champ.set(name)

    def _remove_current(self):
        name = self.var_champ.get()
        if not name:
            return
        key = champions.slug(name)
        if key not in self.champions_data:
            return
        del self.champions_data[key]
        if self._champ_form:
            self._champ_form.destroy()
            self._champ_form = None
        self._current_key = None
        self._vars.clear()
        self._info_lbl.pack(anchor="w", pady=10)
        self.refresh_list()
        if self.on_remove:
            self.on_remove(key)

    def _reset_current(self):
        name = self.var_champ.get()
        if not name:
            return
        key = champions.slug(name)
        defaults = champions.default_for(name)
        self.champions_data[key] = dict(defaults, display_name=name)
        self._build_form(name, key)

    def get_data(self):
        self._save_current()
        return self.champions_data
