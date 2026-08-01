import tkinter as tk
import os, sys
import json
from tkinter import messagebox
from theme import VintageButton, VintageLabel, VintageEntry, TOKENS, FONT_MAIN, FONT_SM
from vintage_widgets import VintageWindowPicker
from process_runner import ProcessRunner
from locales import Locale


class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        self.widget.bind("<Enter>", self._show, add="+")
        self.widget.bind("<Leave>", self._hide, add="+")

    def _show(self, event=None):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 2
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        bg = TOKENS["surfaceAlt"]
        fg = TOKENS["textPrimary"]
        lbl = tk.Label(self.tip, text=self.text, bg=bg, fg=fg,
                       font=("Verdana", 8), padx=4, pady=2,
                       borderwidth=1, relief="solid")
        lbl.pack()

    def _hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

def grid_row(parent, row, *fields):
    col = 0
    created = []
    for key, var, width in fields:
        lbl = VintageLabel(parent, text=Locale.tr(key), font=FONT_SM)
        lbl.grid(row=row, column=col, sticky="w", padx=(0 if col == 0 else 4, 1), pady=0)
        VintageEntry(parent, textvariable=var, width=width).grid(
            row=row, column=col + 1, sticky="w", pady=0)
        created.append(("lbl", lbl, key))
        col += 2
    return created


