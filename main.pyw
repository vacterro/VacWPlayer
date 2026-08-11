import atexit
import copy
import ctypes
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import traceback
import shutil
from datetime import datetime
from tkinterdnd2 import TkinterDnD
import config_store

BASE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(BASE)

LOG_PATH = os.path.join(BASE, "crash.log")


def _excepthook(exc_type, exc_val, exc_tb):
    msg = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
    try:
        with open(LOG_PATH, "a") as f:
            f.write(msg + "\n")
    except OSError:
        pass
    try:
        import tkinter.messagebox
        tkinter.messagebox.showerror("VacWPlayer - Unhandled Error",
                                     "An error occurred:\n\n%s\n\nSee crash.log for details." % exc_val)
    except Exception:
        pass


sys.excepthook = _excepthook
for p in (BASE, PARENT):
    if p not in sys.path:
        sys.path.insert(0, p)

import champions
import single_instance
from theme import (
    apply_base_theme, TOKENS, FONT_SM,
    VintageButton, VintageLabel, VintageNotebook
)
import ahk_generator

from tabs.main_tab import MainTab, TOGGLE_DEFAULTS
from tabs.combo_tab import ComboTab, LEGACY_COMBOS
from tabs.champion_tab import ChampionTab
from tabs.death_tab import DeathWatchTab
from tabs.buy_tab import BuyTab
from tabs.auto_tab import AutoContinueTab
from tabs.minimap_tab import MinimapTab, MINIMAP_DEFAULTS
from tabs.afkfarm_tab import AFKFarmTab, AFKFARM_DEFAULTS
from tabs.accept_tab import AcceptTab
from tabs.surrender_tab import SurrenderTab
from combo_browser import ComboBrowser
from locales import Locale

CONFIG_FILE = os.path.join(BASE, "config.json")
CONFIG_LOCAL_FILE = os.path.join(BASE, "config.local.json")
GENERAL = "General"

config_warning = None
# Write guard (T-135): while the source config could not be read safely, the
# app runs on in-memory defaults but MUST NOT overwrite the source. None =
# writable; otherwise the reason the guard is armed. Cleared only by an
# explicit successful recovery/import/reset.
config_write_blocked = None
# Independent guard for config.local.json (T-169): a corrupt/unreadable/
# semantic-invalid local file may be ignored IN MEMORY, but automatic
# save/apply/quit must never overwrite it - a healthy primary config does not
# authorize destroying an unsafe local file. Missing local = first run,
# writable. Cleared only by an explicit successful local recovery/write.
local_write_blocked = None


def default_config():
    # T-179: deep-copied at the ownership boundary - the nested minimap/
    # afkfarm slot objects must never be shared aliases between callers.
    return copy.deepcopy({
        "mode": "ryze",
        "toggles": dict(TOGGLE_DEFAULTS),
        "combos": [dict(c) for c in LEGACY_COMBOS],
        "champions": {
            "ryze": champions.default_for("Ryze"),
            "xin_zhao": champions.default_for("Xin Zhao"),
        },
        "minimap": dict(MINIMAP_DEFAULTS, _order=[
            "top", "mid", "bot", "top_deep", "mid_deep", "bot_deep",
            "base", "enemy_base",
        ]),
        "afkfarm": dict(AFKFARM_DEFAULTS),
        "lang": "ru",
        "window": {"active_tab": 0},
    })


def _load_validated_on_disk(data):
    """Merge an already-validated config.json into defaults."""
    return load_config_merge(data, default_config())


def load_config():
    global config_warning, config_write_blocked, local_write_blocked
    config_write_blocked = None
    cfg = default_config()
    data, err = config_store.read_raw(CONFIG_FILE)
    if err is None:
        problems = config_store.validate_config(data)
        if problems:
            # Malformed-but-valid JSON is rejected BEFORE any migration or
            # merge (T-086): the file is left untouched for review, the app
            # runs on defaults, and no malformed section ever reaches the
            # live config. The write guard keeps a later auto-save from
            # overwriting the rejected source (T-135).
            for problem in problems:
                print("config_store: config.json rejected: %s" % problem, file=sys.stderr)
            config_warning = "corrupt"
            config_write_blocked = "invalid"
        else:
            cfg = _load_validated_on_disk(data)
    elif err == "missing":
        config_warning = None
    elif err == "corrupt":
        cfg = _recover_corrupt_config()
    else:  # io_error
        print("config_store: config.json unreadable (I/O error); running on "
              "defaults in memory, saving disabled until recovery/import",
              file=sys.stderr)
        config_warning = "io_error"
        config_write_blocked = "io_error"

    local_data, local_err = config_store.read_raw(CONFIG_LOCAL_FILE)
    if local_err == "corrupt":
        local_write_blocked = "corrupt"
        print("config_store: config.local.json corrupt, ignoring runtime state",
              file=sys.stderr)
    elif local_err == "io_error":
        local_write_blocked = "io_error"
        print("config_store: config.local.json unreadable, ignoring runtime state",
              file=sys.stderr)
    elif local_err == "missing":
        local_write_blocked = None  # first run: writable
    elif local_err is None:
        local_problems = config_store.validate_local_config(local_data)
        if local_problems:
            local_write_blocked = "invalid"
            for p in local_problems:
                print("config_store: config.local.json ignored: %s" % p, file=sys.stderr)
        else:
            local_write_blocked = None  # healthy: writable
            cfg = config_store.merge_volatile(cfg, local_data)
    return cfg


