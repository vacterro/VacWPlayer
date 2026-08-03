import json
import os
import re
import sys

"""Renders wr_runtime.ahk from config and manages its process.

wr_runtime.ahk is a GENERATED file - never hand-edit it. All input handling
(combo spam, mouse remap, movement) runs in AutoHotkey v1 because emulators
need SendMode Event and AHK's hook layer is proven; Python only writes the
script and owns its lifetime by PID.
"""
BASE = os.path.dirname(os.path.abspath(__file__))
AHK_NAME = "wr_runtime.ahk"
AHK_PATH = os.path.join(BASE, AHK_NAME)
PID_PATH = os.path.join(BASE, ".ahk.pid")
AHK_EXE_CANDIDATES = [
    os.path.join(BASE, "AutoHotkeyU64.exe"),  # bundled portable
    r"C:\Program Files\AutoHotkey\AutoHotkeyU64.exe",
    r"C:\Program Files\AutoHotkey\AutoHotkey.exe",
    r"C:\Program Files (x86)\AutoHotkey\AutoHotkeyU64.exe",
    r"C:\Program Files (x86)\AutoHotkey\AutoHotkey.exe",
]
def parse_steps(keys_str, default_interval):
    """'q,e:120,{Space}:200' -> [('q',default), ('e',120), ('{Space}',200)]

    The delay is the pause AFTER that key before the next step fires. A step
    without ':ms' uses the combo's interval.
    """
    steps = []
    for raw in keys_str.split(","):
        raw = raw.strip()
        if not raw:
            continue
        key, delay = raw, default_interval
        # Only split on the LAST colon so '{:}:80' style keys stay intact.
        if ":" in raw and not raw.endswith(":"):
            head, tail = raw.rsplit(":", 1)
            if tail.isdigit() and head:
                key, delay = head, int(tail)
        steps.append((key, delay))
    return steps

def _is_plain_key(trigger):
    """True for single keys usable with GetKeyState (no hotkey modifiers)."""
    return bool(trigger and re.fullmatch(r"[A-Za-z0-9]|F\d{1,2}", trigger))


_MOD_PREFIX = "!^+#*~$<>"


def _base_key(trigger):
    """'!F9' -> 'F9'. Strips hotkey modifier/behaviour prefixes."""
    return (trigger or "").strip().lstrip(_MOD_PREFIX)


def _guard_variant(trigger):
    """Hotkey prefix that swallows a *carried-over* press of `trigger`.

    Returns (variant, base_key), or None when the key must not be guarded.

    The pedal is used outside the game too, so a blanket block is wrong. What
    has to die is only the press that started inside the game and is still
    physically down when the game stops being the active window - a foot
    resting on the pedal through a death-minimize, whose auto-repeat otherwise
    rains into whatever app is now in front. These variants sit behind
    `#If GuardCarry(base)`, which is true only for that carried press: release
    the pedal and the guard evaporates, so the very next press outside the game
    reaches Windows untouched.

    F13-F24 get the wildcard form (`*F13`) so no modifier combination leaks.
    Anything else keeps its exact modifier list, so system chords that merely
    share a base key (Alt+F4, Alt+Tab) are never shadowed. Plain typeable keys
    (letters, digits) are never guarded at all.
    """
    trig = (trigger or "").strip()
    if not trig:
        return None
    base = _base_key(trig)
    mods = trig[:len(trig) - len(base)]
    if re.fullmatch(r"[Ff](1[3-9]|2[0-4])", base):
        return "*" + base, base
    if re.fullmatch(r"[Ff]\d{1,2}", base):
        # Keep '~' (pass-through) out of the guard - the point is to swallow.
        mods = "".join(ch for ch in mods if ch in "!^+#")
        return mods + base, base
    return None


def _guarded_triggers(toggles, combos, minimap, afk_k):
    """Ordered, de-duplicated (variant, base_key) pairs for every trigger."""
    if not toggles.get("guard_outside_game", True):
        return []
    trigs = [c.get("trigger", "") for c in combos]
    if isinstance(minimap, dict):
        for key, entry in minimap.items():
            if key == "_order" or not isinstance(entry, dict):
                continue
            trigs.append(entry.get("trigger", ""))
    if afk_k:
        trigs.append(afk_k)
    out, seen = [], set()
    for t in trigs:
        g = _guard_variant(t)
        if g and g[0] not in seen:
            seen.add(g[0])
            out.append(g)
    return out


def _carry_set(trigger, value):
    """AHK statement marking `trigger`'s base key as pressed from in-game."""
    base = _base_key(trigger)
    if not base:
        return None
    return 'Carry["%s"] := %s' % (base, "true" if value else "false")


def _send_for(key, shift):
    """Shift-wrap ability letters (self-cast in Wild Rift), send others raw."""
    if shift and key.lower() in ("q", "w", "e", "r", "u", "i", "o", "p"):
        return "{Blind}{Shift down}" + key + "{Shift up}"
    return "{Blind}" + key

def _hotkey_block(trig, flag, last, step_var, guarded=True, move_when_pressed=False):
    nd = flag + "_NextDelay"
    # Carry is what tells the outside-the-game guard "this press began in the
    # game" - set on every down, cleared on the matching up.
    set_on = ("    " + _carry_set(trig, True) + "\n") if guarded else ""
    set_off = ("    " + _carry_set(trig, False) + "\n") if guarded else ""
    
    move_on = ""
    move_off = ""
    if move_when_pressed:
        # Hold RButton (move) for as long as the combo trigger is held, via the
        # shared MoveRefs counter so combo-hold and LMB-hold never fight each
        # other: releasing one source keeps the others moving.
        move_on = "        MoveRefs += 1\n        CheckMovement()\n"
        move_off = "    MoveRefs := (MoveRefs > 0 ? MoveRefs - 1 : 0)\n    CheckMovement()\n"

    return (
        "*" + trig + "::\n"
        + set_on +
        "    if (!" + flag + "_Held) {\n"
        "        " + flag + "_Held := true\n"
        "        " + last + " := 0\n"
        "        " + step_var + " := 0\n"
        "        " + nd + " := 0\n"
        + move_on +
        "        SetTimer, MasterSpammer, 15\n"
        "    }\n"
        "return\n"
        "*" + trig + " Up::\n"
        + set_off +
        "    " + flag + "_Held := false\n"
        "    " + step_var + " := 0\n"
        + move_off +
        "return\n"
    )

