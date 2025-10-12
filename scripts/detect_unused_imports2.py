"""Improved detector for unused imports in scripts/.

For each top-level import, it searches the whole file (except the import line)
for occurrences of the imported name. It handles 'import a as b' and 'from x import y as z'.
"""

from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
files = list((root / "scripts").glob("*.py"))

import_stmt = re.compile(
    r"^\s*(from\s+(?P<from_mod>\S+)\s+import\s+(?P<from_names>.+)|import\s+(?P<imp_names>.+))"
)

results = {}
for f in files:
    txt = f.read_text(encoding="utf-8")
    lines = txt.splitlines()
    imports = []  # tuples (name, alias, lineno)
    for i, ln in enumerate(lines):
        m = import_stmt.match(ln)
        if not m:
            continue
        if m.group("from_mod"):
            names = m.group("from_names")
            for part in [p.strip() for p in names.split(",")]:
                # handle 'name as alias'
                parts = part.split()
                if len(parts) >= 3 and parts[-2].lower() == "as":
                    name = parts[0]
                    alias = parts[-1]
                else:
                    name = parts[0]
                    alias = parts[0]
                imports.append((name, alias, i + 1))
        elif m.group("imp_names"):
            for part in [p.strip() for p in m.group("imp_names").split(",")]:
                # import modulename or module.sub
                alias = part.split()[-1]
                if " as " in part:
                    alias = part.split()[-1]
                imports.append((part.split(".")[0], alias, i + 1))
    unused = []
    for name, alias, lineno in imports:
        # search for alias usage in file excluding the lineno line
        pattern = re.compile(r"\b" + re.escape(alias) + r"\b")
        found = False
        for j, ln in enumerate(lines):
            if j + 1 == lineno:
                continue
            if pattern.search(ln):
                found = True
                break
        if not found:
            unused.append((name, alias, lineno))
    if unused:
        results[str(f.relative_to(root))] = unused

for f, items in results.items():
    print(f)
    for name, alias, lineno in items:
        if name == alias:
            print(f"  - {name} (line {lineno}) appears unused")
        else:
            print(f"  - {name} as {alias} (line {lineno}) appears unused")

if not results:
    print("No obvious unused imports detected (heuristic).")
else:
    print("\nReview the above before applying changes.")