def _recover_corrupt_config():
    """Try to rebuild a corrupt config.json from a VALIDATED .bak.

    The .bak is read and structurally validated BEFORE it is copied over the
    live file (T-135): an invalid backup is never restored or merged. Returns
    the merged config; arms the write guard when recovery was impossible.
    """
    global config_warning, config_write_blocked
    bak_path = CONFIG_FILE + config_store.BAK_SUFFIX
    data, err = config_store.read_raw(bak_path)
    if err is None:
        problems = config_store.validate_config(data)
        if not problems:
            if config_store.restore_backup(CONFIG_FILE):
                print("config_store: config.json corrupt, restored from .bak")
                config_warning = "restored"
                # Explicit successful recovery: writable again.
                config_write_blocked = None
                return _load_validated_on_disk(data)
    print("config_store: config.json corrupt, no usable .bak, using defaults; "
          "saving disabled until recovery/import", file=sys.stderr)
    config_warning = "corrupt"
    config_write_blocked = "corrupt"
    return default_config()


def load_config_merge(on_disk, cfg):
    if "mode" not in on_disk:
        ryze = on_disk.get("ryze", {})
        xin = on_disk.get("xin", {})
        ryze_on = ryze.get("enabled", True) if isinstance(ryze, dict) else True
        xin_on = xin.get("enabled", False) if isinstance(xin, dict) else False
        on_disk["mode"] = "ryze" if ryze_on else ("xin" if xin_on else "general")
        on_disk.pop("ryze", None)
        on_disk.pop("xin", None)

    if "champions" not in on_disk:
        champs = {}
        if isinstance(on_disk.get("ryze"), dict):
            champs["ryze"] = dict(champions.default_for("Ryze"), **on_disk["ryze"])
        if isinstance(on_disk.get("xin"), dict):
            champs["xin_zhao"] = dict(champions.default_for("Xin Zhao"), **on_disk["xin"])
        on_disk["champions"] = champs or cfg["champions"]
        if on_disk.get("mode") == "xin":
            on_disk["mode"] = "xin_zhao"
    on_disk.pop("ryze", None)
    on_disk.pop("xin", None)

    lang = on_disk.get("lang", "ru")
    Locale.set_lang(lang if lang in Locale.languages() else "ru")

    for key in ("mode", "toggles", "combos", "champions", "window", "minimap", "afkfarm", "lang"):
        if key not in on_disk:
            continue
        if isinstance(cfg.get(key), dict) and isinstance(on_disk[key], dict):
            merged = dict(cfg[key])
            merged.update(on_disk[key])
            merged.pop("enabled", None)
            cfg[key] = merged
        else:
            cfg[key] = on_disk[key]

    for entry in cfg["champions"].values():
        if isinstance(entry, dict):
            for dead in [k for k in entry if k.endswith("_pixel")] + ["ryze_smart_logic"]:
                entry.pop(dead, None)
    return cfg