def _tag(mode):
    """AHK variable names allow only word chars, champion slugs already are."""
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in mode)

def _active_combos(config):
    """Champion mode decides which combo set is live - exactly one owner per
    trigger key, so F13-F15 never collide between General and any champion."""
    mode = config.get("mode", "general")
    combos = []
    if mode == "general":
        for i, c in enumerate(config.get("combos", [])):
            keys = parse_steps(c.get("keys", ""), int(c.get("interval", 50)))
            if c.get("trigger") and keys:
                combos.append({
                    "trigger": c["trigger"], "steps": keys,
                    "shift": bool(c.get("shift", True)), "tag": "gen%d" % i,
                    "move_when_pressed": bool(c.get("move_when_pressed", False)),
                })
    else:
        cfg = config.get("champions", {}).get(mode, {})
        interval = int(cfg.get("interval", 50))
        use_shift = bool(cfg.get("use_shift", True))
        qwer_uiop = bool(cfg.get("qwer_as_uiop", False))
        
        for slot in ("wave", "jungle", "pvp"):
            trig = cfg.get("trigger_" + slot)
            keys_raw = cfg.get("keys_" + slot, "")
            keys = parse_steps(keys_raw, interval)
            move_when_pressed = cfg.get("move_when_pressed_" + slot, False)
            
            if qwer_uiop:
                m = {"q":"u", "w":"i", "e":"o", "r":"p", "Q":"U", "W":"I", "E":"O", "R":"P"}
                keys = [(m.get(k, k), d) for k, d in keys]

            if trig and keys:
                combos.append({
                    "trigger": trig, "steps": keys, "shift": use_shift,
                    "tag": _tag(mode) + "_" + slot,
                    "move_when_pressed": move_when_pressed,
                })
    seen, unique, dropped = set(), [], []
    for c in combos:
        if c["trigger"] in seen:
            dropped.append(c["tag"])
            continue
        seen.add(c["trigger"])
        unique.append(c)
    return unique, dropped

def _gen_header(a, target_exe, combos, afk):
    """Prologue: directives, legacy cleanup, globals, watchdog timer."""
    a.append("#NoEnv")
    a.append("#SingleInstance Force")
    a.append("#Persistent")
    a.append("#MaxThreadsPerHotkey 1")
    a.append("#InstallMouseHook")
    a.append("#MaxHotkeysPerInterval 200")
    a.append("#HotkeyInterval 1000")
    a.append("")
    a.append("DetectHiddenWindows, On")
    a.append("SetTitleMatchMode, RegEx")
    a.append("WinGet, id, List, i)^wr.*\\.ahk - AutoHotkey")
    a.append("Loop, %id%")
    a.append("{")
    a.append("    this_id := id%A_Index%")
    a.append("    WinGet, this_pid, PID, ahk_id %this_id%")
    a.append('    if (this_pid != DllCall("GetCurrentProcessId"))')
    a.append("        WinClose, ahk_id %this_id%")
    a.append("}")
    a.append("DetectHiddenWindows, Off")
    a.append("CoordMode, Mouse, Client")
    a.append("CoordMode, Pixel, Client")
    a.append("")
    a.append("SendMode Event")
    a.append("SetKeyDelay, -1, 15")
    a.append("SetBatchLines -1")
    a.append("")
    a.append("global LMB_Held := false")
    a.append("global StopActive := false")
    a.append("global SpaceActive := false")
    a.append("global AntiAFK := false")
    a.append("global ManualAimActive := false")
    a.append("global LastSpace := 0")
    a.append("global LastAntiAFK := 0")
    a.append("global Carry := {}")
    a.append("global NeedCleanup := false")
    a.append("global WasActive := false")
    a.append("global PhantomArm := \"\"")
    a.append("global MoveToggle := false")
    a.append("global MoveRefs := 0")
    a.append("global LMB_Pass := false")
    for c in combos:
        flag = "P_" + c["tag"]
        a.append("global " + flag + "_Held := false")
        a.append("global Last_" + c["tag"] + " := 0")
        a.append("global Step_" + c["tag"] + " := 0")
        a.append("global " + flag + "_NextDelay := 0")
    if isinstance(afk, dict) and afk.get("enabled"):
        t = (afk.get("toggle_key") or "").strip()
        if t:
            a.append("global P_afk_Active := false")
            a.append("global P_afk_Cycle := 0")
            a.append("global P_afk_Timer := 0")
            a.append("global P_afk_Step := 0")
            a.append("global P_afk_LastCombo := 0")
            a.append("global P_afk_NextDelay := 0")
            a.append("global P_afk_NeedRestart := false")
            a.append("global P_afk_WasDead := false")
            a.append("global P_afk_DeathCheck := 0")
            a.append("global P_afk_PosIndex := 0")
            a.append("global P_afk_LastMove := 0")
    a.append("")
    a.append("global ParentPID := %1%")
    a.append('ahkPid := DllCall("GetCurrentProcessId")')
    a.append('FileDelete, %A_ScriptDir%\\.ahk.pid')
    a.append('FileAppend, %ahkPid%, %A_ScriptDir%\\.ahk.pid')
    a.append("SetTimer, Watchdog, 2000")
    a.append("SetTimer, MasterSpammer, 15")
    a.append("SetTimer, FocusWatch, 50")
    if isinstance(afk, dict) and afk.get("enabled") and (afk.get("toggle_key") or "").strip():
        a.append("SetTimer, AFKFarmLogic, 15")
    a.append("")

