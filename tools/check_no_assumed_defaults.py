"""
check_no_assumed_defaults.py -- the guard against invented numbers.

Scans source for the patterns that turn a MISSING input into a plausible-looking number
(`x or 50`, `.get("k", 33.3)`, `value || 100`, `random.`, ...). Every hit must either be fixed or
be listed in the repo's `assumed_defaults_allowlist.json` with a written reason. A new, unreviewed
hit makes this exit non-zero (and the pytest wrapper fail), so a default cannot slip back in.

Limits, stated plainly: this finds INVENTED DEFAULTS. It cannot find a real number that means
something other than its label (e.g. a sum presented as a count) -- only comparing outputs with an
independent source does that.

Usage:  python check_no_assumed_defaults.py <repo_dir> [<repo_dir> ...]   (exit 1 on unreviewed hits)
"""
import json
import os
import re
import sys

SKIP_DIRS = {"tools", "node_modules", "dist", "build", "scratch", ".venv", "venv", "__pycache__", "android",
             ".git", "tests", "test", "_backup_src_20260910_023905", "cache", ".expo"}
EXTS = (".py", ".js", ".jsx", ".ts", ".tsx", ".html")
NUM = r"(?:50|25|33\.3|0\.5|1\.0|100|150|22|20|40|60|75)(?:\.0)?"

PATTERNS = [
    ("or-default",      re.compile(rf"\bor\s+{NUM}\b(?![\d.])")),
    ("get-default",     re.compile(rf"\.get\([^()]*,\s*{NUM}\s*\)")),
    ("else-default",    re.compile(rf"\belse\s+{NUM}\b(?![\d.])")),
    ("js-or-default",   re.compile(rf"\|\|\s*{NUM}\b(?![\d.])")),
    ("js-nullish",      re.compile(rf"\?\?\s*{NUM}\b(?![\d.])")),
    ("random",          re.compile(r"\brandom\.(random|randint|uniform|choice|gauss|normalvariate)\b|Math\.random\(")),
    ("fake-name",       re.compile(r"\b(mock|fake|dummy|sample)_[a-z_]+\s*[=(]", re.I)),
]
COMMENT = re.compile(r"^\s*(#|//|\*|/\*)")


def _norm(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace("\\", "/")


def scan(repo: str):
    allow_path = os.path.join(repo, "assumed_defaults_allowlist.json")
    allow = {}
    if os.path.exists(allow_path):
        allow = {(e["file"], e["snippet"].strip()): e["reason"] for e in json.load(open(allow_path, encoding="utf-8"))}
    hits = []
    for dp, dn, fn in os.walk(repo):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith("_backup")]
        for f in fn:
            if not f.endswith(EXTS) or f.endswith(".min.js") or ".bak" in f:
                continue
            p = os.path.join(dp, f)
            try:
                lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if COMMENT.match(line):
                    continue
                code = re.sub(r"(#|//).*$", "", line) if "http" not in line else line
                for name, rx in PATTERNS:
                    if rx.search(code):
                        key = (_norm(p, repo), line.strip())
                        if key in allow:
                            continue
                        hits.append({"file": key[0], "line": i, "rule": name, "snippet": line.strip()[:160]})
                        break
    return hits


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    total = 0
    for repo in sys.argv[1:]:
        hits = scan(repo)
        total += len(hits)
        name = os.path.basename(repo.rstrip("/\\"))
        print(f"== {name}: {len(hits)} unreviewed")
        for h in hits:
            print(f"  {h['file']}:{h['line']} [{h['rule']}] {h['snippet']}")
    sys.exit(1 if total else 0)
