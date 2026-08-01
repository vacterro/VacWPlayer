import tkinter as tk
from tkinter import ttk, messagebox
import os, sys
import json
from theme import VintageSunken, VintageButton, VintageLabel, VintageEntry, TOKENS, FONT_MAIN, FONT_SM
from vintage_widgets import VintageWindowPicker
from process_runner import ProcessRunner

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
    for label, var, width in fields:
        VintageLabel(parent, text=label, font=FONT_SM).grid(row=row, column=col, sticky="w", padx=(0 if col == 0 else 6, 2), pady=1)
        VintageEntry(parent, textvariable=var, width=width).grid(row=row, column=col + 1, sticky="w", pady=1)
        col += 2

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
        cfg = load_json(self.cfg_path)
        self.buttons = [dict(b) for b in cfg["buttons"]]


        form = tk.Frame(self, bg=TOKENS["background"])
        form.pack(fill="x", padx=4, pady=(4, 2))

        mon_enabled = cfg.get("monitor_enabled", True)
        self.monitor_var = tk.BooleanVar(value=mon_enabled)
        self.chk_monitor = tk.Checkbutton(form, text="Enable Auto Continue Monitor", variable=self.monitor_var, 
                                          bg=TOKENS["background"], fg=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"],
                                          command=self.toggle_monitor)
        self.chk_monitor.pack(anchor="w", pady=1)
        
        self.status_var = tk.StringVar(value="Stopped")
        self.last_line_var = tk.StringVar(value="")
        
        status_frame = tk.Frame(form, bg=TOKENS["background"])
        status_frame.pack(fill="x", pady=1)
        tk.Label(status_frame, textvariable=self.status_var, width=10, bg=TOKENS["surfaceRaised"], fg=TOKENS["textPrimary"], font=FONT_MAIN).pack(side="left")
        tk.Label(status_frame, textvariable=self.last_line_var, bg=TOKENS["surfaceRaised"], fg=TOKENS["textMuted"], font=("Verdana", 8)).pack(side="left", padx=4, fill="x", expand=True)

        self.runner = ProcessRunner("autocontinue.py", self.status_var, self.last_line_var, self.monitor_var)

        tk.Frame(form, bg=TOKENS["borderMuted"], height=1).pack(fill="x", pady=3)

        config_frame = tk.Frame(self, bg=TOKENS["background"])
        config_frame.pack(fill="x", padx=4)

        self.window_picker = VintageWindowPicker(config_frame, "Window title", cfg["window_title"])
        self.window_picker.pack(fill="x", pady=1)

        params_frame = tk.Frame(config_frame, bg=TOKENS["background"])
        params_frame.pack(fill="x", pady=1)
        self.poll_interval = tk.StringVar(value=cfg["poll_interval_sec"])
        self.poll_interval.trace_add("write", self._auto_save)
        self.click_cooldown = tk.StringVar(value=cfg["click_cooldown_sec"])
        self.click_cooldown.trace_add("write", self._auto_save)
        grid_row(params_frame, 0, ("Poll interval (s)", self.poll_interval, 6), ("Click cooldown (s)", self.click_cooldown, 6))

        tk.Frame(config_frame, bg=TOKENS["borderMuted"], height=1).pack(fill="x", pady=3)

        body = tk.Frame(self, bg=TOKENS["background"])
        body.pack(fill="both", expand=True, padx=4)

        VintageLabel(body, text="Buttons it clicks:").pack(anchor="w")
        self.tree_frame = VintageSunken(body, bg_color=TOKENS["compareBack"])
        self.tree_frame.pack(fill="x", pady=2)

        self.tree = ttk.Treeview(self.tree_frame.content, columns=("threshold",),
                                 show="tree headings", height=5)
        style = ttk.Style()
        style.configure("Treeview", background=TOKENS["compareBack"], foreground=TOKENS["textPrimary"], fieldbackground=TOKENS["compareBack"], font=FONT_MAIN, borderwidth=0)
        style.configure("Treeview.Heading", background=TOKENS["surfaceRaised"], foreground=TOKENS["textPrimary"], font=FONT_MAIN)
        self.tree.heading("#0", text="Name")
        self.tree.heading("threshold", text="Match")
        self.tree.column("#0", width=330)
        self.tree.column("threshold", width=70)
        self.tree.pack(fill="x")

        btn_row = tk.Frame(body, bg=TOKENS["background"])
        btn_row.pack(fill="x", pady=2)
        VintageButton(btn_row, text="Remove", command=self.remove_button, width=8).pack(side="left")
        VintageButton(btn_row, text="⇄ Reset", command=self.reset_defaults, width=8).pack(side="left", padx=2)
        VintageButton(btn_row, text="Apply to Engine", command=self._trigger_apply, width=15).pack(side="right")

        VintageLabel(body,
                     text="These are calibrated already - it clicks Continue through the "
                          "post-game screens on its own. Nothing to set up.",
                     fg=TOKENS["textMuted"], font=FONT_SM,
                     wraplength=600, justify="left").pack(anchor="w", pady=6)

        self._refresh_tree()
        self._tick()
        if self.monitor_var.get():
            self.runner.start(["--replace"])

    def reset_defaults(self):
        import json
        try:
            with open(self.cfg_path) as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        self.poll_interval.set(str(cfg.get("poll_interval_sec", 0.6)))
        self.click_cooldown.set(str(cfg.get("click_cooldown_sec", 2.5)))
        self.window_picker.title_var.set(cfg.get("window_title", ""))
        self._auto_save()

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
            messagebox.showinfo("Remove", "Select a button in the list first.")
            return
        del self.buttons[int(sel[0])]
        self._refresh_tree()

    def save(self, silent=False):
        try:
            cfg = {
                "monitor_enabled": self.monitor_var.get(),
                "window_title": self.window_picker.get(),
                "poll_interval_sec": float(self.poll_interval.get()),
                "click_cooldown_sec": float(self.click_cooldown.get()),
                "buttons": self.buttons,
            }
        except ValueError as e:
            if silent:
                print(f"AutoContinue save skipped (invalid input): {e}", file=sys.stderr)
            else:
                messagebox.showerror("Invalid value", str(e))
            return
        save_json(self.cfg_path, cfg)