def _gen_autobuy(a, target_exe, config):
    """Optional deathwatch quick-buy block (from deathwatch_config.json)."""
    try:
        dw_path = os.path.join(os.path.dirname(__file__), "deathwatch_config.json")
        with open(dw_path) as f:
            dw_cfg = json.load(f)
        if not dw_cfg.get("autobuy_after_b"):
            return
        qb_key = dw_cfg.get("quickbuy_key", "")
        qb_presses = int(dw_cfg.get("quickbuy_presses", 1))
        buy_delay_ms = int(float(dw_cfg.get("buy_after_b_delay_sec", 5.5)) * 1000)
        win_title = dw_cfg.get("window_title", "")
        if not qb_key or not win_title:
            return
        if len(qb_key) == 1 and 'A' <= qb_key.upper() <= 'Z':
            qb_vk = "vk%02X" % ord(qb_key.upper())
        else:
            qb_vk = qb_key
        controlsend = dw_cfg.get("controlsend_z", False)
        a.append(f"#IfWinActive, {win_title}")
        a.append("~b::")
        a.append("    SetTimer, DoAutoBuy, Off")
        a.append(f"    SetTimer, DoAutoBuy, -{buy_delay_ms}")
        a.append("return\n")
        a.append("DoAutoBuy:")
        a.append(f"    if (!WinActive(\"{win_title}\"))")
        a.append("        return")
        a.append(f"    Loop, {qb_presses} {{")
        if controlsend:
            a.append(f"        ControlSend, , {{{qb_vk}}}, ahk_exe {target_exe}")
        else:
            a.append(f"        SendEvent {{Blind}}{{{qb_vk}}}")
        a.append("        Sleep 50")
        a.append("    }")
        if controlsend:
            a.append(f"    ControlSend, , {{Shift Up}}{{Ctrl Up}}{{Alt Up}}{{LWin Up}}, ahk_exe {target_exe}")
        else:
            a.append("    SendEvent {Shift Up}{Ctrl Up}{Alt Up}{LWin Up}")
        if dw_cfg.get("autobuy_then_mid"):
            mid_delay = int(float(dw_cfg.get("autobuy_then_mid_delay_sec", 0.5)) * 1000)
            mid_cfg = config.get("minimap", {}).get("mid", {})
            mx = int(mid_cfg.get("x", 0))
            my = int(mid_cfg.get("y", 0))
            if mx > 0 and my > 0:
                a.append(f"    Sleep, {mid_delay}")
                a.append(f"    if (!WinActive(\"{win_title}\"))")
                a.append("        return")
                if controlsend:
                    a.append(f'    ControlClick, x{mx} y{my}, ahk_exe {target_exe}, , , , NA')
                else:
                    a.append('    MouseGetPos, _ab_mm_x, _ab_mm_y')
                    a.append(f'    MouseMove, {mx}, {my}, 0')
                    a.append('    SendEvent {Blind}{LButton}')
                    a.append('    MouseMove, _ab_mm_x, _ab_mm_y, 0')
        a.append("return")
        a.append("#IfWinActive")
        a.append("")
    except Exception as e:
        print(f"ahk_builder: autobuy block skipped (bad deathwatch_config.json?): {e}", file=sys.stderr)

def _gen_watchdog(a):
    """Watchdog timer + MouseIsOver helper."""
    a.append("Watchdog:")
    a.append("    Process, Exist, %ParentPID%")
    a.append("    if (!ErrorLevel)")
    a.append("        ExitApp")
    a.append("return")
    a.append("")
    a.append("MouseIsOver(WinTitle) {")
    a.append("    MouseGetPos,,, Win")
    a.append('    return WinExist(WinTitle . " ahk_id " . Win)')
    a.append("}")
    a.append("")

def _gen_focus_watch(a, target_exe, toggles, guard_bases=()):
    """FocusWatch + PhantomSweep: the two timers that keep input from leaking.

    FocusWatch turns the game's focus edges into explicit state transitions.
    Losing focus (death-minimize, Alt-Tab) drops every held flag straight away
    instead of waiting for MasterSpammer to notice; regaining focus replays the
    release burst that could not be delivered while the window was gone, so the
    game never comes back with LMB/RMB or an ability key still logically down.

    PhantomSweep only runs while the game is NOT active, which is exactly when
    the script itself never sends anything - so any key the OS still reports as
    logically down while it is physically up is a leftover from an interrupted
    send, and releasing it is always safe. Two consecutive sightings are
    required so a send that is genuinely in flight is never cut in half.
    """
    a.append("FocusWatch:")
    a.append('    _fw_act := WinActive("ahk_exe ' + target_exe + '") ? true : false')
    a.append("    if (_fw_act != WasActive) {")
    a.append("        WasActive := _fw_act")
    a.append("        if (!_fw_act) {")
    a.append("            ResetState(false)")
    a.append("        } else if (NeedCleanup) {")
    a.append("            NeedCleanup := false")
    a.append("            ReleaseAll()")
    a.append("        }")
    a.append("    }")
    a.append("    if (!_fw_act)")
    a.append("        PhantomSweep()")
    if guard_bases:
        # Insurance against a lost key-up leaving Carry stuck true, which would
        # make the pedal look dead outside the game - the exact opposite of
        # what the guard is for.
        a.append("    Loop, Parse, % \"" + ",".join(guard_bases) + "\", `,")
        a.append("    {")
        a.append('        if (Carry[A_LoopField] && !GetKeyState(A_LoopField, "P"))')
        a.append("            Carry[A_LoopField] := false")
        a.append("    }")
    a.append("return")
    a.append("")
    if guard_bases:
        a.append("GuardCarry(k) {")
        a.append("    global Carry")
        a.append("    return Carry[k] ? true : false")
        a.append("}")
        a.append("")
    a.append("PhantomSweep() {")
    a.append("    global PhantomArm")
    a.append("    stuck := \"\"")
    a.append('    Loop, Parse, % "Shift,Ctrl,Alt,LWin,RWin,LButton,RButton", `,')
    a.append("    {")
    a.append('        if (GetKeyState(A_LoopField) && !GetKeyState(A_LoopField, "P"))')
    a.append('            stuck .= A_LoopField . ","')
    a.append("    }")
    a.append('    if (stuck = "") {')
    a.append('        PhantomArm := ""')
    a.append("        return")
    a.append("    }")
    a.append("    if (PhantomArm != stuck) {")
    a.append("        PhantomArm := stuck")
    a.append("        return")
    a.append("    }")
    a.append('    PhantomArm := ""')
    a.append("    Loop, Parse, stuck, `,")
    a.append("    {")
    a.append('        if (A_LoopField != "")')
    a.append("            SendEvent {Blind}{%A_LoopField% up}")
    a.append("    }")
    a.append("}")
    a.append("")


