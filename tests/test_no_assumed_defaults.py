"""Guard: a missing input must never become a plausible-looking number.

Fails when new source contains `x or 50`, `.get("k", 33.3)`, `value || 100`, random data, etc. that is not
listed (with a written reason) in assumed_defaults_allowlist.json. See tools/check_no_assumed_defaults.py.
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _guard():
    spec = importlib.util.spec_from_file_location("guard", os.path.join(ROOT, "tools", "check_no_assumed_defaults.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_unreviewed_assumed_defaults():
    hits = _guard().scan(ROOT)
    assert not hits, "unreviewed assumed-default patterns:\n" + "\n".join(
        f"  {h['file']}:{h['line']} [{h['rule']}] {h['snippet']}" for h in hits)


def test_guard_actually_catches_a_new_default(tmp_path):
    (tmp_path / "bad.py").write_text('rsi = row.get("rsi") or 50\nvol = d.get("v", 1.0)\n', encoding="utf-8")
    (tmp_path / "bad.js").write_text("const x = s.value || 100;\n", encoding="utf-8")
    rules = {h["rule"] for h in _guard().scan(str(tmp_path))}
    assert {"or-default", "get-default", "js-or-default"} <= rules
