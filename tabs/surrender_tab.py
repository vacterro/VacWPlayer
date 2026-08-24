import tkinter as tk
from tkinter import ttk, messagebox
import os
import sys
from theme import VintageSunken, VintageButton, VintageLabel, VintageEntry, TOKENS, FONT_MAIN, FONT_SM
from vintage_widgets import VintageWindowPicker
from process_runner import ProcessRunner
from locales import Locale
from tabs.tab_config import load_json, update_json, resolve_monitor_state, remove_template_by_identity
from engine_config import canonical_default

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


SURRENDER_DEFAULTS = canonical_default("surrender_config.json")


class SurrenderTab(tk.Frame):
    CONFIG_NAME = "surrender_config.json"

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

        # T-CORE-012: materialize a missing canonical file before honoring the
        # monitor flag. If that materialization FAILS, the file stays absent and
        # the config is NOT usable - the engine child must never be launched
        # against a missing/unvalidated file (its load_config() would FATAL).
        if not os.path.exists(self.cfg_path):
            update_json(self.cfg_path, lambda c: None,
                        canonical_default(self.CONFIG_NAME), config_name=self.CONFIG_NAME)
        cfg, cfg_status = load_json(self.cfg_path, self.CONFIG_NAME)

        form = tk.Frame(self, bg=TOKENS["background"])
        form.pack(fill="x", padx=4, pady=(4, 2))

        self._locale_widgets = []

        # CORE-012: resolve the monitor flag + usability from the load status.
        # Only "ok" (present + validated, or successfully materialized)
        # authorizes the engine child to start; "missing" after a failed
        # materialization forces OFF and marks the config NOT usable.
        mon_enabled, self._config_usable = resolve_monitor_state(
            cfg_status, cfg,
            canonical_default(self.CONFIG_NAME).get("monitor_enabled", False))
        self.monitor_var = tk.BooleanVar(value=mon_enabled)
        self.monitor_var.trace_add("write", self._auto_save)
        self.chk_monitor = tk.Checkbutton(
            form, text=Locale.tr("enable_surrender_monitor"), variable=self.monitor_var,
            bg=TOKENS["background"], fg=TOKENS["textPrimary"], selectcolor=TOKENS["compareBack"],
            command=self.toggle_monitor)
        self.chk_monitor.pack(anchor="w", pady=1)
        self._locale_widgets.append(("chk", self.chk_monitor, "enable_surrender_monitor"))

        self.status_var = tk.StringVar(value=Locale.tr("stopped"))
        self.last_line_var = tk.StringVar(value="")

        status_frame = tk.Frame(form, bg=TOKENS["background"])
        status_frame.pack(fill="x", pady=1)
        tk.Label(status_frame, textvariable=self.status_var, width=10,
                 bg=TOKENS["surfaceRaised"], fg=TOKENS["textPrimary"], font=FONT_MAIN).pack(side="left")
        tk.Label(status_frame, textvariable=self.last_line_var,
                 bg=TOKENS["surfaceRaised"], fg=TOKENS["textMuted"], font=("Verdana", 8)).pack(side="left", padx=4, fill="x", expand=True)

        self.runner = ProcessRunner("surrender.py", self.status_var, self.last_line_var, self.monitor_var)

        tk.Frame(form, bg=TOKENS["borderMuted"], height=1).pack(fill="x", pady=3)

        config_frame = tk.Frame(self, bg=TOKENS["background"])
        config_frame.pack(fill="x", padx=4)

        self.window_picker = VintageWindowPicker(config_frame, Locale.tr("window_title_lbl"), cfg.get("window_title", ""), label_key="window_title_lbl")
        self.window_picker.pack(fill="x", pady=1)
        self._locale_widgets.append(("picker", self.window_picker, "window_title_lbl"))

        params_frame = tk.Frame(config_frame, bg=TOKENS["background"])
        params_frame.pack(fill="x", pady=1)
        self.poll_interval = tk.StringVar(value=str(cfg.get("poll_interval_sec", 5.0)))
        self.poll_interval.trace_add("write", self._auto_save)
        self.click_cooldown = tk.StringVar(value=str(cfg.get("click_cooldown_sec", 3.0)))
        self.click_cooldown.trace_add("write", self._auto_save)

        self._lbl_poll = VintageLabel(params_frame, text=Locale.tr("poll_s_lbl"), font=FONT_SM)
        self._lbl_poll.pack(side="left")
        self._locale_widgets.append(("lbl", self._lbl_poll, "poll_s_lbl"))
        VintageEntry(params_frame, textvariable=self.poll_interval, width=6).pack(side="left", padx=2)
        self._lbl_cooldown = VintageLabel(params_frame, text=Locale.tr("cooldown_s_lbl"), font=FONT_SM)
        self._lbl_cooldown.pack(side="left", padx=(6, 0))
        self._locale_widgets.append(("lbl", self._lbl_cooldown, "cooldown_s_lbl"))
        VintageEntry(params_frame, textvariable=self.click_cooldown, width=6).pack(side="left", padx=2)

        tk.Frame(config_frame, bg=TOKENS["borderMuted"], height=1).pack(fill="x", pady=3)

        mode_frame = tk.Frame(config_frame, bg=TOKENS["background"])
        mode_frame.pack(fill="x", pady=1)
        self.auto_accept_var = tk.BooleanVar(value=cfg.get("auto_accept", True))
        self.auto_accept_var.trace_add("write", self._auto_save)
        self._lbl_mode = VintageLabel(mode_frame, text=Locale.tr("surrender_mode"), font=FONT_SM)
        self._lbl_mode.pack(side="left")
        self._locale_widgets.append(("lbl", self._lbl_mode, "surrender_mode"))
        self.chk_accept = tk.Checkbutton(mode_frame, text=Locale.tr("surrender_auto_accept"), 
                                        variable=self.auto_accept_var,
                                        bg=TOKENS["background"], fg=TOKENS["textPrimary"],
                                        selectcolor=TOKENS["compareBack"],
                                        font=FONT_SM, highlightthickness=0, bd=0)
        self.chk_accept.pack(side="left", padx=2)
        self._locale_widgets.append(("chk", self.chk_accept, "surrender_auto_accept"))

        tk.Frame(config_frame, bg=TOKENS["borderMuted"], height=1).pack(fill="x", pady=3)

        templates_frame = tk.Frame(self, bg=TOKENS["background"])
        templates_frame.pack(fill="both", expand=True, padx=4)

        self._lbl_templates = VintageLabel(templates_frame, text=Locale.tr("templates_title"))
        self._lbl_templates.pack(anchor="w")
        self._locale_widgets.append(("lbl", self._lbl_templates, "templates_title"))
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
        self.tree.heading("#0", text=Locale.tr("name_lbl"))
        self.tree.heading("file", text=Locale.tr("file_lbl"))
        self.tree.heading("threshold", text=Locale.tr("match_lbl"))
        self.tree.column("#0", width=160)
        self.tree.column("file", width=200)
        self.tree.column("threshold", width=60)
        self.tree.pack(fill="x")

        btn_row = tk.Frame(templates_frame, bg=TOKENS["background"])
        btn_row.pack(fill="x", pady=2)
        self._btn_add = VintageButton(btn_row, text=Locale.tr("add_template"), command=self.add_template, width=12)
        self._btn_add.pack(side="left")
        self._locale_widgets.append(("btn", self._btn_add, "add_template"))
        self._btn_remove = VintageButton(btn_row, text=Locale.tr("remove_lbl"), command=self.remove_template, width=8)
        self._btn_remove.pack(side="left", padx=2)
        self._locale_widgets.append(("btn", self._btn_remove, "remove_lbl"))
        self._btn_apply = VintageButton(btn_row, text=Locale.tr("apply"), command=self._trigger_apply, width=8)
        self._btn_apply.pack(side="right")
        self._locale_widgets.append(("btn", self._btn_apply, "apply"))

        self._lbl_note = VintageLabel(templates_frame, text=Locale.tr("surrender_note"), fg=TOKENS["textMuted"], font=FONT_SM,
                     wraplength=600, justify="left")
        self._lbl_note.pack(anchor="w", pady=6)
        self._locale_widgets.append(("lbl", self._lbl_note, "surrender_note"))

        self._refresh_tree()
        self._tick()
        if self.monitor_var.get():
            self._safe_start()

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
        self.tree.heading("file", text=Locale.tr("file_lbl"))
        self.tree.heading("threshold", text=Locale.tr("match_lbl"))

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._row_identities = {}
        cfg, _status = load_json(self.cfg_path, self.CONFIG_NAME)
        for i, t in enumerate(cfg.get("templates", [])):
            iid = str(i)
            self.tree.insert("", "end", iid=iid,
                             text=t.get("name", "?"),
                             values=(t.get("file", ""), t.get("threshold", "")))
            # W2-006: bind the row to a VALUE identity (full dict snapshot),
            # never to its positional index, so a concurrent external config
            # change cannot make us delete the wrong item later.
            self._row_identities[iid] = dict(t)

    def add_template(self):
        from tkinter import filedialog, simpledialog
        path = filedialog.askopenfilename(
            initialdir=os.path.join(BASE, "templates"),
            title=Locale.tr("select_png_title"),
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")])
        if not path:
            return
        # W2-008: handle cross-drive relpath gracefully.
        try:
            rel = os.path.relpath(path, BASE)
        except ValueError:
            rel = os.path.normpath(path)
        name = simpledialog.askstring(Locale.tr("template_name_title"), Locale.tr("template_name"),
                                      initialvalue=os.path.splitext(os.path.basename(path))[0])
        if not name:
            return
        action = simpledialog.askstring(
            Locale.tr("template_action_title", fallback="Action"),
            Locale.tr("template_action", fallback="Action (accept/decline)"),
            initialvalue="accept")
        if action not in ("accept", "decline"):
            messagebox.showerror(
                Locale.tr("invalid_value"),
                Locale.tr("template_action_invalid", fallback="Action must be 'accept' or 'decline'"))
            return
        update_json(self.cfg_path, lambda c: c["templates"].append({
            "name": name,
            "file": rel,
            "threshold": 0.75,
            "action": action,
        }), canonical_default(self.CONFIG_NAME), config_name=self.CONFIG_NAME)
        self._refresh_tree()

    def remove_template(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(Locale.tr("remove_need"), Locale.tr("remove_need"))
            return
        iid = sel[0]
        identity = self._row_identities.get(iid)
        if identity is None:
            # Row identity went stale (e.g. external change between render and
            # click). Refuse to guess by position - just resync the view.
            self._refresh_tree()
            return
        removed = {"ok": False}
        update_json(self.cfg_path,
                    lambda c: removed.__setitem__(
                        "ok", remove_template_by_identity(c.get("templates", []), identity)),
                    canonical_default(self.CONFIG_NAME), config_name=self.CONFIG_NAME)
        if not removed["ok"]:
            messagebox.showinfo(
                Locale.tr("remove_need"),
                Locale.tr("remove_not_found",
                          fallback="Template no longer present; list refreshed."))
        self._refresh_tree()

    def _safe_start(self):
        """CORE-012 gate: only launch the engine child when the on-disk config
        is present and validated (self._config_usable). Returns the start()
        result, or False when the config is not usable (no child is spawned)."""
        if not self._config_usable:
            self.status_var.set(Locale.tr("config_not_ready",
                                          fallback="Config not ready"))
            self.monitor_var.set(False)
            return False
        return self.runner.start(["--replace"])

    def _trigger_apply(self):
        if not self.save():
            return  # nothing was persisted - don't touch the engine (T-142)
        # A successful save validated + wrote the config: it is now usable.
        self._config_usable = True
        if self.monitor_var.get():
            self._safe_start()
        # W2-003: Surrender engine owns only its own config/process - no global ApplyStart.

    def toggle_monitor(self):
        if self.monitor_var.get():
            if not self.save():
                self.monitor_var.set(False)  # persistence failed - don't start
                return
            # A successful save validated + wrote the config: it is now usable.
            self._config_usable = True
            if not self._safe_start():
                # CORE-011: spawn failed - persist OFF.
                self.monitor_var.set(False)
                self.save_monitor_state()
        else:
            stopped = self.runner.stop()
            # W2-006: only persist monitor_enabled=False when proven exit.
            if stopped:
                if not self.save_monitor_state():
                    self.status_var.set(Locale.tr("save_failed", fallback="Stopped (state not persisted)"))
            else:
                # W2-006: stop failed, child still live, retain ON state.
                self.monitor_var.set(True)
                self.status_var.set(Locale.tr("stop_failed", fallback="StopFailed (still running)"))

    def save_monitor_state(self):
        return update_json(self.cfg_path,
                    lambda c: c.__setitem__("monitor_enabled", self.monitor_var.get()),
                    canonical_default(self.CONFIG_NAME), config_name=self.CONFIG_NAME)

    def stop_all(self):
        stopped = self.runner.stop()
        try:
            self.monitor_var.set(False if stopped else True)
        except Exception as e:
            print("surrender_tab: reset monitor toggle failed: %s" % e, file=sys.stderr)
        return stopped

    def _tick(self):
        if not self.winfo_exists():
            return
        try:
            self.runner.poll_log()
        except Exception as e:
            print(f"surrender_tab _tick: poll_log error: {e}", file=sys.stderr)
        self._tick_id = self.after(1000, self._tick)

    def save(self, silent=False):
        def mutate(cfg):
            cfg["monitor_enabled"] = self.monitor_var.get()
            cfg["window_title"] = self.window_picker.get()
            cfg["poll_interval_sec"] = float(self.poll_interval.get())
            cfg["click_cooldown_sec"] = float(self.click_cooldown.get())
            cfg["auto_accept"] = self.auto_accept_var.get()
        try:
            ok = update_json(self.cfg_path, mutate,
                             canonical_default(self.CONFIG_NAME), config_name=self.CONFIG_NAME)
        except ValueError as e:
            if silent:
                print(f"Surrender save skipped (invalid input): {e}", file=sys.stderr)
            else:
                messagebox.showerror(Locale.tr("invalid_value"), str(e))
            return False
        return ok