class DeathWatchTab(tk.Frame):
    """Death detection + actions on resurrect.

    Quickbuy / auto-buy after recall moved to BuyTab.
    """
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
        self._static_cfg = load_json(self.cfg_path)
        cfg = self._static_cfg

        form = tk.Frame(self, bg=TOKENS["background"])
        form.pack(fill="x", padx=4, pady=(2, 1))

        self._locale_widgets = []

        mon_enabled = cfg.get("monitor_enabled", True)
        self.monitor_var = tk.BooleanVar(value=mon_enabled)
        self.chk_monitor = tk.Checkbutton(form, text=Locale.tr("enable_death_monitor"), variable=self.monitor_var,
                                          bg=TOKENS["background"], fg=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"],
                                          command=self.toggle_monitor)
        self.chk_monitor.pack(anchor="w", pady=0)
        self._locale_widgets.append(("chk", self.chk_monitor, "enable_death_monitor"))
        ToolTip(self.chk_monitor, "Start/stop the death watch loop that detects death and resurrection in-game")

        self.status_var = tk.StringVar(value=Locale.tr("stopped"))
        self.last_line_var = tk.StringVar(value="")

        status_frame = tk.Frame(form, bg=TOKENS["background"])
        status_frame.pack(fill="x", pady=0)
        tk.Label(status_frame, textvariable=self.status_var, width=10, bg=TOKENS["surfaceRaised"], fg=TOKENS["textPrimary"], font=FONT_MAIN).pack(side="left")
        tk.Label(status_frame, textvariable=self.last_line_var, bg=TOKENS["surfaceRaised"], fg=TOKENS["textMuted"], font=("Verdana", 8)).pack(side="left", padx=4, fill="x", expand=True)

        self.runner = ProcessRunner("deathwatch.py", self.status_var, self.last_line_var, self.monitor_var)

        tk.Frame(form, bg=TOKENS["borderMuted"], height=1).pack(fill="x", pady=2)

        config_frame = tk.Frame(self, bg=TOKENS["background"])
        config_frame.pack(fill="x", padx=4)

        self.window_picker = VintageWindowPicker(config_frame, Locale.tr("window_title_lbl"), cfg["window_title"], label_key="window_title_lbl")
        self.window_picker.pack(fill="x", pady=0)
        self._locale_widgets.append(("picker", self.window_picker, "window_title_lbl"))
        ToolTip(self.window_picker, "Which game window title to monitor for death/revive events")

        params_frame1 = tk.Frame(config_frame, bg=TOKENS["background"])
        params_frame1.pack(fill="x", pady=0)
        self.poll_interval = tk.StringVar(value=cfg["poll_interval_sec"])
        self.poll_interval.trace_add("write", self._auto_save)
        self.shop_buffer = tk.StringVar(value=cfg["shop_buffer_sec"])
        self.shop_buffer.trace_add("write", self._auto_save)
        self.restore_buffer = tk.StringVar(value=cfg["restore_buffer_sec"])
        self.restore_buffer.trace_add("write", self._auto_save)
        self.match_threshold = tk.StringVar(value=cfg["match_threshold"])
        self.match_threshold.trace_add("write", self._auto_save)
        self._locale_widgets.extend(grid_row(params_frame1, 0,
                 ("poll_interval_s", self.poll_interval, 6),
                 ("shop_buffer_s", self.shop_buffer, 6),
                 ("restore_buffer_s", self.restore_buffer, 6)))

        params_frame2 = tk.Frame(config_frame, bg=TOKENS["background"])
        params_frame2.pack(fill="x", pady=0)
        self.max_wait = tk.StringVar(value=cfg["max_death_wait_sec"])
        self.max_wait.trace_add("write", self._auto_save)
        self.pedal_block_sec = tk.StringVar(value=cfg.get("pedal_block_sec", 0))
        self.pedal_block_sec.trace_add("write", self._auto_save)
        self.blocked_keys = tk.StringVar(value=",".join(cfg.get("blocked_keys", ["F13","F14","F15"])))
        self.blocked_keys.trace_add("write", self._auto_save)
        self._locale_widgets.extend(grid_row(params_frame2, 0,
                 ("max_wait_s", self.max_wait, 6),
                 ("block_keys_lbl", self.blocked_keys, 16)))
        params_frame3 = tk.Frame(config_frame, bg=TOKENS["background"])
        params_frame3.pack(fill="x", pady=0)
        self._locale_widgets.extend(grid_row(params_frame3, 0,
                 ("block_duration_s", self.pedal_block_sec, 6)))

        sep = tk.Frame(config_frame, bg=TOKENS["borderMuted"], height=1)
        sep.pack(fill="x", pady=3)

        actions = tk.Frame(config_frame, bg=TOKENS["background"])
        actions.pack(fill="x", pady=0)
        self.switch_to_work = tk.BooleanVar(value=cfg.get("switch_to_work_window", False))
        self.switch_to_work.trace_add("write", self._auto_save)
        sw_btn = tk.Checkbutton(actions, text=Locale.tr("switch_work_lbl"), variable=self.switch_to_work,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"])
        sw_btn.pack(side="left")
        self._locale_widgets.append(("chk", sw_btn, "switch_work_lbl"))
        ToolTip(sw_btn, "While dead, auto-switch to the work window (browser/notes) to keep you productive")

        self.click_mid = tk.BooleanVar(value=cfg.get("click_mid_on_resurrect", False))
        self.click_mid.trace_add("write", self._auto_save)
        cm_btn = tk.Checkbutton(actions, text=Locale.tr("click_mid_lbl"), variable=self.click_mid,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"])
        cm_btn.pack(side="left", padx=(6, 0))
        self._locale_widgets.append(("chk", cm_btn, "click_mid_lbl"))
        ToolTip(cm_btn, "When you resurrect, click the mid lane on minimap to go back to lane immediately")

        self.lock_window = tk.BooleanVar(value=cfg.get("lock_window_resurrect", False))
        self.lock_window.trace_add("write", self._auto_save)
        lw_btn = tk.Checkbutton(actions, text=Locale.tr("lock_window_lbl"), variable=self.lock_window,
                       bg=TOKENS["background"], fg=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"])
        lw_btn.pack(side="left", padx=(6, 0))
        self._locale_widgets.append(("chk", lw_btn, "lock_window_lbl"))
        ToolTip(lw_btn, "Lock/unlock current game window so minimap clicks don't lose focus (Ctrl+Shift+F8 toggle)")

        self.work_window = VintageWindowPicker(config_frame, Locale.tr("work_window_lbl"), cfg.get("work_window_title", ""), label_key="work_window_lbl")
        self.work_window.pack(fill="x", pady=0)
        self._locale_widgets.append(("picker", self.work_window, "work_window_lbl"))
        ToolTip(self.work_window, "Window to auto-switch to while dead (e.g. browser, notes, YouTube)")

        tk.Frame(config_frame, bg=TOKENS["borderMuted"], height=1).pack(fill="x", pady=3)

        btn_frame = tk.Frame(config_frame, bg=TOKENS["background"])
        btn_frame.pack(fill="x", pady=2)
        self._btn_apply = VintageButton(btn_frame, text=Locale.tr("apply"), command=self._trigger_apply, width=8)
        self._btn_apply.pack(side="left")
        self._locale_widgets.append(("btn", self._btn_apply, "apply"))
        self._btn_reset = VintageButton(btn_frame, text=Locale.tr("reset_lbl"), command=self.reset_defaults, width=8)
        self._btn_reset.pack(side="left", padx=2)
        self._locale_widgets.append(("btn", self._btn_reset, "reset_lbl"))

        self._tick()
        if self.monitor_var.get():
            self.runner.start(["--replace"])

    def apply_locale(self):
        for kind, widget, key in self._locale_widgets:
            if kind == "lbl":
                widget.config(text=Locale.tr(key))
            elif kind == "btn":
                widget.label.config(text=Locale.tr(key))
            elif kind == "chk":
                widget.config(text=Locale.tr(key))
            elif kind == "picker":
                widget.apply_locale()

    def reset_defaults(self):
        cfg = load_json(self.cfg_path)
        self.poll_interval.set(str(cfg.get("poll_interval_sec", 0.4)))
        self.shop_buffer.set(str(cfg.get("shop_buffer_sec", 0.0)))
        self.restore_buffer.set(str(cfg.get("restore_buffer_sec", 2.0)))
        self.max_wait.set(str(cfg.get("max_death_wait_sec", 90.0)))
        self.pedal_block_sec.set(str(cfg.get("pedal_block_sec", 0)))
        self.blocked_keys.set(",".join(cfg.get("blocked_keys", ["F13","F14","F15"])))
        self.match_threshold.set(str(cfg.get("match_threshold", 0.75)))
        self.switch_to_work.set(cfg.get("switch_to_work_window", False))
        self.click_mid.set(cfg.get("click_mid_on_resurrect", False))
        self.lock_window.set(cfg.get("lock_window_resurrect", False))
        self.window_picker.title_var.set(cfg.get("window_title", ""))
        self.work_window.title_var.set(cfg.get("work_window_title", ""))

    def _trigger_apply(self):
        self.save()
        if self.monitor_var.get():
            self.runner.start(["--replace"])
        try:
            self.event_generate("<<ApplyStart>>")
        except tk.TclError:
            pass

    def toggle_monitor(self):
        if self.monitor_var.get():
            self.save()
            self.runner.start(["--replace"])
        else:
            self.runner.stop()
            self.save_monitor_state()

    def save_monitor_state(self):
        cfg = load_json(self.cfg_path)
        cfg["monitor_enabled"] = self.monitor_var.get()
        save_json(self.cfg_path, cfg)

    def stop_all(self):
        self.runner.stop()
        try:
            self.monitor_var.set(False)
        except Exception:
            pass

    def _tick(self):
        if not self.winfo_exists():
            return
        try:
            self.runner.poll_log()
        except Exception as e:
            print(f"death_tab _tick: poll_log error: {e}", file=sys.stderr)
        self._tick_id = self.after(1000, self._tick)

    def save(self, silent=False):
        try:
            cfg = load_json(self.cfg_path)
            cfg["monitor_enabled"] = self.monitor_var.get()
            cfg["window_title"] = self.window_picker.get()
            cfg["poll_interval_sec"] = float(self.poll_interval.get())
            cfg["shop_buffer_sec"] = float(self.shop_buffer.get())
            cfg["restore_buffer_sec"] = float(self.restore_buffer.get())
            cfg["match_threshold"] = float(self.match_threshold.get())
            cfg["death_label_region"] = self._static_cfg["death_label_region"]
            cfg["timer_digits_region"] = self._static_cfg["timer_digits_region"]
            cfg["death_label_template"] = self._static_cfg["death_label_template"]
            cfg["digit_templates_dir"] = self._static_cfg["digit_templates_dir"]
            cfg["max_death_wait_sec"] = float(self.max_wait.get())
            raw = self.blocked_keys.get()
            cfg["blocked_keys"] = [k.strip().upper() for k in raw.split(",") if k.strip()]
            cfg["pedal_block_sec"] = float(self.pedal_block_sec.get())
            cfg["switch_to_work_window"] = self.switch_to_work.get()
            cfg["work_window_title"] = self.work_window.get()
            cfg["click_mid_on_resurrect"] = self.click_mid.get()
            cfg["lock_window_resurrect"] = self.lock_window.get()
        except ValueError as e:
            if silent:
                print(f"DeathWatch save skipped (invalid input): {e}", file=sys.stderr)
            else:
                messagebox.showerror(Locale.tr("invalid_value"), str(e))
            return
        save_json(self.cfg_path, cfg)