def _gen_hotkeys(a, target_exe, toggles, combos, minimap, afk_k):
    """All hotkeys under #IfWinActive: mouse remap, stop, space, combos, minimap, AFK toggle."""
    a.append("#IfWinActive ahk_exe " + target_exe)
    a.append("")

    if toggles.get("mouse_remap", True):
        bypass = 'GetKeyState("Alt", "P") || !MouseIsOver("ahk_exe ' + target_exe + '")'
        move_instead_hold = toggles.get("mouse_move_instead_hold", False)
        toggle_hold = toggles.get("mouse_toggle_hold", False)
        if toggle_hold:
            # LMB = toggle movement hold: click once to hold RButton (move),
            # click again to release. Bypass passes the real click through.
            a.append("*LButton::")
            a.append("    if (" + bypass + ") {")
            a.append("        LMB_Pass := true")
            a.append("        SendEvent {LButton down}")
            a.append("        return")
            a.append("    }")
            a.append("    MoveToggle := !MoveToggle")
            a.append("    CheckMovement()")
            a.append("return")
            a.append("*LButton Up::")
            a.append("    if (LMB_Pass) {")
            a.append("        LMB_Pass := false")
            a.append("        SendInput {LButton up}")
            a.append("        return")
            a.append("    }")
            a.append("    ; swallow - toggle applied on press")
            a.append("return")
        elif move_instead_hold:
            a.append("*LButton::")
            a.append("    if (" + bypass + ") {")
            a.append("        SendEvent {LButton down}")
            a.append("        return")
            a.append("    }")
            a.append("    MouseGetPos, _click_x, _click_y")
            a.append("    SendEvent {RButton down}")
            a.append("    Sleep, 50")
            a.append("    SendEvent {RButton up}")
            a.append("    MouseMove, _click_x, _click_y, 0")
            a.append("return")
        else:
            a.append("*LButton::")
            a.append("    if (" + bypass + ") {")
            a.append("        SendEvent {LButton down}")
            a.append("        return")
            a.append("    }")
            a.append("    LMB_Held := true")
            a.append("    CheckMovement()")
            a.append("    SetTimer, MasterSpammer, 15")
            a.append("return")
            a.append("*LButton Up::")
            a.append("    if (!LMB_Held) {")
            a.append("        SendInput {LButton up}")
            a.append("        return")
            a.append("    }")
            a.append("    LMB_Held := false")
            a.append("    CheckMovement()")
            a.append("return")
        a.append("*RButton::")
        a.append("    SendInput {LButton down}")
        a.append("return")
        a.append("*RButton Up::")
        a.append("    SendInput {LButton up}")
        a.append("return\n")

    stop_key = (toggles.get("stop_key") or "").strip()
    if stop_key:
        a.append("*" + stop_key + "::")
        a.append("    if (!StopActive) {")
        a.append("        StopActive := true")
        a.append("        SendInput " + stop_key)
        a.append("        CheckMovement()")
        a.append("        SetTimer, MasterSpammer, 15")
        a.append("    }")
        a.append("return")
        a.append("*" + stop_key + " Up::")
        a.append("    StopActive := false")
        a.append("    CheckMovement()")
        a.append("return")

    if toggles.get("space_spam", True):
        a.append("*Space::")
        a.append("    if (!SpaceActive) {")
        a.append("        SpaceActive := true")
        a.append("        SendInput {Space}")
        a.append("        LastSpace := A_TickCount")
        a.append("        SetTimer, MasterSpammer, 15")
        a.append("    }")
        a.append("return")
        a.append("*Space Up::")
        a.append("    SpaceActive := false")
        a.append("return")

    if toggles.get("anti_afk_hotkey", True):
        a.append("^g::")
        a.append("    AntiAFK := !AntiAFK")
        a.append("    if (AntiAFK)")
        a.append("        LastAntiAFK := A_TickCount")
        a.append("return")

    if toggles.get("manual_aim_block", True):
        for k in ("q", "w", "e", "r", "d", "f"):
            a.append("*" + k + "::")
            a.append("    ManualAimActive := true")
            a.append("    SendInput {" + k + " down}")
            a.append("return")
        for k in ("q", "w", "e", "r", "d", "f"):
            a.append("*" + k + " Up::")
            a.append("    SendInput {" + k + " up}")
            cond = " && ".join('!GetKeyState("%s", "P")' % k for k in ("q", "w", "e", "r", "d", "f"))
            a.append("    if (" + cond + ") {")
            a.append("        ManualAimActive := false")
            a.append("    }")
            a.append("return")

    guards = _guarded_triggers(toggles, combos, minimap, afk_k)
    guarded_bases = {b for _, b in guards}
    for c in combos:
        a.append(_hotkey_block(c["trigger"], "P_" + c["tag"],
                               "Last_" + c["tag"], "Step_" + c["tag"],
                               guarded=_base_key(c["trigger"]) in guarded_bases,
                               move_when_pressed=c.get("move_when_pressed", False)))

    mm_iter = [k for k in minimap if k != "_order"] if isinstance(minimap, dict) else []
    for mk in mm_iter:
        entry = minimap.get(mk, {}) if isinstance(minimap, dict) else {}
        trig = (entry.get("trigger") or "").strip()
        x = int(entry.get("x", 0))
        y = int(entry.get("y", 0))
        if trig and x >= 0 and y >= 0:
            a.append("*" + trig + "::")
            if _base_key(trig) in guarded_bases:
                a.append("    " + _carry_set(trig, True))
            a.append('    if (!WinActive("ahk_exe ' + target_exe + '"))')
            a.append("        return")
            a.append('    MouseGetPos, _mm_x, _mm_y')
            a.append('    MouseMove, ' + str(x) + ', ' + str(y) + ', 0')
            a.append('    SendInput {Blind}{LButton}')
            a.append('    MouseMove, _mm_x, _mm_y, 0')
            a.append("return")
            a.append("")

    if afk_k:
        a.append("*" + afk_k + "::")
        if _base_key(afk_k) in guarded_bases:
            a.append("    " + _carry_set(afk_k, True))
        a.append("    P_afk_Active := !P_afk_Active")
        a.append("    if (P_afk_Active) {")
        a.append("        SetTimer, AFKFarmLogic, 15")
        a.append("        P_afk_NeedRestart := true")
        a.append("        P_afk_Cycle := 0")
        a.append("        P_afk_WasDead := false")
        a.append("        P_afk_PosIndex := 0")
        a.append("        P_afk_Timer := A_TickCount")
        a.append("    }")
        a.append("return")
        a.append("")

    a.append("#If")
    a.append("")

    if guards:
        a.append("; --- pedal carry guard --------------------------------------")
        a.append("; Active only for a press that STARTED in the game and is")
        a.append("; still physically held (Carry). That is the death-minimize")
        a.append("; case: the foot never left the pedal, so its auto-repeat")
        a.append("; would rain into whatever app is now in front. Releasing the")
        a.append("; pedal clears Carry, so the next press outside the game goes")
        a.append("; straight through to Windows - the pedal stays usable there.")
        for variant, base in guards:
            a.append('#If GuardCarry("' + base + '")')
            a.append(variant + "::return")
            a.append(variant + " Up::")
            a.append('    Carry["' + base + '"] := false')
            a.append("return")
        a.append("#If")
        a.append("")

