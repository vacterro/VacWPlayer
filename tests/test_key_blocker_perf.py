"""PERF-005 regression: blocked-key hot reload must update the LIVE hook in
place (atomic set swap) with NO stop()/start() teardown, and must fall back to a
full start() reinstall only when no live hook thread exists (recovery preserved)."""

import key_blocker as kb


class _Alive:
    def is_alive(self):
        return True


class _Dead:
    def is_alive(self):
        return False


def test_update_keys_swaps_in_place_when_hook_alive(monkeypatch):
    monkeypatch.setattr(kb, "_thread", _Alive())
    monkeypatch.setattr(kb, "_blocked_vk", {kb.VK_MAP["F13"]})
    monkeypatch.setattr(kb, "_block_until_released_vk", set())
    calls = []
    monkeypatch.setattr(kb, "start", lambda keys=None: calls.append(("start", keys)))
    monkeypatch.setattr(kb, "stop", lambda: calls.append(("stop",)))

    kb.update_keys(["F14"])

    # In-place swap happened, and crucially NO teardown/reinstall occurred.
    assert kb._blocked_vk == {kb.VK_MAP["F14"]}
    assert calls == []


def test_update_keys_falls_back_to_start_when_no_thread(monkeypatch):
    monkeypatch.setattr(kb, "_thread", None)
    calls = []

    def fake_start(keys=None):
        calls.append(("start", keys))
        kb._blocked_vk = {kb.VK_MAP[k] for k in (keys or []) if k in kb.VK_MAP}

    monkeypatch.setattr(kb, "start", fake_start)
    monkeypatch.setattr(kb, "stop", lambda: calls.append(("stop",)))

    kb.update_keys(["F15"])

    # No live hook -> full reinstall, preserving original recovery semantics.
    assert calls == [("start", ["F15"])]
    assert kb._blocked_vk == {kb.VK_MAP["F15"]}
