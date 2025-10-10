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
    m = re.search(r"^---\s*$", text, re.MULTILINE)
    if not m:
        return {}, text
    # find second '---'
    m2 = re.search(r"^---\s*$", text[m.end():], re.MULTILINE)
    if not m2:
        return {}, text
    fm_text = text[m.end():m.end()+m2.start()]
    # Improved YAML-like parser for limited front-matter (handles nested mappings and simple lists)
    fm = {}
    lines = fm_text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line or line.startswith("#"):
            i += 1
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"')
            if val == "":
                # collect indented block
                j = i + 1
                nested_lines = []
                while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t")):
                    nested_lines.append(lines[j])
                    j += 1
                # parse nested block: either mapping or list
                # detect list items (start with '- ' after stripping leading spaces)
                stripped = [ln.lstrip() for ln in nested_lines]
                if stripped and all(s.startswith("-") or ":" in s for s in stripped):
                    # parse as list or mapping of simple items
                    # if items start with '- ', parse as list
                    if any(s.startswith("-") for s in stripped):
                        items = []
                        for s in stripped:
                            if s.startswith("-"):
                                item = s[1:].strip()
                                # item can be 'name: Foo' or plain 'Foo'
                                if ":" in item:
                                    k, v = item.split(":", 1)
                                    if k.strip() == "name":
                                        items.append({"name": v.strip()})
                                    else:
                                        items.append({k.strip(): v.strip()})
                                else:
                                    items.append(item)
                            # mapping line
                            elif ":" in s:
                                k, v = s.split(":", 1)
                                items.append({k.strip(): v.strip()})
                        fm[key] = items
                    else:
                        # parse as mapping
                        nested = {}
                        for s in stripped:
                            if ":" in s:
                                k, v = s.split(":", 1)
                                nested[k.strip()] = v.strip().strip('"')
                        fm[key] = nested
                else:
                    fm[key] = ""
                i = j
                continue
            fm[key] = val
        i += 1
    rest = text[m.end()+m2.end():]
    return fm or {}, rest


def infer_type_from_name(name: str):
    for rx, label in TYPE_MAP:
        if rx.search(name):
            return label
    # fallback: look for keywords
    if "protocol" in name.lower():
        return "Published Protocols"
    if "implementation" in name.lower() or "implementation-report" in name.lower():
        return "Implementation Reports"
    return "Other Reports"


def citation_from_front_matter(fm: dict, path: Path):
    # Build a simple citation string using available fields in front matter
    title = fm.get("title") or path.stem
    # remove common NHM prefixes from titles
    prefixes = [
        "NHM Urban Research Station Survey Protocol —",
        "NHM Urban Research Station Implementation Report —",
        "NHM Urban Research Station Survey Protocol",
        "NHM Urban Research Station Implementation Report",
    ]
    for pfx in prefixes:
        if title.startswith(pfx):
            title = title[len(pfx):].strip(" \u2014-–:")

    authors = fm.get("author")
    # normalize authors: the front-matter parser may produce a list of dicts
    # containing alternating 'name' and 'affiliation' mappings. Extract only
    # entries that include a 'name' or plain strings.
    authors_str = ""
    if isinstance(authors, list):
        names = []
        for a in authors:
            if isinstance(a, dict):
                if a.get("name"):
                    names.append(a["name"])
            elif isinstance(a, str) and a.strip():
                names.append(a.strip())
        authors_str = ", ".join(names)
    else:
        authors_str = str(authors) if authors else ""
    # authors_str left as-is (do not strip braces)

    citation = fm.get("citation", {}) or {}
    container = citation.get("container-title") or citation.get("journal") or ""
    issue = citation.get("issue")
    # only use year/date if explicitly present in front-matter/citation
    year = fm.get("year") or citation.get("year") or fm.get("date")
    # normalize year to a 4-digit year if a full date was provided
    if year:
        ys = str(year)
        m = re.search(r"(19|20)\d{2}", ys)
        if m:
            year = m.group(0)
        else:
            # keep as-is if no 4-digit year found
            year = ys

    link = f"reports/{path.name}"
    parts = []
    # Link first, using the title as the link text
    parts.append(f"[{title}]({link})")
    # then year
    if year:
        parts.append(str(year))
    # then authors
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
        # normalize heading
        if typ == "Published Protocols" or typ == "Published-Protocol":
            heading = "Published Protocols"
        elif typ in ("Implementation Reports", "Implementation-Report"):
            heading = "Implementation Reports"
        else:
            heading = typ
        grouped.setdefault(heading, []).append((p, fm))

    # Ensure stable order of sections
    ordered_headings = ["Published Protocols", "Implementation Reports", "Other Reports"]
    for h in list(grouped.keys()):
        if h not in ordered_headings:
            ordered_headings.append(h)

    lines = []
    lines.append("---")
    lines.append('title: "Urban Research Station Reports"')
    lines.append("toc: true")
    lines.append("---\n")
    lines.append("This section contains reports on the implementation and development of the Urban Research Station and Nature Discovery Garden infrastructure, methodologies, and research programmes.\n")

    for heading in ordered_headings:
        items = grouped.get(heading)
        if not items:
            continue
        # sort by numeric citation.issue descending; missing issues go last
        def issue_val(item):
            p, fm = item
            citation = fm.get("citation") or {}
            iss = citation.get("issue")
            try:
                return int(iss)
            except Exception:
                # missing/invalid issue -> put after numeric issues
                return -1
        items = sorted(items, key=issue_val, reverse=True)
        lines.append(f"## {heading}\n")
        for p, fm in items:
            cite = citation_from_front_matter(fm, p)
            lines.append(f"- {cite}")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf8")
    print("Wrote", OUT)


if __name__ == "__main__":
    if not REPORTS_DIR.exists():
        print("No reports directory found at", REPORTS_DIR)
        raise SystemExit(1)
    main()
