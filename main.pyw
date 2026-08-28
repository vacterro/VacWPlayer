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
# W2-003: crash-recoverable transaction journal for the two-half persistence
# (config.local.json written first, config.json last). A hard process
# termination between the two atomic replacements leaves this journal; startup
# resolves it by committing the FULL candidate pair, never a hybrid revision.
_TXN_FILE = CONFIG_LOCAL_FILE + ".txn"
GENERAL = "General"


def _txn_write(stable_bytes, local_bytes):
    """Atomically persist the pending two-half transaction (W2-003)."""
    import base64
    try:
        payload = json.dumps({
            "stable": base64.b64encode(stable_bytes).decode("ascii"),
            "local": base64.b64encode(local_bytes).decode("ascii"),
        })
        tmp = _TXN_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, _TXN_FILE)
        return True
    except OSError:
        return False


def _txn_clear():
    try:
        os.remove(_TXN_FILE)
    except OSError:
        pass


def _txn_recover():
    """W2-003 + CORE-002: resolve a crash between the local and stable writes.
    Returns one of: NONE (no journal), RECOVERED (both halves repaired),
    PENDING_FAILED (journal exists but I/O failed; retry next startup),
    INVALID_JOURNAL (malformed journal data). load_config must never merge
    live halves while PENDING_FAILED or INVALID_JOURNAL is returned."""
    import base64
    try:
        with open(_TXN_FILE, encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        return "NONE"
    except (OSError, ValueError, KeyError, TypeError):
        _txn_clear()
        return "INVALID_JOURNAL"
    try:
        stable_bytes = base64.b64decode(payload["stable"])
        local_bytes = base64.b64decode(payload["local"])
    except (ValueError, KeyError, TypeError, base64.binascii.Error):
        _txn_clear()
        return "INVALID_JOURNAL"
    try:
        config_store.atomic_write_bytes(CONFIG_FILE, stable_bytes,
                                        promote_bak=False)
        config_store.atomic_write_bytes(CONFIG_LOCAL_FILE, local_bytes,
                                        promote_bak=False)
    except OSError:
        return "PENDING_FAILED"  # keep journal; retry on next startup
    _txn_clear()
    return "RECOVERED"


config_warning = None
# W2-007: visible local volatile-state degradation ("degraded" | "restored").
local_warning = None
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
    """Merge an already-validated config.json into defaults.
    T-CORE-013: migration is guaranteed to have run before this is called
    (either from load_config or _recover_corrupt_config), but we run it again
    defensively in case a backup contains unmigrated legacy schema."""
    data = _migrate_legacy_config(data)
    return load_config_merge(data, default_config())


def _migrate_legacy_config(raw):
    """Detect and convert recognized legacy schema (ryze/xin top-level keys)
    into the modern format before validation. Never mutates the source object.

    T-CORE-013: the v0.3.34 legacy migration fix was only partially wired;
    valid old configs carrying an explicit legacy mode were rejected by
    modern validation before migration could run. This pre-validation step
    ensures legacy configs are converted BEFORE validate_config.
    """
    if not isinstance(raw, dict):
        return raw  # not a dict - let validation handle it
    # Detect legacy keys (only act when they actually exist)
    has_legacy_ryze = "ryze" in raw and isinstance(raw.get("ryze"), dict)
    has_legacy_xin = "xin" in raw and isinstance(raw.get("xin"), dict)
    has_legacy_mode = raw.get("mode") in ("ryze", "xin")
    if not (has_legacy_ryze or has_legacy_xin or has_legacy_mode):
        return raw  # no legacy markers - pass through unchanged
    # Work on a copy to never mutate the source
    data = copy.deepcopy(raw)
    legacy_ryze = data.pop("ryze", None)
    legacy_xin = data.pop("xin", None)
    if isinstance(legacy_ryze, dict):
        if "champions" not in data or not isinstance(data.get("champions"), dict):
            data["champions"] = {}
        data["champions"]["ryze"] = dict(champions.default_for("Ryze"), **legacy_ryze)
    if isinstance(legacy_xin, dict):
        if "champions" not in data or not isinstance(data.get("champions"), dict):
            data["champions"] = {}
        data["champions"]["xin_zhao"] = dict(champions.default_for("Xin Zhao"), **legacy_xin)
    # Derive mode if not present
    if "mode" not in data:
        ryze_on = False
        xin_on = False
        if isinstance(data.get("champions"), dict):
            ryze_entry = data["champions"].get("ryze")
            xin_entry = data["champions"].get("xin_zhao")
            if isinstance(ryze_entry, dict):
                ryze_on = ryze_entry.get("enabled", True)
            if isinstance(xin_entry, dict):
                xin_on = xin_entry.get("enabled", False)
        data["mode"] = "ryze" if ryze_on else ("xin_zhao" if xin_on else "general")
    # Map legacy mode values
    if data.get("mode") == "xin":
        data["mode"] = "xin_zhao"
    return data


def load_config():
    global config_warning, config_write_blocked, local_write_blocked, local_warning
    config_write_blocked = None
    # W2-003: resolve any interrupted two-half transaction before reading, so
    # startup never merges halves from two different committed states.
    txn_result = _txn_recover()
    if txn_result in ("PENDING_FAILED", "INVALID_JOURNAL"):
        config_write_blocked = "txn_unresolved"
        print("config_store: transaction unresolved (%s); running on "
              "defaults, saving disabled" % txn_result, file=sys.stderr)
    cfg = default_config()
    data, err = config_store.read_raw(CONFIG_FILE)
    if err is None:
        # T-CORE-013: migrate recognized legacy schema BEFORE modern
        # validation so valid old configs (mode=ryze, ryze:{...}) are not
        # rejected by the modern validator.
        data = _migrate_legacy_config(data)
        problems = config_store.validate_config(data)
        if problems:
            # Malformed-but-valid JSON is rejected AFTER migration attempt
            # (T-086): the file is left untouched for review, the app
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
        if not _recover_local_from_bak():
            print("config_store: config.local.json corrupt, ignoring runtime state",
                  file=sys.stderr)
    elif local_err == "io_error":
        # W2-007: permission/unreadable stays FAIL-CLOSED - never auto-replace a
        # file we cannot even read.
        local_write_blocked = "io_error"
        local_warning = "degraded"
        print("config_store: config.local.json unreadable, ignoring runtime state",
              file=sys.stderr)
    elif local_err == "missing":
        local_write_blocked = None  # first run: writable
    elif local_err is None:
        local_problems = config_store.validate_local_config(local_data)
        if local_problems:
            local_write_blocked = "invalid"
            if not _recover_local_from_bak():
                for p in local_problems:
                    print("config_store: config.local.json ignored: %s" % p,
                          file=sys.stderr)
        else:
            local_write_blocked = None  # healthy: writable
            cfg = config_store.merge_volatile(cfg, local_data)
    return cfg


def _recover_local_from_bak():
    """W2-007: restore a VALIDATED config.local.json.bak over the corrupt or
    semantically-invalid live local file. Returns True on recovery; on failure
    surfaces a visible degraded state instead of silently locking persistence."""
    global local_write_blocked, local_warning
    bak = CONFIG_LOCAL_FILE + config_store.BAK_SUFFIX
    data, err = config_store.read_raw(bak)
    if err is not None or config_store.validate_local_config(data):
        local_warning = "degraded"
        return False
    try:
        config_store.atomic_write(CONFIG_LOCAL_FILE, data, promote_bak=False)
    except OSError:
        local_warning = "degraded"
        return False
    local_write_blocked = None
    local_warning = "restored"
    print("config_store: config.local.json restored from validated .bak",
          file=sys.stderr)
    return True


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
        # CORE-011: migrate legacy schema of the backup BEFORE validation,
        # exactly as the normal primary load does (load_config ->
        # _migrate_legacy_config). A backup that is valid only after legacy
        # migration (e.g. mode="xin" with legacy xin data) must restore
        # successfully instead of forcing defaults + the write guard. The
        # damaged primary is still never promoted over the known-good .bak.
        migrated = _migrate_legacy_config(data)
        problems = config_store.validate_config(migrated)
        if not problems:
            if config_store.restore_backup(CONFIG_FILE):
                print("config_store: config.json corrupt, restored from .bak")
                config_warning = "restored"
                # Explicit successful recovery: writable again.
                config_write_blocked = None
                return _load_validated_on_disk(migrated)
    print("config_store: config.json corrupt, no usable .bak, using defaults; "
          "saving disabled until recovery/import", file=sys.stderr)
    config_warning = "corrupt"
    config_write_blocked = "corrupt"
    return default_config()


def load_config_merge(on_disk, cfg):
    # T-CORE-013: legacy migration (ryze/xin/mode) is handled by
    # _migrate_legacy_config before this function is called. This function
    # only handles the modern merge of on_disk data into defaults.

    if "champions" not in on_disk:
        on_disk["champions"] = cfg["champions"]
    elif not isinstance(on_disk.get("champions"), dict):
        on_disk["champions"] = cfg["champions"]

    lang = on_disk.get("lang", "ru")
    Locale.set_lang(lang if lang in Locale.languages() else "ru")

    for key in ("mode", "toggles", "combos", "champions", "window", "minimap", "afkfarm", "lang"):
        if key not in on_disk:
            continue
        if isinstance(cfg.get(key), dict) and isinstance(on_disk[key], dict):
            merged = dict(cfg[key])
            merged.update(on_disk[key])
            cfg[key] = merged
        else:
            cfg[key] = on_disk[key]

    for entry in cfg["champions"].values():
        if isinstance(entry, dict):
            for dead in [k for k in entry if k.endswith("_pixel")] + ["ryze_smart_logic"]:
                entry.pop(dead, None)
    return cfg


def save_config(config, bypass_guard=False):
    """Persist the stable+local halves. Returns True only on a FULLY persisted
    write; False means NO durable candidate half was committed (T-170/T-186).

    While the primary guard is armed (degraded startup: corrupt/rejected/
    unreadable source) NOTHING is written (T-135). While the LOCAL guard is
    armed, the requested volatile half cannot be persisted, so the save is
    refused entirely rather than reporting partial success as full (T-186) -
    unless `bypass_guard` (explicit recovery/import) is used.

    `bypass_guard` recovery writes use promote_bak=False so a known-bad source
    never overwrites the last-good .bak (T-188).

    T-CORE-006: if an existing local file cannot be snapshotted byte-for-byte,
    abort BEFORE any transaction write - a failed rollback would otherwise
    leave a durable candidate local half behind.
    """
    global config_write_blocked, local_write_blocked
    if config_write_blocked and not bypass_guard:
        print("config_store: save skipped (%s); recover config or import a "
              "backup to re-enable saving" % config_write_blocked, file=sys.stderr)
        return False
    if local_write_blocked and not bypass_guard:
        print("config_store: save skipped (config.local.json %s); fix or "
              "reset the local file to re-enable saving" % local_write_blocked,
              file=sys.stderr)
        return False
    stable, local = config_store.split_volatile(config)
    # PERF-004: snapshot each half's current disk bytes for change detection.
    # Only halves that actually changed are written; unchanged halves are
    # skipped entirely to avoid unnecessary filesystem/backup churn.
    local_existed = os.path.exists(CONFIG_LOCAL_FILE)
    local_prev = None
    local_cur_bytes = None
    if local_existed:
        try:
            with open(CONFIG_LOCAL_FILE, "rb") as f:
                local_prev = f.read()
            local_cur_bytes = local_prev
        except OSError:
            print("config_store: cannot snapshot config.local.json for "
                  "rollback; aborting write", file=sys.stderr)
            return False
    stable_cur_bytes = None
    try:
        with open(CONFIG_FILE, "rb") as f:
            stable_cur_bytes = f.read()
    except OSError:
        pass  # missing or unreadable -> must write
    # PERF-004: serialize candidate halves for byte-level comparison.
    try:
        stable_new_bytes = (json.dumps(stable, indent=4) + "\n").encode("utf-8")
        local_new_bytes = (json.dumps(local, indent=4) + "\n").encode("utf-8")
    except (TypeError, ValueError):
        # Serialization failure: fall through to full write (safe fallback).
        stable_new_bytes = None
        local_new_bytes = None
    local_changed = local_cur_bytes != local_new_bytes
    stable_changed = stable_cur_bytes != stable_new_bytes
    if not local_changed and not stable_changed:
        # PERF-004: both halves byte-identical -> no-op, no filesystem churn.
        return True
    # W2-003: persist the pending transaction BEFORE any half is written, so a
    # hard crash between the two atomic writes is recovered to the full pair.
    if not _txn_write(stable_new_bytes if stable_changed else stable_cur_bytes,
                       local_new_bytes if local_changed else local_cur_bytes):
        print("config_store: save aborted - transaction journal could not "
              "be published", file=sys.stderr)
        return False
    local_written = False
    try:
        # Local (volatile) half FIRST, stable half LAST (T-161).
        if local_changed:
            config_store.atomic_write(CONFIG_LOCAL_FILE, local, promote_bak=not bypass_guard)
            local_written = True
        if stable_changed:
            config_store.atomic_write(CONFIG_FILE, stable, promote_bak=not bypass_guard)
    except OSError as e:
        print("config_store: save failed: %s" % e, file=sys.stderr)
        if local_written:
            try:
                if local_existed and local_prev is not None:
                    config_store.atomic_write_bytes(
                        CONFIG_LOCAL_FILE, local_prev, promote_bak=False)
                elif not local_existed:
                    os.remove(CONFIG_LOCAL_FILE)
            except Exception:
                # T-187: a rollback that itself fails is PARTIAL_COMMIT, never
                # an ordinary False - keep the write guards armed so nothing
                # else persists on top of the unknown state.
                config_write_blocked = "partial_commit"
                local_write_blocked = "partial_commit"
                print("config_store: FATAL - rollback failed after partial "
                      "write; write guards armed, journal retained for "
              "next-startup repair", file=sys.stderr)
        # CORE-002: do NOT clear the journal on rollback failure. Retain it
        # so the next launch can attempt recovery from the durable candidate.
        return False
    _txn_clear()
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


def _evaluate_quit_persistence(tab_save_results, saved):
    """W2-001: strict shutdown persistence contract.

    Every tab save and the main-config save must return literal True for the
    persistence to count as successful. A validation/conversion failure returns
    False; any accidental None (or other non-True) ALSO counts as failure so an
    unhandled save result fails CLOSED instead of being misread as success.

    Returns (all_ok, failed_names). `failed_names` lists each component whose
    result is not True, plus "main config" when the main save is not True.
    """
    all_ok = (saved is True) and all(v is True for v in tab_save_results.values())
    failed = [name for name, v in tab_save_results.items() if v is not True]
    if saved is not True:
        failed.append("main config")
    return all_ok, failed


class VacWPlayer:
    def __init__(self):
        self.config = load_config()
        self._applying = False
        self._applying_epoch = None  # CORE-004: generation that owns _applying
        self._probing = False  # PERF-002: one liveness probe at a time
        # T-177: the config the runtime is ACTUALLY running (set only after a
        # successful Apply). Editing/autosaving updates self.config (draft);
        # the watchdog resurrects THIS, never the mutable draft - otherwise
        # whether a draft goes live depends on whether AHK happened to crash.
        self._last_applied_config = None
        # W2-001: serialise every AHK-mutating operation through one lock.
        self._engine_lock = threading.Lock()
        self._engine_epoch = 0
        # W2-010: separate active-runtime truth from last-applied-for-recovery.
        self._active_runtime_config = None
        # W2-001: pending request captured while another Apply/DeathBuy/Stop
        # is in flight. Latest intent wins; a pending full Apply supersedes
        # a pending DeathBuy. Drained by the next apply/stop completion.
        # Shapes: ("apply", candidate) | ("deathbuy", base) | ("stop",)
        self._pending_request = None

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
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.drop_target_register("*")
        self.root.dnd_bind("<<Drop>>", self._on_file_drop)
        self.root.bind("<<AutoSave>>", self._on_auto_save)
        self.root.bind("<<ApplyStart>>", lambda e: self.apply_and_start())
        # W2-001: Death/Buy autobuy edits regenerate the runtime from the
        # LAST-ACCEPTED main config - a dedicated event so the Death Apply and
        # Buy autosave never run the whole-main collect_config commit that would
        # promote unrelated main-tab drafts.
        self.root.bind("<<DeathBuyRefresh>>", self._on_death_buy_apply)
        self._auto_save_timer = None
        self._show_config_warning()

        bar = tk.Frame(self.root, bg=TOKENS["background"])
        bar.pack(side="bottom", fill="x", padx=4, pady=(0, 4))
        self.bar = bar

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
        # Dynamic UI (no scrollbars): fit the window to the ACTIVE tab so no
        # element ever clips out of bounds - the window follows its content
        # and the user never has to resize manually.
        self.notebook.bind("<<NotebookTabChanged>>", self._fit_window_to_content)
        self.root.after(10, self._fit_window_to_content)

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

        self._engine_should_run = False
        # Pre-launch: kill orphaned wr_runtime.ahk from previous crash + clean temps
        ahk_generator.cleanup_stale_before_start()
        ahk_generator.cleanup_temp_ahk_files()
        self.root.after(100, self.apply_and_start)

        self._target_watchdog = None
        self._target_watchdog_exes = None
        # W2-002: the watchdog is owned here and reconciled after every accepted
        # main-config transition (Apply/import) so ON/OFF and target_exe changes
        # take effect live - never frozen at startup.
        self._reconcile_target_watchdog()
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

    def _fit_window_to_content(self, _event=None):
        """Dynamic UI (no scrollbars): the window grows to fit the ACTIVE tab
        so every element stays in view - out-of-bounds elements move by the
        window following its content, never by manual resize. minsize clamps
        manual shrinking below the content so nothing can clip."""
        try:
            self.root.update_idletasks()
        except tk.TclError:
            return
        try:
            need_w = self.notebook.winfo_reqwidth() + 4
            need_h = self.notebook.winfo_reqheight() + 4
            if getattr(self, "bar", None) is not None:
                need_h += self.bar.winfo_reqheight()
            self.root.minsize(need_w, need_h)
            cur_w = self.root.winfo_width()
            cur_h = self.root.winfo_height()
            # grow-only: a larger user-chosen window is preserved, a smaller
            # one is bumped up to the content so nothing is ever cut off.
            if need_w > cur_w or need_h > cur_h:
                self.root.geometry("%dx%d" % (max(need_w, cur_w),
                                              max(need_h, cur_h)))
        except tk.TclError:
            pass

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
        # W2-011: respect the full Windows virtual desktop, not just the primary
        # monitor. Uses proper MONITORINFO structure with cbSize.
        try:
            import ctypes
            import ctypes.wintypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_ulong),
                            ("rcMonitor", RECT),
                            ("rcWork", RECT),
                            ("dwFlags", ctypes.c_ulong)]

            pt = POINT(x, y)
            monitor = ctypes.windll.user32.MonitorFromPoint(
                pt, 2)  # MONITOR_DEFAULTTONEAREST
            if monitor:
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                if ctypes.windll.user32.GetMonitorInfoW(
                        monitor, ctypes.byref(mi)):
                    # Use rcWork (excluding taskbar) for clamping.
                    mx, my = mi.rcWork.left, mi.rcWork.top
                    max_x, max_y = mi.rcWork.right, mi.rcWork.bottom
                    cx = max(mx, min(x, max_x - win_w))
                    cy = max(my, min(y, max_y - win_h))
                    return "%dx%d+%d+%d" % (win_w, win_h, cx, cy)
        except Exception:
            pass
        # Fallback for single-monitor or failure: clamp to primary screen.
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
        # W2-009: write to temp then atomic replace so a failure never truncates
        # an existing export at the destination.
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
                f.write("\n")
            os.replace(tmp_path, path)
            self.status_lbl.config(text=Locale.tr("export_ok"), fg=TOKENS["success"])
        except OSError as e:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
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
        # T-CORE-013 / W2-007: migrate recognized legacy schema BEFORE modern
        # validation, exactly as the primary load (load_config) and .bak
        # recovery (_recover_corrupt_config) paths do. A valid legacy import
        # (mode="xin" with legacy xin data, or top-level ryze/xin keys) must
        # convert before validation instead of being rejected (T-CORE-013).
        imported = _migrate_legacy_config(imported)
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
        # T-CORE-006: save_config exclusively owns guard transitions - import
        # must never overwrite a stronger partial_commit guard with a weaker
        # previous value.
        global config_write_blocked
        previous_guard = config_write_blocked
        if not save_config(imported, bypass_guard=True):
            # Only restore the previous guard when it was weaker (not
            # partial_commit): a failed rollback may have armed partial_commit
            # and import must not downgrade it.
            if previous_guard != "partial_commit":
                config_write_blocked = previous_guard
            messagebox.showerror(Locale.tr("import_failed"),
                                 Locale.tr("import_write_failed", fallback="Import was not saved: config file write failed."))
            return
        self.config = load_config()  # read-back; re-arms guard if disk invalid
        self._rebuild_ui()
        # W2-002 + CORE-003: an accepted import is a main-config transition.
        # Reconcile the target watchdog against the imported snapshot, not
        # the mutable draft.
        self._reconcile_target_watchdog(self.config)
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
        ts = datetime.now().strftime("%Y%m%d_%H%M%S") + ".%06d" % datetime.now().microsecond
        backup_path = os.path.join(backup_dir, "config_%s.json" % ts)
        # W2-010: collision-proof naming - use microseconds to avoid same-second
        # overwrites. If somehow the path exists, append a numeric suffix.
        counter = 1
        while os.path.exists(backup_path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S") + ".%06d" % datetime.now().microsecond
            backup_path = os.path.join(backup_dir, "config_%s_%d.json" % (ts, counter))
            counter += 1
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
        # W2-007: surface local volatile-state degradation/recovery visibly -
        # a locked save caused by the "expendable" local file must not be silent.
        if local_warning == "restored":
            messagebox.showinfo(
                Locale.tr("config_restored_title", fallback="Local State Restored"),
                Locale.tr("config_local_restored",
                          fallback="config.local.json was invalid; restored from its backup (.bak)."))
        elif local_warning == "degraded":
            messagebox.showwarning(
                Locale.tr("config_error_title", fallback="Config Error"),
                Locale.tr("config_local_degraded",
                          fallback="config.local.json is corrupt/unreadable and no usable "
                                   "backup exists. Volatile runtime state is ignored and saving "
                                   "is disabled until the file is fixed or reset."))

    # T-CORE-005: the exact set of tabs owned by main-config import.
    # Death/Buy/Auto/Accept/Surrender tabs own independent engine configs
    # and are never destroyed or restarted by a main-config import.
    _MAIN_OWNED_TABS = frozenset({
        "tab_main", "tab_combos", "tab_champions", "tab_minimap", "tab_afkfarm",
    })

    def _rebuild_ui(self):
        """Rebuild ONLY main-owned tabs (Main/Combos/Champions/Minimap/AFK).
        Death/Accept/Surrender/Auto/Buy tabs own independent engine configs and
        must not be destroyed or restarted by a main-config import (T-W2-004).

        T-CORE-005: the loop now correctly unpacks 3-tuples and only touches
        main-owned tabs. Independent engine tabs retain their objects, runners,
        pending state, and tab order.
        """
        # Destroy and recreate only main-owned tabs in-place. CORE-005: each
        # recreated tab is INSERTED at its canonical _tab_specs position -
        # notebook.add() appended, scrambling the order so _restore_active_tab
        # resolved the persisted numeric index against the wrong layout.
        position = {attr: i for i, (attr, _k, _f) in enumerate(self._tab_specs)}
        for attr, key, factory in self._tab_specs:
            if attr not in self._MAIN_OWNED_TABS:
                continue
            tab = getattr(self, attr, None)
            if tab is not None:
                self.notebook.forget(tab)
                tab.destroy()
                setattr(self, attr, None)
            # Recreate this tab with the factory.
            new_tab = factory()
            self.notebook.insert(position[attr], new_tab, text=Locale.tr(key))
            setattr(self, attr, new_tab)
        self._refresh_mode_box()
        self._restore_active_tab()
        self._apply_locale()

    def _update_ahk_dot(self, running):
        if running == "unknown":
            color = TOKENS.get("warning", "#7A7A20")
        else:
            color = TOKENS["success"] if running else TOKENS["danger"]
        self.ahk_dot.itemconfig(self.ahk_dot_id, fill=color)

    def apply_and_start(self):
        # W2-001: an in-flight Apply captures the latest draft as a pending
        # request instead of dropping it. A pending full Apply supersedes any
        # pending DeathBuy refresh.
        if self._applying:
            # W2-001: coalesce to latest state. A pending full Apply is
            # refreshed with the newest draft; a pending DeathBuy is
            # superseded by the full Apply.
            self.collect_config()
            pending_candidate = copy.deepcopy(self.config)
            self._pending_request = ("apply", pending_candidate)
            return
        with self._engine_lock:
            self._engine_epoch += 1
            epoch = self._engine_epoch
        self._applying = True
        # CORE-004: this generation owns _applying; the same epoch flows through
        # the worker and the finalization callback so a stale callback can only
        # release the flag if it is still the owning generation.
        self._applying_epoch = epoch
        self.collect_config()
        # T-185: freeze ONE immutable candidate on the main thread. The same
        # snapshot flows through save -> worker -> generate -> done; a GUI
        # autosave/mutation of self.config mid-transaction can never change
        # what gets generated or what is recorded as last-applied.
        candidate = copy.deepcopy(self.config)
        if not save_config(candidate):
            # Degraded state (corrupt/unreadable config, guard armed): the
            # candidate must not overwrite the source, and automation must not
            # run on unvalidated defaults (T-135).
            self._applying = False
            self._applying_epoch = None
            self.status_lbl.config(
                text=Locale.tr("config_locked",
                               fallback="Config locked (corrupt/unreadable); fix config or import a backup"),
                fg=TOKENS["danger"])
            return
        self._engine_should_run = True
        self.status_lbl.config(text=Locale.tr("generating"), fg=TOKENS["warning"])
        threading.Thread(target=self._apply_worker, args=(candidate, epoch),
                         daemon=True).start()

    def _on_death_buy_apply(self, _event=None):
        """W2-001: dedicated AHK refresh for Death/Buy autobuy edits.

        Death/Buy autosave autobuy/quickbuy fields into deathwatch_config.json,
        which ahk_builder._gen_autobuy re-reads at every generation. This handler
        regenerates the runtime from the LAST-ACCEPTED main config (never the
        mutable editor draft) WITHOUT collect_config(), so a Death Apply or Buy
        autosave cannot promote unrelated main-tab drafts. Reuses the
        _apply_worker(candidate, epoch) pattern: same lock serialisation, same
        epoch gate, same generate_and_run.
        """
        if self._applying:
            # A pending full Apply already covers this DeathBuy intent.
            if not self._pending_is_apply:
                base = (self._active_runtime_config or self._last_applied_config
                        or self.config)
                self._pending_request = ("deathbuy", copy.deepcopy(base))
            return
        with self._engine_lock:
            self._engine_epoch += 1
            epoch = self._engine_epoch
        self._applying = True
        self._applying_epoch = epoch
        base = (self._active_runtime_config or self._last_applied_config
                or self.config)
        candidate = copy.deepcopy(base)
        self._engine_should_run = True
        self.status_lbl.config(text=Locale.tr("generating"), fg=TOKENS["warning"])
        threading.Thread(target=self._apply_worker, args=(candidate, epoch),
                         daemon=True).start()

    def _apply_worker(self, candidate, epoch):
        ok, msg = False, "superseded"
        try:
            # W2-001: lock serialises generate_and_run against concurrent
            # Stop/Quit; epoch check prevents stale results from posting.
            with self._engine_lock:
                if epoch != self._engine_epoch:
                    # Superseded before we could even generate - report back so
                    # the Tk thread releases OUR _applying flag. A bare return
                    # here (the old code) stranded _applying=True forever and
                    # blocked every future Apply (CORE-004 defect #1).
                    self.root.after(0, self._apply_done, False,
                                    "Apply superseded by Stop", None, epoch)
                    return
                try:
                    ok, msg = ahk_generator.generate_and_run(candidate)
                except Exception as e:
                    print("ahk apply worker failed: %s" % e, file=sys.stderr)
                    ok, msg = False, "Apply failed: %s" % e
                # NOTE: no second epoch check here. The completion callback
                # carries our epoch and the Tk thread re-checks against the live
                # epoch, closing the race where Stop bumps the epoch and kills
                # the runtime between this point and the callback (CORE-004 #2).
        except Exception:
            self.root.after(0, self._apply_done, False,
                            "lock destroyed during quit", None, epoch)
            return
        try:
            self.root.after(0, self._apply_done, ok, msg, candidate, epoch)
        except Exception:
            pass  # Tk destroyed during quit

    def _apply_done(self, ok, msg, candidate=None, epoch=None):
        # CORE-004: generation-aware finalization. A stale callback (epoch != the
        # live epoch) must never commit candidate/runtime truth, and must only
        # release _applying when THIS worker is still the owning generation.
        if epoch is not None and epoch != self._engine_epoch:
            if self._applying_epoch == epoch:
                self._applying = False
                self._applying_epoch = None
            return
        # Current generation: commit truth (if accepted) and release _applying.
        # A rejected candidate must not paint the last-good runtime dead: the
        # AHK dot reflects the ACTUAL runtime state, not the apply result.
        # is_running() may be None (UNKNOWN) - never claim alive on unknown.
        running = ok or ahk_generator.is_running() is True
        if not ok and running:
            msg = msg + " - last-good AHK still running"
        if ok and candidate is not None:
            # T-177: only an ACCEPTED candidate becomes the last-applied state
            # the watchdog resurrects; a rejected candidate never does.
            self._last_applied_config = copy.deepcopy(candidate)
            # W2-010: verified successful Apply sets active runtime truth.
            self._active_runtime_config = copy.deepcopy(candidate)
            # T-CORE-012: write the accepted PvP trigger to a process-shared
            # file so deathwatch's PvP restart consumes the exact last-applied
            # combo, never a stale config.json draft.
            try:
                import deathwatch
                if not deathwatch._write_runtime_trigger(candidate):
                    print("config_store: WARNING - PvP runtime trigger not "
                          "published; DeathWatch PvP restart may be stale",
                          file=sys.stderr)
            except Exception as e:
                print("config_store: WARNING - PvP runtime trigger write failed: "
                      "%s" % e, file=sys.stderr)
        self.status_lbl.config(text=self._short_status(msg),
                               fg=TOKENS["success"] if ok else TOKENS["danger"])
        self._update_ahk_dot(running)
        if ok and candidate is not None:
            # W2-002 + CORE-003: an accepted Apply is a main-config transition.
            # Reconcile the target watchdog against the accepted candidate,
            # NOT the mutable draft (self.config).
            self._reconcile_target_watchdog(candidate)
        self._applying = False
        self._applying_epoch = None
        self._drain_pending()

    @staticmethod
    def _short_status(msg, limit=64):
        """Cap the one-line status text so a long warning/dropped list cannot
        push the bottom bar's buttons out of the window."""
        msg = str(msg)
        return msg if len(msg) <= limit else msg[:limit - 1] + "…"

    def _reconcile_target_watchdog(self, cfg=None):
        """W2-002: reconcile the target-gone watchdog against the CURRENT
        accepted main-config state. Called at startup and after every accepted
        main-config transition (Apply success / import success).

        OFF cancels the running watcher; ON starts or retargets exactly one
        watcher. Old generations are invalidated so a superseded watcher can
        never fire shutdown after replacement."""
        source = cfg if cfg is not None else self.config
        toggles = source.get("toggles", {})
        want = bool(toggles.get("exit_when_bs_gone", True))
        exes = [toggles.get("target_exe") or "HD-Player.exe"]
        current = getattr(self, "_target_watchdog", None)
        current_exes = getattr(self, "_target_watchdog_exes", None)
        if current is not None:
            if not want or current_exes != exes:
                current.stop()
                self._target_watchdog = None
                self._target_watchdog_exes = None
            else:
                return
        if want:
            self._target_watchdog = single_instance.start_target_watchdog(
                exes,
                lambda: self.root.after(0, self.quit_app, None, None, True),
                interval_sec=3.0, grace_ticks=2, min_uptime_sec=15.0)
            self._target_watchdog_exes = exes

    def stop_engine(self):
        self._engine_should_run = False
        self.status_lbl.config(text=Locale.tr("stopping", fallback="Stopping…"),
                               fg=TOKENS["warning"])
        # PERF-002: the blocking stop_ahk identity probe (10s PowerShell timeout
        # + retry) runs off-Tk. The UI paints "Stopping…" immediately and the
        # worker marshals the authoritative result back via root.after, so a
        # degraded identity path can never freeze the window.
        if self._applying:
            # Stop supersedes any pending restart; the in-flight op observes
            # the new epoch and bails out without committing truth.
            self._pending_request = ("stop",)
            with self._engine_lock:
                self._engine_epoch += 1
            return
        with self._engine_lock:
            self._engine_epoch += 1
            epoch = self._engine_epoch
        self._applying = True
        self._applying_epoch = epoch

        def _worker():
            try:
                with self._engine_lock:
                    res = ahk_generator.stop_ahk()
            except Exception as e:
                print("stop_engine worker failed: %s" % e, file=sys.stderr)
                res = "UNKNOWN_IDENTITY"
            try:
                self.root.after(0, self._stop_engine_done, res, epoch)
            except tk.TclError:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_engine_done(self, res, epoch):
        if epoch != self._engine_epoch:
            return  # superseded by a newer stop/apply - its result will land
        if res in ("STOPPED", "ALREADY_STOPPED"):
            self._active_runtime_config = None  # CORE-003: clear only after proven stop
            self.status_lbl.config(text=Locale.tr("engine_stopped"), fg=TOKENS["textPrimary"])
            self._update_ahk_dot(False)
            try:
                import deathwatch
                if not deathwatch._set_runtime_inactive():
                    print("config_store: WARNING - PvP runtime inactive state not "
                          "persisted; DeathWatch may re-arm PvP after stop",
                          file=sys.stderr)
            except Exception as e:
                print("config_store: WARNING - PvP runtime inactive write failed: "
                      "%s" % e, file=sys.stderr)
        else:
            self.status_lbl.config(text=Locale.tr("stop_failed", fallback="Stop Unknown/Failed"),
                                   fg=TOKENS.get("error", "#f00"))
            ahk_is = ahk_generator.is_running()
            if ahk_is is None:
                self._update_ahk_dot("unknown")
            else:
                self._update_ahk_dot(ahk_is)
        self._applying = False
        self._applying_epoch = None
        self._drain_pending()

    def _drain_pending(self):
        """W2-001: drain pending. Safe when _pending_request is unset (test
        fixtures that bypass __init__ still hit this path)."""
        req = getattr(self, "_pending_request", None)
        if req is None:
            return
        self._pending_request = None
        kind, arg = req
        with self._engine_lock:
            self._engine_epoch += 1
            epoch = self._engine_epoch
        if kind == "stop":
            self._applying = True
            self._applying_epoch = epoch
            self._engine_should_run = False

            def _worker():
                try:
                    with self._engine_lock:
                        res = ahk_generator.stop_ahk()
                except Exception as e:
                    print("stop_engine worker failed: %s" % e, file=sys.stderr)
                    res = "UNKNOWN_IDENTITY"
                try:
                    self.root.after(0, self._stop_engine_done, res, epoch)
                except tk.TclError:
                    pass

            threading.Thread(target=_worker, daemon=True).start()
            return
        # apply / deathbuy
        self._applying = True
        self._applying_epoch = epoch
        self._engine_should_run = True
        self.status_lbl.config(text=Locale.tr("generating"), fg=TOKENS["warning"])
        threading.Thread(target=self._apply_worker, args=(arg, epoch),
                         daemon=True).start()

    @property
    def _pending_is_apply(self):
        """W2-001: True when the pending request is a full Apply."""
        req = getattr(self, "_pending_request", None)
        return req is not None and req[0] == "apply"

    def _engine_watchdog(self):
        # PERF-002: liveness probe runs off-Tk when the cheap fast-path
        # (launched Popen handle) is unavailable. The probe is serialized
        # through _probing so at most one blocking scan runs at a time.
        if getattr(self, "_engine_should_run", False) and not self._applying and not self._probing:
            # Fast path: the trusted launched handle is alive -> no probe needed.
            if ahk_generator._last_launched_proc is not None:
                try:
                    if ahk_generator._last_launched_proc.poll() is None:
                        try:
                            self.root.after(3000, self._engine_watchdog)
                        except tk.TclError:
                            pass
                        return
                except Exception:
                    pass
            # Fast path dead or absent: launch an off-Tk probe.
            self._probing = True
            threading.Thread(target=self._probe_and_maybe_restart, daemon=True).start()
        try:
            self.root.after(3000, self._engine_watchdog)
        except tk.TclError:
            pass

    def _probe_and_maybe_restart(self):
        """PERF-002: run the potentially-blocking is_running() off the Tk
        thread. Post the result back for _probe_result to handle."""
        try:
            running = ahk_generator.is_running()
        except Exception:
            running = None
        try:
            self.root.after(0, self._probe_result, running)
        except Exception:
            # Tk destroyed during quit: clear _probing so it never sticks.
            self._probing = False

    def _probe_result(self, running):
        """PERF-002: Tk-thread callback after liveness probe."""
        self._probing = False
        if running is not False:
            return  # running or UNKNOWN: no restart needed
        if not self._engine_should_run or self._applying:
            return
        # VERIFIED-False: restart trigger.
        self._applying = True
        self._applying_epoch = self._engine_epoch
        self.status_lbl.config(text=Locale.tr("auto_restarting"), fg=TOKENS["warning"])
        last = getattr(self, "_last_applied_config", None)
        if last is None:
            self._applying = False
            self.status_lbl.config(
                text=Locale.tr("config_locked",
                               fallback="No last-applied config; engine standby"),
                fg=TOKENS["danger"])
            return
        frozen = copy.deepcopy(last)
        epoch = self._engine_epoch
        threading.Thread(target=self._watchdog_worker, args=(frozen, epoch),
                         daemon=True).start()

    def _watchdog_worker(self, cfg=None, epoch=None):
        # T-177/T-185: resurrect the LAST-APPLIED config, never the mutable
        # editor draft. The candidate is normally frozen by _engine_watchdog on
        # the main thread; the fallback here guards direct calls (tests).
        if cfg is None:
            last = getattr(self, "_last_applied_config", None)
            cfg = last if last is not None else self.config
            epoch = getattr(self, "_engine_epoch", 0)
        ok, msg = False, "superseded"
        try:
            # W2-001: lock serialises against Stop/Quit; epoch gates stale posts.
            with self._engine_lock:
                if epoch is not None and epoch != self._engine_epoch:
                    # Superseded before generate - report back so the Tk thread
                    # releases OUR _applying flag (CORE-004: never strand it).
                    self.root.after(0, self._watchdog_done, False,
                                    "Restart superseded by Stop", epoch)
                    return
                try:
                    ok, msg = ahk_generator.generate_and_run(cfg)
                except Exception as e:
                    print("ahk watchdog worker failed: %s" % e, file=sys.stderr)
                    ok, msg = False, "Auto-restart failed: %s" % e
                # No second epoch check: the callback carries our epoch and the
                # Tk thread re-checks, closing the Stop-during-callback race.
        except Exception:
            self.root.after(0, self._watchdog_done, False,
                            "lock destroyed during quit", epoch)
            return
        try:
            self.root.after(0, self._watchdog_done, ok, msg, epoch)
        except Exception:
            pass

    def _watchdog_done(self, ok, msg, epoch=None):
        # CORE-004: generation-aware finalization (see _apply_done).
        if epoch is not None and epoch != self._engine_epoch:
            if self._applying_epoch == epoch:
                self._applying = False
                self._applying_epoch = None
            return
        running = ok or ahk_generator.is_running() is True
        self.status_lbl.config(text=self._short_status(Locale.tr("auto_restarted") + " " + msg),
                               fg=TOKENS["warning"])
        self._update_ahk_dot(running)
        self._applying = False
        self._applying_epoch = None

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

        # W2-010: show hotkeys from the ACTIVE runtime config, not the
        # last-applied-for-recovery or the mutable draft.
        active = getattr(self, "_active_runtime_config", None)
        if active is None:
            w(Locale.tr("hk_no_active_runtime", fallback="No active runtime - hotkeys unknown"))
        else:
            toggles = active.get("toggles", {})
            champs = active.get("champions", {})
            minimap = active.get("minimap", {})
            afkfarm = active.get("afkfarm", {})

            w("=== " + Locale.tr("hk_global") + " ===")
            w("  " + Locale.tr("hk_stop_key") + ":     %s" % toggles.get("stop_key", "s"))
            w("  " + Locale.tr("hk_anti_afk") + ":     Ctrl+G (" + Locale.tr("hk_in_game_toggle") + ")")
            w("  " + Locale.tr("hk_mode") + ":         %s" % active.get("mode", "general"))
            w("  " + Locale.tr("hk_target_exe") + ":   %s" % toggles.get("target_exe", "HD-Player.exe"))
            w("")

            w("=== " + Locale.tr("hk_champ_triggers") + " ===")
            mode = active.get("mode", "general")
            if mode != "general":
                entry = champs.get(mode, {})
                for slot in ("wave", "jungle", "pvp"):
                    trig = entry.get("trigger_" + slot, "")
                    if trig:
                        keys = entry.get("keys_" + slot, "")
                        w("  %s: %s -> %s" % (slot, trig, keys))
            else:
                for c in active.get("combos", []):
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
        # Reliable shutdown: serialise against in-flight _apply_worker /
        # _watchdog_worker AND the watchdog's restart probe.
        ahk_stopped = False
        try:
            with self._engine_lock:
                self._engine_epoch += 1
                # T-CORE: keep our own runtime dead even if an identity scan
                # flaps once - retry the stop so a transient UNKNOWN/KILL_FAILED
                # cannot leave wr_runtime.ahk alive in the tray.
                res = ahk_generator.stop_ahk()
                if res in ("UNKNOWN_IDENTITY", "KILL_FAILED"):
                    res = ahk_generator.stop_ahk()
                if res == "KILL_FAILED":
                    # Last resort: force-kill any remaining verified PIDs
                    state, pids = ahk_generator._find_our_pids(force=True)
                    if pids:
                        ahk_generator._force_kill_ahk_processes(pids)
                ahk_stopped = res in ("STOPPED", "ALREADY_STOPPED")
        except Exception as e:
            print("stop_everything: AHK stop failed: %s" % e, file=sys.stderr)
        if ahk_stopped:
            self._active_runtime_config = None  # CORE-003: clear only after proven stop
        # CORE-003: aggregate child monitor stops; only paint OFF what is
        # proven stopped. A failed stop keeps its monitor ON/error state live
        # instead of representing a surviving process as OFF.
        children_stopped = True
        for tab in (self.tab_death, self.tab_auto, self.tab_accept,
                    self.tab_surrender):
            if tab is not None:
                if not tab.stop_all():
                    children_stopped = False
        if ahk_stopped and children_stopped:
            self._update_ahk_dot(False)
        else:
            ahk_is = ahk_generator.is_running()
            self._update_ahk_dot(ahk_is if ahk_is is not None else "unknown")
        # W2-002: publish inactive idempotently at shutdown. stop_ahk only
        # stops the process; the inactive sidecar is what makes the reader
        # fail-safe. Idempotent across atexit's second-call pattern.
        if ahk_stopped:
            try:
                import deathwatch
                if not deathwatch._set_runtime_inactive():
                    print("config_store: WARNING - PvP runtime inactive not "
                          "persisted at shutdown", file=sys.stderr)
            except Exception as e:
                print("config_store: WARNING - PvP inactive write failed at "
                      "shutdown: %s" % e, file=sys.stderr)
        # Exit cleanup: remove orphaned temp files
        ahk_generator.cleanup_temp_ahk_files()
        return ahk_stopped and children_stopped

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

    def hide_window(self):
        """X button -> hide to tray (not quit).

        The automation runtime (wr_runtime.ahk) must not outlive a closed
        window: stop it here so wr_runtime.ahk exits with the window. Without
        this the engine watchdog (_engine_watchdog) keeps _engine_should_run
        True and resurrects wr_runtime.ahk every cycle - so a manually killed
        runtime came back and a "closed" app left the runtime running forever."""
        if self.tray_icon:
            try:
                self.stop_engine()
            except Exception as e:
                print("hide_window: stop_engine failed: %s" % e, file=sys.stderr)
            try:
                self.root.withdraw()
            except tk.TclError:
                pass
        else:
            self.quit_app()

    def quit_app(self, icon=None, item=None, force=False):
        # T-CORE-006/T-CORE-007: persistence first, tray+teardown after.
        # Collect ALL save results before any teardown decision.
        self.collect_config()
        tab_save_results = {}
        for tab in (self.tab_death, self.tab_buy, self.tab_auto,
                    self.tab_accept, self.tab_surrender):
            if tab and hasattr(tab, "save"):
                tab_save_results[tab.__class__.__name__] = tab.save(silent=True)
        saved = save_config(self.config)
        # W2-001: strict contract - every tab save AND the main config save must
        # return literal True. A False (validation failure) or accidental None
        # (any non-True) counts as failure and is named in `failed` so shutdown
        # fails CLOSED instead of silently discarding edits.
        all_saves_ok, failed = _evaluate_quit_persistence(tab_save_results, saved)
        if not all_saves_ok and not force:
            # Normal quit: persistence failure aborts shutdown so edits are not
            # silently discarded. Report which config failed.
            print("config_store: quit aborted - save failed (%s); app stays alive"
                  % ", ".join(failed), file=sys.stderr)
            return
        if not all_saves_ok and force:
            # Force quit (target-gone safety): log failures but proceed.
            print("config_store: force quit with save failures: %s"
                  % ", ".join(failed), file=sys.stderr)
        # T-CORE-006: tray stops AFTER persistence succeeds; the GUI stays
        # usable if persistence fails on a normal quit.
        if self.tray_icon:
            self.tray_icon.stop()
        self.stop_everything()
        # W2-002: belt-and-braces inactive publish in case stop_everything
        # bailed out before the AHK-stopped branch (force quit, etc.).
        try:
            import deathwatch
            deathwatch._set_runtime_inactive()
        except Exception:
            pass
        self.root.after(0, self.root.destroy)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    import engine_config
    engine_config.setup_logging()
    # W2-002: publish inactive fail-safe BEFORE any auto-starting DeathWatch
    # child can read a stale sidecar from a prior session. Idempotent and
    # safe even if deathwatch module import fails.
    try:
        import deathwatch
        deathwatch._set_runtime_inactive()
    except Exception as e:
        print("config_store: startup inactive publish failed: %s" % e,
              file=sys.stderr)
    single_instance.ensure_single_instance("wr_assistant", replace=True)
    app = VacWPlayer()
    atexit.register(app.stop_everything)
    app.run()