def _gen_master_spammer(a, target_exe, toggles, combos):
    """MasterSpammer timer: guards, anti-afk, space spam, combo step logic."""
    a.append("MasterSpammer:")
    cond_list = ["LMB_Held", "StopActive", "SpaceActive"]
    for c in combos:
        cond_list.append("P_" + c["tag"] + "_Held")
    a.append("    if (!(" + " || ".join(cond_list) + ")) {")
    a.append("        SetTimer, MasterSpammer, 200")
    a.append("        return")
    a.append("    }")
    a.append("    SetTimer, MasterSpammer, 15")
    a.append("")
    a.append('    if (!WinActive("ahk_exe ' + target_exe + '")) {')
    a.append("        ResetState()")
    a.append("        return")
    a.append("    }")
    if toggles.get("mouse_remap", True):
        a.append('    if (!MouseIsOver("ahk_exe ' + target_exe + '")) {')
        a.append("        ResetState()")
        a.append("        return")
        a.append("    }")
    a.append('    if (LMB_Held && !GetKeyState("LButton", "P")) {')
    a.append("        LMB_Held := false")
    a.append("        CheckMovement()")
    a.append("    }")
    for c in combos:
        trig = (c.get("trigger") or "").strip()
        if _is_plain_key(trig):
            a.append('    if (P_' + c["tag"] + '_Held && !GetKeyState("' + trig + '", "P")) {')
            a.append("        P_" + c["tag"] + "_Held := false")
            a.append("        Step_" + c["tag"] + " := 0")
            if c.get("move_when_pressed", False):
                a.append("        MoveRefs := (MoveRefs > 0 ? MoveRefs - 1 : 0)")
                a.append("        CheckMovement()")
            a.append("    }")
    stop_key = (toggles.get("stop_key") or "").strip()
    if _is_plain_key(stop_key):
        a.append('    if (StopActive && !GetKeyState("' + stop_key + '", "P")) {')
        a.append("        StopActive := false")
        a.append("        CheckMovement()")
        a.append("    }")
    if toggles.get("space_spam", True):
        a.append('    if (SpaceActive && !GetKeyState("Space", "P")) {')
        a.append("        SpaceActive := false")
        a.append("    }")
    a.append("    if (ManualAimActive || StopActive)")
    a.append("        return")
    a.append("    currentTime := A_TickCount")
    if toggles.get("anti_afk_hotkey", True):
        afk_ms = int(toggles.get("anti_afk_interval", 5000))
        a.append("    if (AntiAFK && (currentTime - LastAntiAFK >= " + str(afk_ms) + ")) {")
        a.append("        SendInput {Blind}{RButton}")
        a.append("        LastAntiAFK := currentTime")
        a.append("    }")
    if toggles.get("space_spam", True):
        sp_ms = int(toggles.get("space_interval", 128))
        a.append("    if (SpaceActive && (currentTime - LastSpace >= " + str(sp_ms) + ")) {")
        a.append("        SendInput {Space}")
        a.append("        LastSpace := currentTime")
        a.append("    }")
    a.append("")
    for c in combos:
        flag = "P_" + c["tag"]
        nd = flag + "_NextDelay"
        steps = c["steps"]
        a.append("    if (" + flag + "_Held && currentTime - Last_" + c["tag"] + " >= " + nd + ") {")
        a.append("        Last_" + c["tag"] + " := currentTime")
        for idx, (key, delay) in enumerate(steps):
            a.append("        if (Step_" + c["tag"] + " == " + str(idx) + ") {")
            a.append("            SendInput " + _send_for(key, c["shift"]))
            a.append("            " + nd + " := " + str(delay))
            a.append("        }")
        a.append("        Step_" + c["tag"] + " := Mod(Step_" + c["tag"] + " + 1, " + str(len(steps)) + ")")
        a.append("    }")
    a.append("return")
    a.append("")