def save_config(config, bypass_guard=False):
    """Persist the stable+local halves. Returns True only on a successful write.

    While the write guard is armed (degraded startup: corrupt/rejected/
    unreadable source) NOTHING is written - defaults may run in memory, but
    automatic saves must never overwrite the source (T-135).

    `bypass_guard` is reserved for EXPLICIT recovery writes (import): the
    candidate is written over the damaged source on purpose, but the guard is
    only cleared afterwards, when the write succeeded (T-156).
    """
    if config_write_blocked and not bypass_guard:
        print("config_store: save skipped (%s); recover config or import a "
              "backup to re-enable saving" % config_write_blocked, file=sys.stderr)
        return False
    stable, local = config_store.split_volatile(config)
    # T-170: snapshot the previous local half so a failed save can roll it
    # back - save_config(False) must leave NO durable candidate half behind.
    local_existed = os.path.exists(CONFIG_LOCAL_FILE)
    local_prev = None
    if local_existed:
        try:
            with open(CONFIG_LOCAL_FILE, "rb") as f:
                local_prev = f.read()
        except OSError:
            local_prev = None
    local_written = False
    try:
        # Local (volatile) half FIRST, stable half LAST (T-161): on a failed
        # save the PRIMARY config.json is never left ahead of the failure -
        # "False" always means the main config did not change.
        if not local_write_blocked or bypass_guard:
            config_store.atomic_write(CONFIG_LOCAL_FILE, local)
            local_written = True
        config_store.atomic_write(CONFIG_FILE, stable)
    except OSError as e:
        print("config_store: save failed: %s" % e, file=sys.stderr)
        if local_written:
            try:
                if local_existed and local_prev is not None:
                    config_store.atomic_write(
                        CONFIG_LOCAL_FILE, json.loads(local_prev.decode("utf-8")))
                elif not local_existed:
                    os.remove(CONFIG_LOCAL_FILE)
            except Exception:
                pass  # rollback is best-effort; primary config was not touched
        return False
    return True


def display_name(key, entry):
    if isinstance(entry, dict) and entry.get("display_name"):
        return entry["display_name"]
    for n in champions.ROSTER:
        if champions.slug(n) == key:
            return n
    return key.replace("_", " ").title()


def _first_drop_path(splitlist, raw):
    """Parse a TkinterDnD <<Drop>> payload (a Tcl list) into the first usable
    local .json file path, or None (T-145).

    Tcl's splitlist handles the quoting itself: {braced} paths, Windows paths
    with spaces, multiple files and file:/// URIs all parse correctly - no
    manual whitespace tokenization (raw.split()[0] used to truncate
    "C:\\Users\\A\\My Config.json" to "C:\\Users\\A\\My")."""
    if not raw or not raw.strip():
        return None
    try:
        items = splitlist(raw.strip())
    except tk.TclError:
        return None
    for item in items:
        path = item.strip()
        if path.startswith("file:///"):
            path = path[8:]
        if os.path.isfile(path) and path.lower().endswith(".json"):
            return path
    return None


