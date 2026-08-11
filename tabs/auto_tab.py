import copy
import tkinter as tk
from tkinter import ttk, messagebox
import os, sys
from theme import VintageSunken, VintageButton, VintageLabel, TOKENS, FONT_MAIN, FONT_SM
from vintage_widgets import VintageWindowPicker, grid_row
from process_runner import ProcessRunner
from locales import Locale
from tabs.tab_config import load_json, update_json
from engine_config import canonical_default

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class AutoContinueTab(tk.Frame):
    CONFIG_NAME = "autocontinue_config.json"

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
        cfg = load_json(self.cfg_path, self.CONFIG_NAME)
        self.buttons = [dict(b) for b in cfg.get("buttons", canonical_default(self.CONFIG_NAME)["buttons"])]


        form = tk.Frame(self, bg=TOKENS["background"])
        form.pack(fill="x", padx=4, pady=(4, 2))

        self._locale_widgets = []

        mon_enabled = cfg.get("monitor_enabled", True)
        self.monitor_var = tk.BooleanVar(value=mon_enabled)
        self.chk_monitor = tk.Checkbutton(form, text=Locale.tr("enable_auto_monitor"), variable=self.monitor_var, 
                                          bg=TOKENS["background"], fg=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"],
                                          command=self.toggle_monitor)
        self.chk_monitor.pack(anchor="w", pady=1)
        self._locale_widgets.append(("chk", self.chk_monitor, "enable_auto_monitor"))
        
        self.status_var = tk.StringVar(value=Locale.tr("stopped"))
        self.last_line_var = tk.StringVar(value="")
        
        status_frame = tk.Frame(form, bg=TOKENS["background"])
        status_frame.pack(fill="x", pady=1)
        tk.Label(status_frame, textvariable=self.status_var, width=10, bg=TOKENS["surfaceRaised"], fg=TOKENS["textPrimary"], font=FONT_MAIN).pack(side="left")
        tk.Label(status_frame, textvariable=self.last_line_var, bg=TOKENS["surfaceRaised"], fg=TOKENS["textMuted"], font=("Verdana", 8)).pack(side="left", padx=4, fill="x", expand=True)

        self.runner = ProcessRunner("autocontinue.py", self.status_var, self.last_line_var, self.monitor_var)

        tk.Frame(form, bg=TOKENS["borderMuted"], height=1).pack(fill="x", pady=3)

        config_frame = tk.Frame(self, bg=TOKENS["background"])
        config_frame.pack(fill="x", padx=4)

        self.window_picker = VintageWindowPicker(config_frame, Locale.tr("window_title_lbl"), cfg.get("window_title", ""), label_key="window_title_lbl")
        self.window_picker.pack(fill="x", pady=1)
        self._locale_widgets.append(("picker", self.window_picker, "window_title_lbl"))

        params_frame = tk.Frame(config_frame, bg=TOKENS["background"])
        params_frame.pack(fill="x", pady=1)
        self.poll_interval = tk.StringVar(value=cfg.get("poll_interval_sec", 0.6))
        self.poll_interval.trace_add("write", self._auto_save)
        self.click_cooldown = tk.StringVar(value=cfg.get("click_cooldown_sec", 2.5))
        self.click_cooldown.trace_add("write", self._auto_save)
        self._locale_widgets.extend(grid_row(params_frame, 0, ("poll_interval_s", self.poll_interval, 6), ("click_cooldown_s", self.click_cooldown, 6), pad=(6, 2), pady=1))

        tk.Frame(config_frame, bg=TOKENS["borderMuted"], height=1).pack(fill="x", pady=3)

        body = tk.Frame(self, bg=TOKENS["background"])
        body.pack(fill="both", expand=True, padx=4)

        self._lbl_buttons = VintageLabel(body, text=Locale.tr("buttons_title"))
        self._lbl_buttons.pack(anchor="w")
        self._locale_widgets.append(("lbl", self._lbl_buttons, "buttons_title"))
        self.tree_frame = VintageSunken(body, bg_color=TOKENS["compareBack"])
        self.tree_frame.pack(fill="x", pady=2)

        self.tree = ttk.Treeview(self.tree_frame.content, columns=("threshold",),
                                 show="tree headings", height=5)
        style = ttk.Style()
        style.configure("Treeview", background=TOKENS["compareBack"], foreground=TOKENS["textPrimary"], fieldbackground=TOKENS["compareBack"], font=FONT_MAIN, borderwidth=0)
        style.configure("Treeview.Heading", background=TOKENS["surfaceRaised"], foreground=TOKENS["textPrimary"], font=FONT_MAIN)
        self.tree.heading("#0", text=Locale.tr("name_lbl"))
        self.tree.heading("threshold", text=Locale.tr("match_lbl"))
        self.tree.column("#0", width=330)
        self.tree.column("threshold", width=70)
        self.tree.pack(fill="x")

        btn_row = tk.Frame(body, bg=TOKENS["background"])
        btn_row.pack(fill="x", pady=2)
        self._btn_remove = VintageButton(btn_row, text=Locale.tr("remove_lbl"), command=self.remove_button, width=8)
        self._btn_remove.pack(side="left")
        self._locale_widgets.append(("btn", self._btn_remove, "remove_lbl"))
        self._btn_reset = VintageButton(btn_row, text=Locale.tr("reset_lbl"), command=self.reset_defaults, width=8)
        self._btn_reset.pack(side="left", padx=2)
        self._locale_widgets.append(("btn", self._btn_reset, "reset_lbl"))
        self._btn_apply = VintageButton(btn_row, text=Locale.tr("apply_to_engine"), command=self._trigger_apply, width=15)
        self._btn_apply.pack(side="right")
        self._locale_widgets.append(("btn", self._btn_apply, "apply_to_engine"))

        self._lbl_note = VintageLabel(body,
                     text=Locale.tr("auto_note"),
                     fg=TOKENS["textMuted"], font=FONT_SM,
                     wraplength=600, justify="left")
        self._lbl_note.pack(anchor="w", pady=6)
        self._locale_widgets.append(("lbl", self._lbl_note, "auto_note"))

        self._refresh_tree()
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
        self.tree.heading("#0", text=Locale.tr("name_lbl"))
        self.tree.heading("threshold", text=Locale.tr("match_lbl"))

    def reset_defaults(self):
        d = canonical_default(self.CONFIG_NAME)
        self.poll_interval.set(str(d["poll_interval_sec"]))
        self.click_cooldown.set(str(d["click_cooldown_sec"]))
        self.window_picker.title_var.set(d["window_title"])
        # Undo removes: restore the canonical buttons (deep-copied so the live
        # list never aliases the canonical source's region lists, T-141).
        self.buttons = copy.deepcopy(d["buttons"])
        self._refresh_tree()
        self._auto_save()

    def _trigger_apply(self):
        if not self.save():
            return  # nothing was persisted - don't touch the engine (T-142)
        if self.monitor_var.get():
            self.runner.start(["--replace"])
        try:
            self.event_generate("<<ApplyStart>>")
        except tk.TclError:
            pass

    def toggle_monitor(self):
        if self.monitor_var.get():
            if not self.save():
                self.monitor_var.set(False)  # persistence failed - don't start
                return
            self.runner.start(["--replace"])
        else:
            self.runner.stop()
            if not self.save_monitor_state():
                self.monitor_var.set(True)  # disk still says enabled - restore

    def save_monitor_state(self):
        return update_json(self.cfg_path,
                    lambda c: c.__setitem__("monitor_enabled", self.monitor_var.get()),
                    canonical_default(self.CONFIG_NAME), config_name=self.CONFIG_NAME)

    def stop_all(self):
        self.runner.stop()
        try:
            self.monitor_var.set(False)
        except Exception as e:
            print("auto_tab: reset monitor toggle failed: %s" % e, file=sys.stderr)

    def _tick(self):
        if not self.winfo_exists():
            return
        try:
            self.runner.poll_log()
        except Exception as e:
            print(f"auto_tab _tick: poll_log error: {e}", file=sys.stderr)
        self._tick_id = self.after(1000, self._tick)

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, b in enumerate(self.buttons):
            self.tree.insert("", "end", iid=str(i), text=b.get("name", "?"),
                             values=(b.get("threshold", ""),))

    def remove_button(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(Locale.tr("remove_lbl"), Locale.tr("remove_need"))
            return
        del self.buttons[int(sel[0])]
        self._refresh_tree()

    def save(self, silent=False):
        def mutate(cfg):
            cfg["monitor_enabled"] = self.monitor_var.get()
            cfg["window_title"] = self.window_picker.get()
            cfg["poll_interval_sec"] = float(self.poll_interval.get())
            cfg["click_cooldown_sec"] = float(self.click_cooldown.get())
            cfg["buttons"] = [dict(b) for b in self.buttons]
        try:
            ok = update_json(self.cfg_path, mutate,
                             canonical_default(self.CONFIG_NAME), config_name=self.CONFIG_NAME)
        except ValueError as e:
            if silent:
                print(f"AutoContinue save skipped (invalid input): {e}", file=sys.stderr)
            else:
                messagebox.showerror(Locale.tr("invalid_value"), str(e))
            return
        return ok