def _deathwatch_cfg():
    """Load deathwatch_config.json for AFK death-pause region/template.

    Falls back to the classic hardcoded defaults if the file is missing or
    malformed - the AFK farm must never die on a bad engine config.
    """
    dw_path = os.path.join(BASE, "deathwatch_config.json")
    try:
        with open(dw_path, encoding="utf-8") as f:
            dw = json.load(f)
        region = dw.get("death_label_region", [900, 118, 1165, 145])
        template = dw.get("death_label_template",
                          "templates/death_label.png")
        if len(region) != 4:
            region = [900, 118, 1165, 145]
        if not template.endswith(".png"):
            template = "templates/death_label.png"
        return [int(v) for v in region], template
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return [900, 118, 1165, 145], "templates/death_label.png"


def _gen_afk_farm(a, target_exe, config, afk, afk_k):
    """AFKFarmLogic timer: death check, minimap cycle, movement, combo."""
    if not afk_k:
        return
    move_dur = int(afk.get("move_duration", 5000))
    follow = bool(afk.get("follow_cursor", True))
    keys_str = (afk.get("combo_keys") or "").strip()
    combo_ms = int(afk.get("combo_interval", 128))
    steps = parse_steps(keys_str, combo_ms) if keys_str else []

    mm = config.get("minimap", {})
    slots_cfg = afk.get("slots", {}) if isinstance(afk, dict) else {}
    positions = []
    move_slots = []
    
    # Handle both old list format and new dict format
    if isinstance(slots_cfg, list):
        # Old format: list of slot keys
        for mk in slots_cfg:
            entry = mm.get(mk, {}) if isinstance(mm, dict) else {}
            trig = (entry.get("trigger") or "").strip()
            x = int(entry.get("x", 0))
            y = int(entry.get("y", 0))
            if trig and x > 0 and y > 0:
                positions.append({"name": mk, "x": x, "y": y})
    else:
        # New format: dict with slot configs
        for mk, slot_cfg in slots_cfg.items():
            if not slot_cfg.get("enabled", False):
                continue
            entry = mm.get(mk, {}) if isinstance(mm, dict) else {}
            trig = (entry.get("trigger") or "").strip()
            x = int(entry.get("x", 0))
            y = int(entry.get("y", 0))
            if trig and x > 0 and y > 0:
                positions.append({"name": mk, "x": x, "y": y})
                if slot_cfg.get("move_when_pressed", False):
                    move_slots.append(mk)
    
    dl_region, dl_template = _deathwatch_cfg()
    dl_x1, dl_y1, dl_x2, dl_y2 = dl_region
    death_template = dl_template
    if not os.path.isabs(death_template):
        death_template = os.path.join("%A_ScriptDir%",
                                      death_template.replace("/", "\\"))

    a.append("AFKFarmLogic:")
    a.append("    if (!P_afk_Active) {")
    a.append("        SetTimer, AFKFarmLogic, 1000")
    a.append("        return")
    a.append("    }")
    a.append("    SetTimer, AFKFarmLogic, 15")
    a.append('    if (!WinActive("ahk_exe ' + target_exe + '"))')
    a.append("        return")
    a.append("    currentTime := A_TickCount")
    a.append("")
    if not positions:
        positions = [{"name": "Mid", "x": 116, "y": 293}]
    a.append("    ; --- restart -------------------------------------------------")
    a.append("    if (P_afk_NeedRestart) {")
    a.append("        P_afk_NeedRestart := false")
    a.append("        P_afk_Timer := currentTime")
    a.append("        P_afk_Step := 0")
    a.append("        P_afk_NextDelay := " + str(steps[0][1] if steps else 128))
    a.append("        return")
    a.append("    }")
    a.append("")
    a.append("    ; --- death check every 500ms -----------------------------")
    a.append("    if (currentTime - P_afk_DeathCheck >= 500) {")
    a.append("        P_afk_DeathCheck := currentTime")
    a.append("        ImageSearch, , , " + str(dl_x1) + ", " + str(dl_y1) + ", " + str(dl_x2) + ", " + str(dl_y2) + ", *40 " + death_template)
    a.append("        if (ErrorLevel = 0) {")
    a.append("            if (!P_afk_WasDead) {")
    a.append("                P_afk_WasDead := true")
    a.append("            }")
    a.append("        } else {")
    a.append("            if (P_afk_WasDead) {")
    a.append("                P_afk_WasDead := false")
    a.append("                P_afk_NeedRestart := true")
    a.append("            }")
    a.append("        }")
    a.append("    }")
    a.append("")
    a.append("    ; while dead skip cycle -----------------------------------")
    a.append("    if (P_afk_WasDead)")
    a.append("        return")
    a.append("")
    if positions:
        a.append("    ; --- cycle: click pos -> move+combo -> next pos -> ... ---")
        a.append("    if (P_afk_Cycle = 0) {")
        a.append("        ; MINIMAP phase: click current position, advance index")
        a.append("        P_afk_Cycle := 1")
        a.append("        P_afk_Timer := currentTime")
        a.append("        P_afk_Step := 0")
        a.append("        MouseGetPos, _af_mx, _af_my")
        for idx, p in enumerate(positions):
            cond = "if" if idx == 0 else "} else if"
            slot_name = p["name"]
            should_move = slot_name in move_slots
            a.append("        " + cond + " (P_afk_PosIndex = " + str(idx) + ") {")
            a.append("            MouseMove, " + str(p["x"]) + ", " + str(p["y"]) + ", 0")
            if should_move:
                a.append("            SendEvent {Blind}{LButton}")
                a.append("            Sleep, 50")
                a.append("            SendEvent {RButton down}")
                a.append("            Sleep, 50")
                a.append("            SendEvent {RButton up}")
            else:
                a.append("            SendEvent {Blind}{LButton}")
        a.append("        }")
        a.append("        MouseMove, _af_mx, _af_my, 0")
        a.append("        P_afk_PosIndex := Mod(P_afk_PosIndex + 1, " + str(len(positions)) + ")")
        a.append("        return")
        a.append("    }")
        a.append("")
        a.append("    ; MOVE phase: duration check")
        a.append("    if (currentTime - P_afk_Timer >= " + str(move_dur) + ") {")
        a.append("        P_afk_Cycle := 0")
        a.append("        return")
        a.append("    }")
    if follow:
        a.append("    ; move toward current mouse position")
    else:
        a.append("    ; move forward (center of game screen)")
        a.append('    WinGetPos, , , _af_fww, _af_fwh, ahk_exe ' + target_exe)
        a.append("    MouseMove, _af_fww // 2, _af_fwh // 3, 0")
    a.append("    ; --- wiggle every 1s to prevent getting stuck ---")
    a.append("    if (currentTime - P_afk_Wiggle >= 1000) {")
    a.append("        P_afk_Wiggle := currentTime")
    a.append("        P_afk_WiggleDir := !P_afk_WiggleDir")
    a.append("        if (P_afk_WiggleDir)")
    a.append("            MouseMove, 1, 0, 0, R")
    a.append("        else")
    a.append("            MouseMove, -1, 0, 0, R")
    a.append("    }")
    a.append("    ; --- re-issue move order every 300ms (was every 15ms tick) ---")
    a.append("    if (currentTime - P_afk_LastMove >= 300) {")
    a.append("        P_afk_LastMove := currentTime")
    a.append("        SendEvent {Blind}{RButton}")
    a.append("    }")
    a.append("    ; fire combo")
    a.append("    if (currentTime - P_afk_LastCombo >= P_afk_NextDelay) {")
    a.append("        P_afk_LastCombo := currentTime")
    for idx, (key, delay) in enumerate(steps):
        a.append("        if (P_afk_Step == " + str(idx) + ") {")
        a.append("            SendEvent {Blind}" + key)
        a.append("            P_afk_NextDelay := " + str(delay))
        a.append("        }")
    a.append("        P_afk_Step := Mod(P_afk_Step + 1, " + str(len(steps) if steps else 1) + ")")
    a.append("    }")
    a.append("return")
    a.append("")

