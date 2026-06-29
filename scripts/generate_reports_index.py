"""Generate reports.qmd from files in the reports/ directory.

This script scans `reports/` for Quarto files with YAML front-matter that
includes a `citation` mapping and groups them by a report type inferred from
filename or front-matter. It then emits `reports.qmd` with headings for each
report type and a complete citation line linking to the local report file.

Usage: python scripts/generate_reports_index.py

The output file is `reports.qmd` at the repository root and will be overwritten.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
OUT = ROOT / "reports.qmd"

# Mapping heuristics: filename prefixes to section headings
TYPE_MAP = [
    (re.compile(r"^1_"), "Published Protocols"),
    (re.compile(r"^2_"), "Published Protocols"),
    (re.compile(r"^3_"), "Implementation Reports"),
]


def read_front_matter(path: Path):
    text = path.read_text(encoding="utf8")
    if not text.startswith("---"):
        return {}, text
    # find end of front matter
    if not (m := re.search(r"^---\s*$", text, re.MULTILINE)):
        return {}, text
    if not (m2 := re.search(r"^---\s*$", text[m.end():], re.MULTILINE)):
        return {}, text
    
    fm_text = text[m.end():m.end() + m2.start()]
    fm = {}
    lines = fm_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("#"):
            i += 1
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key, val = key.strip(), val.strip().strip('"')
            if val == "":
                # collect indented block
                j = i + 1
                nested_lines = []
                while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t")):
                    nested_lines.append(lines[j])
                    j += 1
                stripped = [ln.lstrip() for ln in nested_lines]
                if stripped and all(s.startswith("-") or ":" in s for s in stripped):
                    if any(s.startswith("-") for s in stripped):
                        items = []
                        for s in stripped:
                            if s.startswith("-"):
                                item = s[1:].strip()
                                if ":" in item:
                                    k, v = item.split(":", 1)
                                    items.append({"name": v.strip()} if k.strip() == "name" else {k.strip(): v.strip()})
                                else:
                                    items.append(item)
                            elif ":" in s:
                                k, v = s.split(":", 1)
                                items.append({k.strip(): v.strip()})
                        fm[key] = items
                    else:
                        fm[key] = {k.strip(): v.strip().strip('"') for s in stripped if ":" in s for k, v in [s.split(":", 1)]}
                else:
                    fm[key] = ""
                i = j
                continue
            fm[key] = val
        i += 1
    return fm or {}, text[m.end() + m2.end():]


def infer_type_from_name(name: str):
    for rx, label in TYPE_MAP:
        if rx.search(name):
            return label
    if "protocol" in name.lower():
        return "Published Protocols"
    if "implementation" in name.lower():
        return "Implementation Reports"
    return "Other Reports"


def citation_from_front_matter(fm: dict, path: Path):
    # Build citation string
    title = fm.get("title") or path.stem
    for pfx in [
        "NHM Living Labs Urban Research Station Survey Protocol —",
        "NHM Living Labs Urban Research Station Implementation Report —",
        "NHM Urban Research Station Survey Protocol —",
        "NHM Urban Research Station Implementation Report —",
        "NHM Living Labs Urban Research Station Survey Protocol",
        "NHM Living Labs Urban Research Station Implementation Report",
        "NHM Urban Research Station Survey Protocol",
        "NHM Urban Research Station Implementation Report",
    ]:
        if title.startswith(pfx):
            title = title[len(pfx):].strip(" \u2014-–:")
            break

    authors = fm.get("author")
    authors_str = ""
    if isinstance(authors, list):
        names = [a.get("name") if isinstance(a, dict) and a.get("name") else a.strip() 
                 for a in authors if (isinstance(a, dict) and a.get("name")) or (isinstance(a, str) and a.strip())]
        authors_str = ", ".join(names)
    elif authors:
        authors_str = str(authors)

    citation = fm.get("citation", {}) or {}
    container = citation.get("container-title") or citation.get("journal") or ""
    issue = citation.get("issue")
    year = fm.get("year") or citation.get("year") or fm.get("date")
    if year:
        if m := re.search(r"(19|20)\d{2}", str(year)):
            year = m.group(0)

    link = f"reports/{path.name}"
    parts = [f"[{title}]({link})"]
    if year:
        parts.append(str(year))
    if authors_str:
        parts.append(authors_str)
    if container:
        parts.append(f"*{container}*")
    if issue:
        parts.append(f"Issue {issue}")
    return " — ".join(parts)


def main():
    files = sorted(REPORTS_DIR.glob("*.qmd"))
    grouped = {}
    for p in files:
        fm, _ = read_front_matter(p)
        typ = fm.get("type") or infer_type_from_name(p.name)
        heading = {
            "Published Protocols": "Published Protocols",
            "Published-Protocol": "Published Protocols",
            "Implementation Reports": "Implementation Reports",
            "Implementation-Report": "Implementation Reports"
        }.get(typ, typ)
        grouped.setdefault(heading, []).append((p, fm))

    ordered_headings = ["Published Protocols", "Implementation Reports", "Other Reports"]
    for h in grouped.keys():
        if h not in ordered_headings:
            ordered_headings.append(h)

    lines = [
        "---",
        'title: "NHM Living Labs Reports"',
        "toc: true",
        "---\n",
        "This section contains reports on the implementation and development of NHM Living Labs, including Urban Research Station and Tring, covering infrastructure, methodologies, and research programmes.\n"
    ]

    for heading in ordered_headings:
        if not (items := grouped.get(heading)):
            continue

        items = sorted(items, key=lambda x: int(iss) if (iss := (x[1].get("citation") or {}).get("issue")) and str(iss).isdigit() else -1, reverse=True)
        lines.append(f"## {heading}\n")
        for p, fm in items:
            lines.append(f"- {citation_from_front_matter(fm, p)}")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf8")
    print("Wrote", OUT)


if __name__ == "__main__":
    if not REPORTS_DIR.exists():
        print("No reports directory found at", REPORTS_DIR)
        raise SystemExit(1)
    main()
