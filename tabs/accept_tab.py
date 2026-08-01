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


class AcceptTab(tk.Frame):
    CONFIG_NAME = "accept_config.json"

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

        form = tk.Frame(self, bg=TOKENS["background"])
        form.pack(fill="x", padx=4, pady=(4, 2))

        mon_enabled = cfg.get("monitor_enabled", False)
        self.monitor_var = tk.BooleanVar(value=mon_enabled)
        self.chk_monitor = tk.Checkbutton(
            form, text="Enable Auto-Accept Monitor", variable=self.monitor_var,
            bg=TOKENS["background"], fg=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"],
            command=self.toggle_monitor)
        self.chk_monitor.pack(anchor="w", pady=1)

        self.status_var = tk.StringVar(value="Stopped")
        self.last_line_var = tk.StringVar(value="")

        status_frame = tk.Frame(form, bg=TOKENS["background"])
        status_frame.pack(fill="x", pady=1)
        tk.Label(status_frame, textvariable=self.status_var, width=10,
                 bg=TOKENS["surfaceRaised"], fg=TOKENS["textPrimary"], font=FONT_MAIN).pack(side="left")
        tk.Label(status_frame, textvariable=self.last_line_var,
                 bg=TOKENS["surfaceRaised"], fg=TOKENS["textMuted"], font=("Verdana", 8)).pack(side="left", padx=4, fill="x", expand=True)

        self.runner = ProcessRunner("accept.py", self.status_var, self.last_line_var, self.monitor_var)

        tk.Frame(form, bg=TOKENS["borderMuted"], height=1).pack(fill="x", pady=3)

        config_frame = tk.Frame(self, bg=TOKENS["background"])
        config_frame.pack(fill="x", padx=4)

        self.window_picker = VintageWindowPicker(config_frame, "Window title", cfg["window_title"])
        self.window_picker.pack(fill="x", pady=1)

        params_frame = tk.Frame(config_frame, bg=TOKENS["background"])
        params_frame.pack(fill="x", pady=1)
        self.poll_interval = tk.StringVar(value=str(cfg.get("poll_interval_sec", 1.0)))
        self.poll_interval.trace_add("write", self._auto_save)
        self.click_cooldown = tk.StringVar(value=str(cfg.get("click_cooldown_sec", 3.0)))
        self.click_cooldown.trace_add("write", self._auto_save)

        VintageLabel(params_frame, text="Poll (s):", font=FONT_SM).pack(side="left")
        VintageEntry(params_frame, textvariable=self.poll_interval, width=6).pack(side="left", padx=2)
        VintageLabel(params_frame, text="Cooldown (s):", font=FONT_SM).pack(side="left", padx=(6, 0))
        VintageEntry(params_frame, textvariable=self.click_cooldown, width=6).pack(side="left", padx=2)

        tk.Frame(config_frame, bg=TOKENS["borderMuted"], height=1).pack(fill="x", pady=3)

        templates_frame = tk.Frame(self, bg=TOKENS["background"])
        templates_frame.pack(fill="both", expand=True, padx=4)

        VintageLabel(templates_frame, text="Button templates:").pack(anchor="w")
        self.tree_frame = VintageSunken(templates_frame, bg_color=TOKENS["compareBack"])
        self.tree_frame.pack(fill="x", pady=2)

        self.tree = ttk.Treeview(self.tree_frame.content, columns=("file", "threshold"),
                                 show="tree headings", height=4)
        style = ttk.Style()
        style.configure("Treeview", background=TOKENS["compareBack"],
                        foreground=TOKENS["textPrimary"], fieldbackground=TOKENS["compareBack"],
                        font=FONT_MAIN, borderwidth=0)
        style.configure("Treeview.Heading", background=TOKENS["surfaceRaised"],
                        foreground=TOKENS["textPrimary"], font=FONT_MAIN)
        self.tree.heading("#0", text="Name")
        self.tree.heading("file", text="File")
        self.tree.heading("threshold", text="Match")
        self.tree.column("#0", width=160)
        self.tree.column("file", width=200)
        self.tree.column("threshold", width=60)
        self.tree.pack(fill="x")

        btn_row = tk.Frame(templates_frame, bg=TOKENS["background"])
        btn_row.pack(fill="x", pady=2)
        VintageButton(btn_row, text="Add template", command=self.add_template, width=12).pack(side="left")
        VintageButton(btn_row, text="Remove", command=self.remove_template, width=8).pack(side="left", padx=2)
        VintageButton(btn_row, text="Apply", command=self._trigger_apply, width=8).pack(side="right")

        msg = ("Place cropped button PNGs in templates/ folder, then add them here.\n"
               "Poller uses PrintWindow — detects button even when game is behind other windows.")
        VintageLabel(templates_frame, text=msg, fg=TOKENS["textMuted"], font=FONT_SM,
                     wraplength=600, justify="left").pack(anchor="w", pady=6)

        self._refresh_tree()
        self._tick()
        if self.monitor_var.get():
            self.runner.start(["--replace"])

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        cfg = load_json(self.cfg_path)
        for i, t in enumerate(cfg.get("templates", [])):
            self.tree.insert("", "end", iid=str(i),
                             text=t.get("name", "?"),
                             values=(t.get("file", ""), t.get("threshold", "")))

    def add_template(self):
        from tkinter import filedialog, simpledialog
        path = filedialog.askopenfilename(
            initialdir=os.path.join(BASE, "templates"),
            title="Select button template PNG",
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")])
        if not path:
            return
        rel = os.path.relpath(path, BASE)
        name = simpledialog.askstring("Template name", "Name:", initialvalue=os.path.splitext(os.path.basename(path))[0])
        if not name:
            return
        cfg = load_json(self.cfg_path)
        cfg.setdefault("templates", []).append({
            "name": name,
            "file": rel,
            "threshold": 0.8,
        })
        save_json(self.cfg_path, cfg)
        self._refresh_tree()

    def remove_template(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Remove", "Select a template first.")
            return
        idx = int(sel[0])
        cfg = load_json(self.cfg_path)
        templates = cfg.get("templates", [])
        if 0 <= idx < len(templates):
            del templates[idx]
            cfg["templates"] = templates
            save_json(self.cfg_path, cfg)
            self._refresh_tree()

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

    def _trigger_apply(self):
        self.save()
        if self.monitor_var.get():
            self.runner.start(["--replace"])
        try:
            self.event_generate("<<ApplyStart>>")
        except tk.TclError:
            pass

    def _tick(self):
        if not self.winfo_exists():
            return
        try:
            self.runner.poll_log()
        except Exception as e:
            print(f"accept_tab _tick: poll_log error: {e}", file=sys.stderr)
        self._tick_id = self.after(1000, self._tick)

    def save(self, silent=False):
        try:
            cfg = load_json(self.cfg_path)
            cfg["monitor_enabled"] = self.monitor_var.get()
            cfg["window_title"] = self.window_picker.get()
            cfg["poll_interval_sec"] = float(self.poll_interval.get())
            cfg["click_cooldown_sec"] = float(self.click_cooldown.get())
        except ValueError as e:
            if silent:
                print(f"Accept save skipped (invalid input): {e}", file=sys.stderr)
            else:
                messagebox.showerror("Invalid value", str(e))
            return
        save_json(self.cfg_path, cfg)
