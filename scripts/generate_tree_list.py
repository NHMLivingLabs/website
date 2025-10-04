#!/usr/bin/env python3
"""
Generate trees/_tree-list.md listing tree pages (qmd or html) in the trees/ folder.
Runs cross-platform and mirrors the earlier PowerShell behavior.
"""
import re
from pathlib import Path

ROOT = Path.cwd()
TREES_DIR = ROOT / 'trees'
OUT_FILE = TREES_DIR / '_tree-list.md'

if not TREES_DIR.exists():
    print(f"Trees directory not found: {TREES_DIR}")
    raise SystemExit(1)

items = [p for p in TREES_DIR.iterdir() if p.is_file() and not p.name.startswith('_') and p.name.lower() not in ('index.qmd','index.html')]
# sort by numeric value if possible
def sort_key(p):
    name = p.stem
    try:
        return (0, int(name))
    except Exception:
        return (1, name)

items.sort(key=sort_key)

lines = []

title_re1 = re.compile(r'^title:\s*"([^"]+)"', re.IGNORECASE | re.MULTILINE)
title_re2 = re.compile(r"^title:\s*'([^']+)'", re.IGNORECASE | re.MULTILINE)
heading_re = re.compile(r'^#\s*(.+)$', re.MULTILINE)

for p in items:
    name = p.name
    ext = p.suffix.lower()
    base = p.stem
    if ext == '.qmd':
        link = f"{base}.html"
    else:
        link = name

    title = None
    if ext == '.qmd':
        try:
            text = p.read_text(encoding='utf-8')
            m = title_re1.search(text) or title_re2.search(text)
            if m:
                title = m.group(1).strip()
            else:
                m2 = heading_re.search(text)
                if m2:
                    title = m2.group(1).strip()
        except Exception:
            title = None

    if not title:
        title = f"Tree {base}"

    lines.append(f"- [{title}]({link})")

OUT_FILE.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f"Wrote {OUT_FILE}")
