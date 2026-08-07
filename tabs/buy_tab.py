import tkinter as tk
import os, sys
from tkinter import messagebox
from theme import VintageButton, VintageLabel, VintageEntry, TOKENS, FONT_SM
from tabs.death_tab import ToolTip
from locales import Locale
from tabs.tab_config import load_json, save_json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class BuyTab(tk.Frame):
    CONFIG_NAME = "deathwatch_config.json"

    def _auto_save(self, *args):
        if hasattr(self, '_save_timer') and self._save_timer:
            self.after_cancel(self._save_timer)
        self._save_timer = self.after(500, self._do_save)

    def _do_save(self):
        self._save_timer = None
        self.save(silent=True)

    def __init__(self, parent):
        super().__init__(parent, bg=TOKENS["background"])
        self.cfg_path = os.path.join(BASE, self.CONFIG_NAME)
        cfg = load_json(self.cfg_path)

        head = tk.Frame(self, bg=TOKENS["background"])
        head.pack(fill="x", padx=4, pady=(4, 1))
        self._lbl_title = VintageLabel(head, text=Locale.tr("auto_buy_title"))
        self._lbl_title.pack(anchor="w")

        self._locale_widgets = []
        self._locale_widgets.append(("lbl", self._lbl_title, "auto_buy_title"))

        form = tk.Frame(self, bg=TOKENS["background"])
        form.pack(fill="x", padx=4, pady=2)

        r = 0
        self._lbl_qkey = VintageLabel(form, text=Locale.tr("quickbuy_key_lbl"), font=FONT_SM)
        self._lbl_qkey.grid(row=r, column=0, sticky="w", pady=1)
        self._locale_widgets.append(("lbl", self._lbl_qkey, "quickbuy_key_lbl"))
        self.quickbuy_key = tk.StringVar(value=cfg.get("quickbuy_key", "Z"))
        self.quickbuy_key.trace_add("write", self._auto_save)
        qk_entry = VintageEntry(form, textvariable=self.quickbuy_key, width=4)
        qk_entry.grid(row=r, column=1, sticky="w")
        ToolTip(qk_entry, key="tt_quickbuy_key")

        self._lbl_presses = VintageLabel(form, text=Locale.tr("presses_lbl"), font=FONT_SM)
        self._lbl_presses.grid(row=r, column=2, sticky="w", padx=(6, 1))
        self._locale_widgets.append(("lbl", self._lbl_presses, "presses_lbl"))
        self.quickbuy_presses = tk.StringVar(value=cfg.get("quickbuy_presses", 5))
        self.quickbuy_presses.trace_add("write", self._auto_save)
        VintageEntry(form, textvariable=self.quickbuy_presses, width=4).grid(row=r, column=3, sticky="w")

        self._lbl_wms = VintageLabel(form, text=Locale.tr("window_ms_lbl"), font=FONT_SM)
        self._lbl_wms.grid(row=r, column=4, sticky="w", padx=(6, 1))
        self._locale_widgets.append(("lbl", self._lbl_wms, "window_ms_lbl"))
        self.quickbuy_window_ms = tk.StringVar(value=cfg.get("quickbuy_window_ms", 10.0))
        self.quickbuy_window_ms.trace_add("write", self._auto_save)
        qw_entry = VintageEntry(form, textvariable=self.quickbuy_window_ms, width=6)
        qw_entry.grid(row=r, column=5, sticky="w")
        ToolTip(qw_entry, key="tt_quickbuy_window")

        r += 1
        sep = tk.Frame(form, bg=TOKENS["borderMuted"], height=1)
        sep.grid(row=r, column=0, columnspan=6, sticky="ew", pady=4)

        r += 1
        self.autobuy_b = tk.BooleanVar(value=cfg.get("autobuy_after_b", False))
        self.autobuy_b.trace_add("write", self._auto_save)
        buy_ckbtn = tk.Checkbutton(form, text=Locale.tr("autobuy_after_b"), variable=self.autobuy_b,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"])
        buy_ckbtn.grid(row=r, column=0, columnspan=2, sticky="w", pady=1)
        self._locale_widgets.append(("chk", buy_ckbtn, "autobuy_after_b"))
        ToolTip(buy_ckbtn, key="tt_autobuy_after_b")

        self._lbl_delay = VintageLabel(form, text=Locale.tr("delay_s_lbl"), font=FONT_SM)
        self._lbl_delay.grid(row=r, column=2, sticky="w", padx=(6, 1))
        self._locale_widgets.append(("lbl", self._lbl_delay, "delay_s_lbl"))
        self.buy_delay_sec = tk.StringVar(value=cfg.get("buy_after_b_delay_sec", 5.5))
        self.buy_delay_sec.trace_add("write", self._auto_save)
        bd_entry = VintageEntry(form, textvariable=self.buy_delay_sec, width=5)
        bd_entry.grid(row=r, column=3, sticky="w")
        ToolTip(bd_entry, key="tt_buy_delay")

        r += 1
        self.buy_then_mid = tk.BooleanVar(value=cfg.get("autobuy_then_mid", False))
        self.buy_then_mid.trace_add("write", self._auto_save)
        mid_ckbtn = tk.Checkbutton(form, text=Locale.tr("click_mid_after_buy"), variable=self.buy_then_mid,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"],
                       selectcolor=TOKENS["compareBack"])
        mid_ckbtn.grid(row=r, column=0, columnspan=2, sticky="w", pady=1)
        self._locale_widgets.append(("chk", mid_ckbtn, "click_mid_after_buy"))
        ToolTip(mid_ckbtn, key="tt_click_mid_after_buy")

        self._lbl_delay2 = VintageLabel(form, text=Locale.tr("delay_s_lbl"), font=FONT_SM)
        self._lbl_delay2.grid(row=r, column=2, sticky="w", padx=(6, 1))
        self._locale_widgets.append(("lbl", self._lbl_delay2, "delay_s_lbl"))
        self.buy_then_mid_delay = tk.StringVar(value=cfg.get("autobuy_then_mid_delay_sec", 0.5))
        self.buy_then_mid_delay.trace_add("write", self._auto_save)
        tm_entry = VintageEntry(form, textvariable=self.buy_then_mid_delay, width=5)
        tm_entry.grid(row=r, column=3, sticky="w")
        ToolTip(tm_entry, key="tt_mid_delay")

        r += 1
        self.controlsend_z = tk.BooleanVar(value=cfg.get("controlsend_z", False))
        self.controlsend_z.trace_add("write", self._auto_save)
        cs_ckbtn = tk.Checkbutton(form, text=Locale.tr("bg_z_lbl"), variable=self.controlsend_z,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"],
                       selectcolor=TOKENS["compareBack"])
        cs_ckbtn.grid(row=r, column=0, columnspan=3, sticky="w", pady=1)
        self._locale_widgets.append(("chk", cs_ckbtn, "bg_z_lbl"))
        ToolTip(cs_ckbtn, key="tt_bg_z")

        btn_frame = tk.Frame(self, bg=TOKENS["background"])
        btn_frame.pack(fill="x", padx=4, pady=6)
        self._btn_reset = VintageButton(btn_frame, text=Locale.tr("reset_lbl"), command=self.reset_defaults, width=8)
        self._btn_reset.pack(side="left")
        self._locale_widgets.append(("btn", self._btn_reset, "reset_lbl"))

    def apply_locale(self):
        for kind, widget, key in self._locale_widgets:
            if kind == "lbl":
                widget.config(text=Locale.tr(key))
            elif kind == "btn":
                widget.label.config(text=Locale.tr(key))
            elif kind == "chk":
                widget.config(text=Locale.tr(key))

    def reset_defaults(self):
        cfg = load_json(self.cfg_path)
        self.quickbuy_key.set(cfg.get("quickbuy_key", "Z"))
        self.quickbuy_presses.set(str(cfg.get("quickbuy_presses", 5)))
        self.quickbuy_window_ms.set(str(cfg.get("quickbuy_window_ms", 150.0)))
        self.autobuy_b.set(cfg.get("autobuy_after_b", False))
        self.buy_delay_sec.set(str(cfg.get("buy_after_b_delay_sec", 5.5)))
        self.buy_then_mid.set(cfg.get("autobuy_then_mid", False))
        self.buy_then_mid_delay.set(str(cfg.get("autobuy_then_mid_delay_sec", 0.5)))
        self.controlsend_z.set(cfg.get("controlsend_z", False))

    def save(self, silent=False):
        try:
            cfg = load_json(self.cfg_path)
            cfg["quickbuy_key"] = self.quickbuy_key.get()
            cfg["quickbuy_presses"] = int(self.quickbuy_presses.get())
            cfg["quickbuy_window_ms"] = float(self.quickbuy_window_ms.get())
            cfg["autobuy_after_b"] = self.autobuy_b.get()
            cfg["buy_after_b_delay_sec"] = float(self.buy_delay_sec.get())
            cfg["autobuy_then_mid"] = self.buy_then_mid.get()
            cfg["autobuy_then_mid_delay_sec"] = float(self.buy_then_mid_delay.get())
            cfg["controlsend_z"] = self.controlsend_z.get()
        except ValueError as e:
            if silent:
                print(f"BuyTab save skipped: {e}", file=sys.stderr)
            else:
                messagebox.showerror(Locale.tr("invalid_value"), str(e))
            return
        save_json(self.cfg_path, cfg)
