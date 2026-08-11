"""README mirror digest regression test.

Each locale README carries, as its marker line:

    <!-- source-digest: README.md sha256:<16 hex> -->

the sha256 of the English source (README.md) it was translated FROM, with every
N.N.N version string normalised to the literal ``VERSION`` first (so a release
version-bump never invalidates the marker).  This test recomputes that digest
from the current README.md and asserts every mirror carries a matching marker —
guarding against the drift class fixed in v0.3.8 (mirrors silently stale, digest
markers re-stamped to a value that no longer matched the source).
"""

import hashlib
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

SOURCE = BASE / "README.md"
MIRRORS = ["README.ru.md", "README.ee.md", "README.ja.md", "README.ded.md"]

MARKER_RE = re.compile(
    r"source-digest:\s*README\.md\s+sha256:([0-9a-f]{16})",
    re.IGNORECASE,
)

VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def source_digest(path=SOURCE):
    """Normalised digest of the English source: CRLF->LF, N.N.N->VERSION, sha256[:16]."""
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    text = raw.decode("utf-8")
    normalised = VERSION_RE.sub("VERSION", text)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def test_source_digest_is_16_hex():
    digest = source_digest()
    assert re.fullmatch(r"[0-9a-f]{16}", digest), digest


def test_every_mirror_carries_matching_digest():
    expected = source_digest()
    missing, stale = [], []
    for name in MIRRORS:
        path = BASE / name
        assert path.is_file(), f"{name} missing"
        text = path.read_text(encoding="utf-8")
        match = MARKER_RE.search(text)
        if match is None:
            missing.append(name)
        elif match.group(1) != expected:
            stale.append(f"{name} ({match.group(1)} != {expected})")
    assert not missing, f"mirrors missing source-digest marker: {missing}"
    assert not stale, f"mirrors with stale source-digest marker: {stale}"


# --- T-148: version drift - READMEs and CHANGELOG must agree, no stale VERSION

def test_readme_badges_match_latest_changelog_version():
    """All README badges must cite the latest CHANGELOG release - the
    changelog is the single version source (T-148)."""
    changelog = (BASE / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## v(\d+\.\d+\.\d+)", changelog, re.MULTILINE)
    assert m, "CHANGELOG.md must carry a `## vX.Y.Z` header"
    latest = m.group(1)
    for name in ["README.md", *MIRRORS]:
        text = (BASE / name).read_text(encoding="utf-8")
        assert "v%s" % latest in text, (
            f"{name} does not cite the latest release v{latest}")


def test_main_has_no_stale_version_constant():
    """VERSION was a dead constant (0.3.20) that disagreed with READMEs
    (0.3.27); it was deleted (T-148). If a version constant is ever needed
    again it must be derived from the single CHANGELOG source - a second
    hand-maintained number is how this drift happened."""
    import main as main_mod
    assert not hasattr(main_mod, "VERSION")