class VacWPlayer:
    def __init__(self):
        self.config = load_config()
        self._applying = False
        # T-177: the config the runtime is ACTUALLY running (set only after a
        # successful Apply). Editing/autosaving updates self.config (draft);
        # the watchdog resurrects THIS, never the mutable draft - otherwise
        # whether a draft goes live depends on whether AHK happened to crash.
        self._last_applied_config = None

        self.root = TkinterDnD.Tk()
        self.root.title("VacWPlayer")
        self.root.geometry(self._restore_geometry())
        self.root.resizable(True, True)
        apply_base_theme(self.root)
        self.root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x02000000)
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0020)
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.root.drop_target_register("*")
        self.root.dnd_bind("<<Drop>>", self._on_file_drop)
        self.root.bind("<<AutoSave>>", self._on_auto_save)
        self.root.bind("<<ApplyStart>>", lambda e: self.apply_and_start())
        self._auto_save_timer = None
        self._show_config_warning()

        bar = tk.Frame(self.root, bg=TOKENS["background"])
        bar.pack(side="bottom", fill="x", padx=4, pady=(0, 4))

        self.notebook = VintageNotebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=2, pady=2)

        self._tab_specs = [
            ("tab_main", "tab_main", lambda: MainTab(self.notebook, self.config)),
            ("tab_combos", "tab_combos", lambda: ComboTab(self.notebook, self.config)),
            ("tab_champions", "tab_champions", lambda: ChampionTab(
                self.notebook, self.config["champions"],
                on_select=self._on_champ_select, on_remove=self._on_champ_remove)),
            ("tab_death", "tab_death", lambda: DeathWatchTab(self.notebook)),
            ("tab_buy", "tab_buy", lambda: BuyTab(self.notebook)),
            ("tab_auto", "tab_auto", lambda: AutoContinueTab(self.notebook)),
            ("tab_minimap", "tab_minimap", lambda: MinimapTab(self.notebook, self.config.get("minimap"))),
            ("tab_afkfarm", "tab_afkfarm", lambda: AFKFarmTab(self.notebook, self.config.get("afkfarm"))),
            ("tab_accept", "tab_accept", lambda: AcceptTab(self.notebook)),
            ("tab_surrender", "tab_surrender", lambda: SurrenderTab(self.notebook)),
        ]
        self._build_all_tabs()
        self._restore_active_tab()

        self._bar_locale_widgets = []
        self.lang_var = tk.StringVar()
        self.lang_box = ttk.Combobox(bar, textvariable=self.lang_var, state="readonly",
                                     values=[Locale.language_name(c) for c in Locale.languages()],
                                     font=FONT_SM, width=14)
        self.lang_box.set(Locale.language_name(Locale.current()))
        self.lang_box.pack(side="left")
        self.lang_box.bind("<<ComboboxSelected>>", self._set_lang)
        lbl_champ = VintageLabel(bar, text=Locale.tr("champion"), font=FONT_SM)
        lbl_champ.pack(side="left")
        self._bar_locale_widgets.append(("label", lbl_champ, "champion"))
        self.var_mode = tk.StringVar()
        self.mode_box = ttk.Combobox(bar, textvariable=self.var_mode, width=8,
                                     state="readonly", font=FONT_SM)
        self.mode_box.pack(side="left", padx=1)
        self._refresh_mode_box()
        tk.Frame(bar, bg=TOKENS["borderMuted"], width=1).pack(side="left", fill="y", pady=1)
        btn_export = VintageButton(bar, text=Locale.tr("export"), command=self.export_config, width=2)
        btn_export.pack(side="left")
        self._bar_locale_widgets.append(("btn", btn_export, "export"))
        btn_import = VintageButton(bar, text=Locale.tr("import"), command=self.import_config, width=2)
        btn_import.pack(side="left")
        self._bar_locale_widgets.append(("btn", btn_import, "import"))
        btn_backup = VintageButton(bar, text=Locale.tr("backup"), command=self.backup_config, width=2)
        btn_backup.pack(side="left")
        self._bar_locale_widgets.append(("btn", btn_backup, "backup"))
        btn_hotkeys = VintageButton(bar, text=Locale.tr("hotkeys"), command=self._show_hotkeys, width=2)
        btn_hotkeys.pack(side="left")
        self._bar_locale_widgets.append(("btn", btn_hotkeys, "hotkeys"))
        btn_browse = VintageButton(bar, text=Locale.tr("browse_combos"), command=self._show_combo_browser, width=2)
        btn_browse.pack(side="left")
        self._bar_locale_widgets.append(("btn", btn_browse, "browse_combos"))
        tk.Frame(bar, bg=TOKENS["borderMuted"], width=1).pack(side="left", fill="y", pady=1)

        self.ahk_dot = tk.Canvas(bar, width=8, height=8, bg=TOKENS["background"],
                                 bd=0, highlightthickness=0)
        self.ahk_dot.pack(side="right", pady=1)
        self.ahk_dot_id = self.ahk_dot.create_oval(1, 1, 7, 7, fill=TOKENS["danger"], outline="")
        btn_stop = VintageButton(bar, text=Locale.tr("stop"), command=self.stop_engine, width=2)
        btn_stop.pack(side="right")
        self._bar_locale_widgets.append(("btn", btn_stop, "stop"))
        self.status_lbl = VintageLabel(bar, text=Locale.tr("ready"), font=FONT_SM, width=34, anchor="w")
        self.status_lbl.pack(side="right")
        btn_apply = VintageButton(bar, text=Locale.tr("apply_start"), command=self.apply_and_start, width=2)
        btn_apply.pack(side="right")
        self._bar_locale_widgets.append(("btn", btn_apply, "apply_start"))

        self.tray_icon = None
        self.setup_tray()

        self._engine_should_run = True
        self.root.after(100, self.apply_and_start)

        toggles = self.config.get("toggles", {})
        if toggles.get("exit_when_bs_gone", True):
            exes = [toggles.get("target_exe") or "HD-Player.exe"]
            single_instance.start_target_watchdog(
                exes,
                lambda: self.root.after(0, self.quit_app),
                interval_sec=3.0,
                grace_ticks=2,
                min_uptime_sec=15.0)

        self.root.after(3000, self._engine_watchdog)

    # --- tabs ------------------------------------------------------------------
    def _build_all_tabs(self):
        for attr, key, factory in self._tab_specs:
            tab = factory()
            self.notebook.add(tab, text=Locale.tr(key))
            setattr(self, attr, tab)

    # --- locale ---------------------------------------------------------------
    def _set_lang(self, _event=None):
        for code in Locale.languages():
            if Locale.language_name(code) == self.lang_var.get():
                Locale.set_lang(code)
                break
        self._apply_locale()
        self.collect_config()
        save_config(self.config)

    def _apply_locale(self):
        for kind, widget, key in self._bar_locale_widgets:
            if kind == "label":
                widget.config(text=Locale.tr(key))
            elif kind == "btn":
                widget.label.config(text=Locale.tr(key))
        self.status_lbl.config(text=Locale.tr("ready"))
        for idx, (attr, key, _factory) in enumerate(self._tab_specs):
            tab = getattr(self, attr, None)
            if tab is not None:
                self.notebook.tab(idx, text=Locale.tr(key))
                if hasattr(tab, "apply_locale"):
                    tab.apply_locale()

    # --- champion tab ---------------------------------------------------------
    def _on_champ_select(self, key):
        if not hasattr(self, "var_mode"):
            return
        name = display_name(key, self.config["champions"].get(key, {}))
        self.var_mode.set(name)
        self.config["mode"] = key

    def _on_champ_remove(self, key):
        if not hasattr(self, "var_mode") or not hasattr(self, "mode_box"):
            return
        mode_key = self.config.get("mode", "general")
        if mode_key == key:
            names = self.mode_box["values"]
            self.var_mode.set(names[0] if names else GENERAL)
            self.config["mode"] = "general"

    def _refresh_mode_box(self):
        names = [GENERAL]
        for key, entry in self.config["champions"].items():
            names.append(display_name(key, entry))
        self.mode_box["values"] = names
        current = self.var_mode.get()
        if current not in names:
            mode = self.config.get("mode", "general")
            if mode == "general":
                self.var_mode.set(GENERAL)
            else:
                match = display_name(mode, self.config["champions"].get(mode, {}))
                self.var_mode.set(match if match in names else GENERAL)

    def _mode_key(self):
        name = self.var_mode.get()
        return "general" if name == GENERAL else champions.slug(name)

    # --- window state ---------------------------------------------------------
    def _restore_active_tab(self):
        tab_idx = self.config.get("window", {}).get("active_tab", 0)
        count = len(self.notebook.tabs())
        if 0 <= tab_idx < count:
            self.notebook.select(tab_idx)

    def _restore_geometry(self):
        # Window must be wide enough for the bottom button bar (~870px in RU
        # with real labels) - 750 clipped the right-side buttons.
        win_w, win_h = 920, 550
        pos = self.config.get("window", {}).get("position", "")
        try:
            x, y = (int(v) for v in pos.split(","))
        except (ValueError, AttributeError):
            return "%dx%d" % (win_w, win_h)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, min(x, max(0, sw - win_w)))
        y = max(0, min(y, max(0, sh - win_h)))
        return "%dx%d+%d+%d" % (win_w, win_h, x, y)

    def _remember_window(self):
        try:
            if self.root.state() == "withdrawn":
                return
            self.config.setdefault("window", {})["position"] = (
                "%d,%d" % (self.root.winfo_x(), self.root.winfo_y()))
        except tk.TclError:
            pass

    # --- auto-save -----------------------------------------------------------
    def _on_auto_save(self, event=None):
        if self._auto_save_timer:
            self.root.after_cancel(self._auto_save_timer)
        self._auto_save_timer = self.root.after(300, self._do_auto_save)

    def _do_auto_save(self):
        self._auto_save_timer = None
        self.collect_config()
        save_config(self.config)

    # --- engine ---------------------------------------------------------------
    def collect_config(self):
        self.config["mode"] = self._mode_key()
        if self.tab_combos:
            self.config["combos"] = self.tab_combos.get_data()
        if self.tab_main:
            self.config["toggles"] = self.tab_main.get_toggles()
        if self.tab_champions:
            self.config["champions"] = self.tab_champions.get_data()
        if self.tab_minimap:
            self.config["minimap"] = self.tab_minimap.get_data()
        if self.tab_afkfarm:
            self.config["afkfarm"] = self.tab_afkfarm.get_data()
        self.config["lang"] = Locale.current()
        self.config.setdefault("window", {})["active_tab"] = self.notebook.index(self.notebook.select())
        self._remember_window()

    def export_config(self):
        path = filedialog.asksaveasfilename(
            initialdir=BASE, defaultextension=".json",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
            title=Locale.tr("export_config_title"))
        if not path:
            return
        self.collect_config()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
                f.write("\n")
            self.status_lbl.config(text=Locale.tr("export_ok"), fg=TOKENS["success"])
        except OSError as e:
            messagebox.showerror(Locale.tr("export_failed"), str(e))

    def _on_file_drop(self, event):
        path = _first_drop_path(self.tk.splitlist, getattr(event, "data", ""))
        if path:
            self.root.after(50, lambda: self._do_import_file(path))
            return
        if getattr(event, "data", "") and str(event.data).strip():
            messagebox.showwarning(Locale.tr("import"),
                                   Locale.tr("import_only_json"))

    def _do_import_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                imported = json.load(f)
        except (OSError, ValueError) as e:
            messagebox.showerror(Locale.tr("import_failed"), str(e))
            return
        # Validate BEFORE save: a structurally-bad import must never overwrite
        # the user's live config (T-092).
        problems = config_store.validate_config(imported)
        if problems:
            messagebox.showerror(
                Locale.tr("import_failed"), "; ".join(problems[:3]))
            return
        if not messagebox.askyesno(Locale.tr("import_config_title"),
                                   Locale.tr("import_config_confirm") + "\n%s?" % os.path.basename(path)):
            return
        # Explicit import is a sanctioned recovery: the candidate write may
        # bypass the guard, but the guard is only released after the write
        # actually landed and the result validates. A failed recovery write
        # restores the previous guard so later autosaves stay blocked (T-156).
        global config_write_blocked
        previous_guard = config_write_blocked
        if not save_config(imported, bypass_guard=True):
            config_write_blocked = previous_guard
            messagebox.showerror(Locale.tr("import_failed"),
                                 Locale.tr("import_write_failed", fallback="Import was not saved: config file write failed."))
            return
        self.config = load_config()  # read-back; re-arms guard if disk invalid
        self._rebuild_ui()
        self.status_lbl.config(text=Locale.tr("import_ok"), fg=TOKENS["success"])

    def import_config(self):
        path = filedialog.askopenfilename(
            initialdir=BASE, filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
            title=Locale.tr("import_config_title"))
        if not path:
            return
        self._do_import_file(path)

    def backup_config(self):
        backup_dir = os.path.join(BASE, "backups")
        try:
            os.makedirs(backup_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror(Locale.tr("backup_failed"), str(e))
            return
        self.collect_config()
        # The backup must contain the CURRENT STABLE config. If the write is
        # blocked (guard) or fails, there is no stable current config to back
        # up - abort instead of copying the corrupt/rejected source and
        # calling it a successful backup (T-157).
        if not save_config(self.config):
            reason = config_write_blocked or "config file write failed"
            messagebox.showerror(
                Locale.tr("backup_failed"),
                Locale.tr("backup_blocked", fallback="No current-config backup created: %s" % reason))
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, "config_%s.json" % ts)
        try:
            shutil.copy2(CONFIG_FILE, backup_path)
            self.status_lbl.config(text=Locale.tr("backup_ok") + "config_%s.json" % ts,
                                   fg=TOKENS["success"])
        except OSError as e:
            messagebox.showerror(Locale.tr("backup_failed"), str(e))

    def _show_config_warning(self):
        if config_warning == "corrupt":
            messagebox.showwarning(
                Locale.tr("config_error_title", fallback="Config Error"),
                Locale.tr("config_corrupt_no_backup",
                          fallback="config.json was unreadable and no usable "
                                   "backup was found. Settings were reset to defaults."))
        elif config_warning == "restored":
            messagebox.showinfo(
                Locale.tr("config_restored_title", fallback="Config Restored"),
                Locale.tr("config_restored",
                          fallback="config.json was unreadable; restored from "
                                   "the last good backup (.bak)."))
        elif config_warning == "io_error":
            messagebox.showwarning(
                Locale.tr("config_error_title", fallback="Config Error"),
                Locale.tr("config_io_error",
                          fallback="config.json could not be read (I/O/permission error). "
                                   "Settings are shown from defaults and saving is disabled "
                                   "until the file is fixed or a backup is imported."))

    def _rebuild_ui(self):
        if self.tab_death:
            self.tab_death.stop_all()
        if self.tab_auto:
            self.tab_auto.stop_all()
        if self.tab_accept:
            self.tab_accept.stop_all()
        if self.tab_surrender:
            self.tab_surrender.stop_all()
        for tab in list(self.notebook.tabs()):
            w = self.notebook.nametowidget(tab)
            self.notebook.forget(tab)
            w.destroy()

        self._build_all_tabs()
        self._refresh_mode_box()

    def _update_ahk_dot(self, running):
        self.ahk_dot.itemconfig(self.ahk_dot_id,
                                fill=TOKENS["success"] if running else TOKENS["danger"])

    def apply_and_start(self):
        if self._applying:
            return
        self._applying = True
        self.collect_config()
        if not save_config(self.config):
            # Degraded state (corrupt/unreadable config, guard armed): the
            # candidate must not overwrite the source, and automation must not
            # run on unvalidated defaults (T-135).
            self._applying = False
            self.status_lbl.config(
                text=Locale.tr("config_locked",
                               fallback="Config locked (corrupt/unreadable); fix config or import a backup"),
                fg=TOKENS["danger"])
            return
        self._engine_should_run = True
        self.status_lbl.config(text=Locale.tr("generating"), fg=TOKENS["warning"])
        threading.Thread(target=self._apply_worker, daemon=True).start()

    def _apply_worker(self):
        try:
            ok, msg = ahk_generator.generate_and_run(self.config)
        except Exception as e:
            print("ahk apply worker failed: %s" % e, file=sys.stderr)
            ok, msg = False, "Apply failed: %s" % e
        self.root.after(0, lambda: self._apply_done(ok, msg, self.config))

    def _apply_done(self, ok, msg, candidate=None):
        # A rejected candidate must not paint the last-good runtime dead: the
        # AHK dot reflects the ACTUAL runtime state, not the apply result.
        running = ok or ahk_generator.is_running()
        if not ok and running:
            msg = msg + " - last-good AHK still running"
        if ok and candidate is not None:
            # T-177: only an ACCEPTED candidate becomes the last-applied state
            # the watchdog resurrects; a rejected candidate never does.
            self._last_applied_config = copy.deepcopy(candidate)
        self.status_lbl.config(text=self._short_status(msg),
                               fg=TOKENS["success"] if ok else TOKENS["danger"])
        self._update_ahk_dot(running)
        self._applying = False

    @staticmethod
    def _short_status(msg, limit=64):
        """Cap the one-line status text so a long warning/dropped list cannot
        push the bottom bar's buttons out of the window."""
        msg = str(msg)
        return msg if len(msg) <= limit else msg[:limit - 1] + "…"

    def stop_engine(self):
        self._engine_should_run = False
        ahk_generator.stop_ahk()
        self.status_lbl.config(text=Locale.tr("engine_stopped"), fg=TOKENS["textPrimary"])
        self._update_ahk_dot(False)

    def _engine_watchdog(self):
        if getattr(self, "_engine_should_run", False) and not self._applying:
            if not ahk_generator.is_running():
                self._applying = True
                self.status_lbl.config(text=Locale.tr("auto_restarting"), fg=TOKENS["warning"])
                threading.Thread(target=self._watchdog_worker, daemon=True).start()
        try:
            self.root.after(3000, self._engine_watchdog)
        except tk.TclError:
            pass

    def _watchdog_worker(self):
        # T-177: resurrect the LAST-APPLIED config, never the mutable editor
        # draft (fall back to self.config only before any Apply succeeded).
        last = getattr(self, "_last_applied_config", None)
        cfg = last if last is not None else self.config
        try:
            ok, msg = ahk_generator.generate_and_run(cfg)
        except Exception as e:
            print("ahk watchdog worker failed: %s" % e, file=sys.stderr)
            ok, msg = False, "Auto-restart failed: %s" % e
        self.root.after(0, lambda: self._watchdog_done(ok, msg))

    def _watchdog_done(self, ok, msg):
        running = ok or ahk_generator.is_running()
        self.status_lbl.config(text=self._short_status(Locale.tr("auto_restarted") + " " + msg),
                               fg=TOKENS["warning"])
        self._update_ahk_dot(running)
        self._applying = False

    def _show_hotkeys(self):
        win = tk.Toplevel(self.root)
        win.title(Locale.tr("hotkeys_title"))
        win.configure(bg=TOKENS["background"])
        win.resizable(False, False)
        txt = tk.Text(win, width=56, height=24, bg=TOKENS["compareBack"],
                      fg=TOKENS["textPrimary"], font=("Consolas", 9),
                      bd=0, highlightthickness=0, wrap="none")
        txt.pack(padx=8, pady=8)

        def w(t):
            txt.insert("end", t + "\n")

        toggles = self.config.get("toggles", {})
        champs = self.config.get("champions", {})
        minimap = self.config.get("minimap", {})
        afkfarm = self.config.get("afkfarm", {})

        w("=== " + Locale.tr("hk_global") + " ===")
        w("  " + Locale.tr("hk_stop_key") + ":     %s" % toggles.get("stop_key", "s"))
        w("  " + Locale.tr("hk_anti_afk") + ":     Ctrl+G (" + Locale.tr("hk_in_game_toggle") + ")")
        w("  " + Locale.tr("hk_mode") + ":         %s" % self.config.get("mode", "general"))
        w("  " + Locale.tr("hk_target_exe") + ":   %s" % toggles.get("target_exe", "HD-Player.exe"))
        w("")

        w("=== " + Locale.tr("hk_champ_triggers") + " ===")
        mode = self.config.get("mode", "general")
        if mode != "general":
            entry = champs.get(mode, {})
            for slot in ("wave", "jungle", "pvp"):
                trig = entry.get("trigger_" + slot, "")
                if trig:
                    keys = entry.get("keys_" + slot, "")
                    w("  %s: %s -> %s" % (slot, trig, keys))
        else:
            for c in self.config.get("combos", []):
                w("  %s -> %s  (%s %d)" % (
                    c.get("trigger", "?"), c.get("keys", "?"),
                    Locale.tr("hk_interval"), c.get("interval", 50)))
        w("")

        w("=== " + Locale.tr("hk_minimap") + " ===")
        for key in minimap.get("_order", []):
            entry = minimap.get(key, {})
            trig = entry.get("trigger", "")
            x, y = entry.get("x", 0), entry.get("y", 0)
            if trig:
                w("  %s: %s  (%d, %d)" % (key, trig, x, y))
        w("")

        w("=== " + Locale.tr("hk_afk_farm") + " ===")
        if afkfarm.get("enabled"):
            w("  " + Locale.tr("hk_toggle") + ":  %s" % afkfarm.get("toggle_key", "F5"))
            w("  " + Locale.tr("hk_slots") + ":   %s" % ", ".join(afkfarm.get("slots", [])))
            w("  " + Locale.tr("hk_combo") + ":   %s" % afkfarm.get("combo_keys", ""))
        else:
            w("  (" + Locale.tr("hk_disabled") + ")")

        txt.config(state="disabled")
        VintageButton(win, text=Locale.tr("close_lbl"), command=win.destroy, width=8).pack(pady=(0, 8))
        win.bind("<Escape>", lambda e: win.destroy())

    def _show_combo_browser(self):
        ComboBrowser(self.root, on_apply=self._browser_apply)

    def _browser_apply(self, name):
        key = champions.slug(name)
        if key in self.config["champions"]:
            names = self.mode_box["values"]
            for n in names:
                if champions.slug(n) == key:
                    self.var_mode.set(n)
                    self.config["mode"] = key
                    self.tab_champions.var_champ.set(n)
                    return
        self.config["champions"][key] = dict(
            champions.default_for(name), display_name=name)
        self.tab_champions.refresh_list()
        self.tab_champions.var_champ.set(name)
        self._refresh_mode_box()

    def stop_everything(self):
        self._engine_should_run = False
        ahk_generator.stop_ahk()
        self._update_ahk_dot(False)
        if self.tab_death:
            self.tab_death.stop_all()
        if self.tab_auto:
            self.tab_auto.stop_all()
        if self.tab_accept:
            self.tab_accept.stop_all()
        if self.tab_surrender:
            self.tab_surrender.stop_all()

    # --- tray -------------------------------------------------------------------
    def _tray_image(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (64, 64), TOKENS["background"])
        dc = ImageDraw.Draw(img)
        dc.rectangle([2, 2, 61, 61], outline=TOKENS["borderHighlight"], width=2)
        dc.rectangle([6, 6, 57, 57], fill=TOKENS["surfaceRaised"],
                     outline=TOKENS["borderDark"], width=1)
        dc.text((14, 20), "WR", fill=TOKENS["textPrimary"])
        return img

    def setup_tray(self):
        try:
            import pystray
        except ImportError:
            return
        menu = pystray.Menu(
            pystray.MenuItem(Locale.tr("tray_show"), self.show_window, default=True),
            pystray.MenuItem(Locale.tr("tray_apply_start"), lambda: self.root.after(0, self.apply_and_start)),
            pystray.MenuItem(Locale.tr("tray_stop"), lambda: self.root.after(0, self.stop_engine)),
            pystray.MenuItem(Locale.tr("tray_quit"), self._tray_quit),
        )
        self.tray_icon = pystray.Icon("VacWPlayer", self._tray_image(),
                                      "VacWPlayer", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _tray_quit(self, icon=None, item=None):
        # Marshal to the Tk thread: quit_app touches Tk widgets and must never
        # run on pystray's callback thread (T-149-F).
        self.root.after(0, self.quit_app)

    def show_window(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def quit_app(self, icon=None, item=None):
        if self.tray_icon:
            self.tray_icon.stop()
        self.collect_config()
        for tab in (self.tab_death, self.tab_buy, self.tab_auto, self.tab_accept, self.tab_surrender):
            if tab and hasattr(tab, "save"):
                tab.save(silent=True)
        save_config(self.config)
        self.stop_everything()
        self.root.after(0, self.root.destroy)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    import engine_config
    engine_config.setup_logging()
    single_instance.ensure_single_instance("wr_assistant", replace=True)
    app = VacWPlayer()
    atexit.register(app.stop_everything)
    app.run()