def _gen_helper_funcs(a, combos, afk_k, target_exe, toggles):
    """CheckMovement, ResetState helper functions."""
    a.append("CheckMovement() {")
    a.append("    global LMB_Held, MoveToggle, MoveRefs, StopActive")
    # LMB press-hold, LMB toggle-hold and combo move-hold all share one
    # RButton: release one source and the others keep the champion moving.
    a.append("    want := (LMB_Held || MoveToggle || MoveRefs > 0)")
    a.append("    if (want && !StopActive)")
    a.append("        SendEvent {RButton down}")
    a.append("    else")
    a.append("        SendEvent {RButton up}")
    a.append("}")
    a.append("")
    a.append("ResetState(killAfk := true) {")
    g = ["LMB_Held", "StopActive", "SpaceActive", "ManualAimActive", "NeedCleanup",
         "MoveToggle", "MoveRefs"]
    for c in combos:
        g.append("P_" + c["tag"] + "_Held")
    if afk_k:
        g.append("P_afk_Active")
    a.append("    global " + ", ".join(g))
    held = ["LMB_Held", "StopActive", "SpaceActive", "ManualAimActive",
            "MoveToggle", "MoveRefs > 0"]
    for c in combos:
        held.append("P_" + c["tag"] + "_Held")
    # Nothing was down -> nothing to release. Without this test every single
    # Alt-Tab back into the game would fire a burst of synthetic button-ups,
    # which BlueStacks reads as real clicks.
    a.append("    held := (" + " || ".join(held) + ")")
    a.append("    StopActive := false")
    a.append("    LMB_Held := false")
    a.append("    SpaceActive := false")
    a.append("    ManualAimActive := false")
    a.append("    MoveToggle := false")
    a.append("    MoveRefs := 0")
    for c in combos:
        a.append("    P_" + c["tag"] + "_Held := false")
    if afk_k:
        # Focus loss alone must not switch AFK farm off: AFKFarmLogic already
        # idles while the game is in the background and resumes on return.
        # Only the panic path (cursor left the window) kills it.
        a.append("    if (killAfk)")
        a.append("        P_afk_Active := false")
    a.append("    if (!held)")
    a.append("        return")
    # Releasing into a window that is already gone lands nowhere, so remember
    # the debt and pay it in FocusWatch the moment the game is back in front.
    a.append('    if (WinActive("ahk_exe ' + target_exe + '"))')
    a.append("        ReleaseAll()")
    a.append("    else")
    a.append("        NeedCleanup := true")
    a.append("}")
    a.append("")
    a.append("ReleaseAll() {")
    a.append("    SendEvent {Blind}{LButton up}{RButton up}")
    if toggles.get("manual_aim_block", True):
        ups = "".join("{%s up}" % k for k in ("q", "w", "e", "r", "d", "f"))
        a.append("    SendEvent {Blind}" + ups)
    if toggles.get("space_spam", True):
        a.append("    SendEvent {Blind}{Space up}")
    stop_key = (toggles.get("stop_key") or "").strip()
    if _is_plain_key(stop_key):
        a.append("    SendEvent {Blind}{" + stop_key + " up}")
    # Only force a modifier up when the foot/hand is not actually on it -
    # blindly releasing a physically held Shift makes the next keystroke wrong.
    a.append('    Loop, Parse, % "Shift,Ctrl,Alt,LWin,RWin", `,')
    a.append("    {")
    a.append('        if (!GetKeyState(A_LoopField, "P"))')
    a.append("            SendEvent {Blind}{%A_LoopField% up}")
    a.append("    }")
    a.append("}")
    a.append("")

