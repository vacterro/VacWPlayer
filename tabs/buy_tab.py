import tkinter as tk
import os, sys
import json
from tkinter import messagebox
from theme import VintageButton, VintageLabel, VintageEntry, TOKENS, FONT_SM
from tabs.death_tab import ToolTip

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

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
        VintageLabel(head, text="Auto-Buy After Recall").pack(anchor="w")

        form = tk.Frame(self, bg=TOKENS["background"])
        form.pack(fill="x", padx=4, pady=2)

        r = 0
        VintageLabel(form, text="Quick-buy key:", font=FONT_SM).grid(row=r, column=0, sticky="w", pady=1)
        self.quickbuy_key = tk.StringVar(value=cfg["quickbuy_key"])
        self.quickbuy_key.trace_add("write", self._auto_save)
        qk_entry = VintageEntry(form, textvariable=self.quickbuy_key, width=4)
        qk_entry.grid(row=r, column=1, sticky="w")
        ToolTip(qk_entry, "Key that buys items from quick-buy slots in shop")

        VintageLabel(form, text="Presses:", font=FONT_SM).grid(row=r, column=2, sticky="w", padx=(6, 1))
        self.quickbuy_presses = tk.StringVar(value=cfg["quickbuy_presses"])
        self.quickbuy_presses.trace_add("write", self._auto_save)
        VintageEntry(form, textvariable=self.quickbuy_presses, width=4).grid(row=r, column=3, sticky="w")

        VintageLabel(form, text="Window (ms):", font=FONT_SM).grid(row=r, column=4, sticky="w", padx=(6, 1))
        self.quickbuy_window_ms = tk.StringVar(value=cfg["quickbuy_window_ms"])
        self.quickbuy_window_ms.trace_add("write", self._auto_save)
        qw_entry = VintageEntry(form, textvariable=self.quickbuy_window_ms, width=6)
        qw_entry.grid(row=r, column=5, sticky="w")
        ToolTip(qw_entry, "Time window (ms) after shop opens during which quick-buy is allowed")

        r += 1
        sep = tk.Frame(form, bg=TOKENS["borderMuted"], height=1)
        sep.grid(row=r, column=0, columnspan=6, sticky="ew", pady=4)

        r += 1
        self.autobuy_b = tk.BooleanVar(value=cfg.get("autobuy_after_b", False))
        self.autobuy_b.trace_add("write", self._auto_save)
        buy_ckbtn = tk.Checkbutton(form, text="Auto-buy after Recall (B)", variable=self.autobuy_b,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"])
        buy_ckbtn.grid(row=r, column=0, columnspan=2, sticky="w", pady=1)
        ToolTip(buy_ckbtn, "Auto-buy items from quick-buy slots when you press Recall (B)")

        VintageLabel(form, text="Delay (s):", font=FONT_SM).grid(row=r, column=2, sticky="w", padx=(6, 1))
        self.buy_delay_sec = tk.StringVar(value=cfg.get("buy_after_b_delay_sec", 5.5))
        self.buy_delay_sec.trace_add("write", self._auto_save)
        bd_entry = VintageEntry(form, textvariable=self.buy_delay_sec, width=5)
        bd_entry.grid(row=r, column=3, sticky="w")
        ToolTip(bd_entry, "How long after pressing B to send the quick-buy keys")

        r += 1
        self.buy_then_mid = tk.BooleanVar(value=cfg.get("autobuy_then_mid", False))
        self.buy_then_mid.trace_add("write", self._auto_save)
        mid_ckbtn = tk.Checkbutton(form, text="Click mid after buy", variable=self.buy_then_mid,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"],
                       selectcolor=TOKENS["compareBack"])
        mid_ckbtn.grid(row=r, column=0, columnspan=2, sticky="w", pady=1)
        ToolTip(mid_ckbtn, "After auto-buy, click the mid lane on minimap to return to lane")

        VintageLabel(form, text="Delay (s):", font=FONT_SM).grid(row=r, column=2, sticky="w", padx=(6, 1))
        self.buy_then_mid_delay = tk.StringVar(value=cfg.get("autobuy_then_mid_delay_sec", 0.5))
        self.buy_then_mid_delay.trace_add("write", self._auto_save)
        tm_entry = VintageEntry(form, textvariable=self.buy_then_mid_delay, width=5)
        tm_entry.grid(row=r, column=3, sticky="w")
        ToolTip(tm_entry, "Delay after buying before clicking mid on minimap")

        r += 1
        self.controlsend_z = tk.BooleanVar(value=cfg.get("controlsend_z", False))
        self.controlsend_z.trace_add("write", self._auto_save)
        cs_ckbtn = tk.Checkbutton(form, text="Background Z (ControlSend)", variable=self.controlsend_z,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"],
                       selectcolor=TOKENS["compareBack"])
        cs_ckbtn.grid(row=r, column=0, columnspan=3, sticky="w", pady=1)
        ToolTip(cs_ckbtn, "Send Z keys + minimap click directly to game window, works when Alt-Tabbed")

        btn_frame = tk.Frame(self, bg=TOKENS["background"])
        btn_frame.pack(fill="x", padx=4, pady=6)
        VintageButton(btn_frame, text="Reset", command=self.reset_defaults, width=8).pack(side="left")

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
                messagebox.showerror("Invalid value", str(e))
            return
        save_json(self.cfg_path, cfg)