def generate_script(config):
    toggles = config.get("toggles", {})
    target_exe = toggles.get("target_exe", "HD-Player.exe") or "HD-Player.exe"
    combos, dropped = _active_combos(config)
    afk = config.get("afkfarm", {})
    tk = (afk.get("toggle_key") or "").strip() if isinstance(afk, dict) and afk.get("enabled") else None
    afk_k = tk if tk else None
    minimap = config.get("minimap", {})

    a = []
    _gen_header(a, target_exe, combos, afk)
    _gen_autobuy(a, target_exe, config)
    _gen_watchdog(a)
    guard_bases = [b for _, b in _guarded_triggers(toggles, combos, minimap, afk_k)]
    _gen_focus_watch(a, target_exe, toggles, guard_bases)
    _gen_hotkeys(a, target_exe, toggles, combos, minimap, afk_k)
    _gen_master_spammer(a, target_exe, toggles, combos)
    _gen_afk_farm(a, target_exe, config, afk, afk_k)
    _gen_helper_funcs(a, combos, afk_k, target_exe, toggles)
    a.append("~^!+R:: ExitApp")
    a.append("")
    return "\n".join(a), dropped

def validate_config(config):
    """Check config for common mistakes before generation. Returns list of warnings."""
    warnings = []
    toggles = config.get("toggles", {})
    mode = config.get("mode", "general")
    seen_triggers = {}

    def _check(trig, source):
        if not trig or not trig.strip():
            return
        trig = trig.strip()
        if trig in seen_triggers:
            warnings.append(f"Duplicate trigger '{trig}' in {source} (also in {seen_triggers[trig]})")
        else:
            seen_triggers[trig] = source

    # Check general combos
    if mode == "general":
        combos = config.get("combos", [])
        if not combos:
            warnings.append("General mode: no combos configured")
        for i, c in enumerate(combos):
            trig = c.get("trigger", "")
            _check(trig, f"general combo #{i + 1}")
            if trig and not c.get("keys", "").strip():
                warnings.append(f"Combo #{i + 1} trigger '{trig}' has no keys")
    else:
        # Check champion mode
        entry = config.get("champions", {}).get(mode, {})
        if not entry:
            warnings.append(f"Mode '{mode}' not found in config['champions']")
        else:
            has_any = False
            for slot in ("wave", "jungle", "pvp"):
                trig = entry.get("trigger_" + slot, "")
                keys = entry.get("keys_" + slot, "")
                if trig:
                    has_any = True
                    _check(trig, f"champion {slot}")
                    if not keys.strip():
                        warnings.append(f"{slot}: trigger '{trig}' has no keys")
            if not has_any:
                warnings.append(f"Mode '{mode}': no triggers configured for wave/jungle/pvp")

    # Check minimap triggers
    minimap = config.get("minimap", {})
    if isinstance(minimap, dict):
        for key, entry in minimap.items():
            if key == "_order" or not isinstance(entry, dict):
                continue
            trig = entry.get("trigger", "")
            _check(trig, f"minimap '{key}'")
            x = int(entry.get("x", 0))
            y = int(entry.get("y", 0))
            if trig and (x < 0 or y < 0 or x > 2000 or y > 2000):
                warnings.append(f"minimap '{key}': suspicious coordinates ({x}, {y})")

    # Check AFK farm toggle
    afk = config.get("afkfarm", {})
    if isinstance(afk, dict) and afk.get("enabled"):
        tk = (afk.get("toggle_key") or "").strip()
        if tk:
            _check(tk, "AFK toggle")

    # Check target_exe
    target = toggles.get("target_exe", "")
    if not target:
        warnings.append("target_exe is empty — no window will match")

    # Check stop_key
    sk = (toggles.get("stop_key") or "").strip()
    if sk:
        _check(sk, "stop key")

    # Check AFK farm slots against minimap
    if isinstance(afk, dict) and afk.get("enabled") and isinstance(minimap, dict):
        slots = afk.get("slots", {})
        if isinstance(slots, list):  # legacy list format
            slots = {s: {"enabled": True} for s in slots}
        if isinstance(slots, dict):
            for s, sc in slots.items():
                if isinstance(sc, dict) and not sc.get("enabled", True):
                    continue
                if s not in minimap:
                    warnings.append(f"AFK slot '{s}' not found in minimap config")

    return warnings
