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
SPECIES_DIR = TREES_DIR / 'species'

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

# mapping: slug -> {"name": display_name, "trees": [(title, link, base)]}
species_map = {}
family_map = {}
genus_map = {}

title_re1 = re.compile(r'^title:\s*"([^"]+)"', re.IGNORECASE | re.MULTILINE)
title_re2 = re.compile(r"^title:\s*'([^']+)'", re.IGNORECASE | re.MULTILINE)
heading_re = re.compile(r'^#\s*(.+)$', re.MULTILINE)


def strip_markup(s: str) -> str:
    """Remove Markdown links, HTML tags and stray asterisks from a string."""
    if not s:
        return s
    # convert markdown links [text](url) -> text
    s = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", s)
    # remove any remaining HTML tags
    s = re.sub(r"<[^>]+>", "", s)
    # remove asterisks used for italics/bold
    s = s.replace("*", "")
    return s.strip()

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

    # try to detect species from an include to trees/_tree-species-info/_*.md (or the old assets path)
    species_slug = None
    try:
        text = p.read_text(encoding='utf-8')
        # match either /assets/tree-species-info/name.md or /trees/_tree-species-info/_name.md
        m = re.search(r"(?:tree-species-info/|_tree-species-info/_)(?:_?)([\w\-]+)\.md", text)
        if m:
            species_slug = m.group(1)
        else:
            # fallback: if title contains a dash like 'Tree 63 - European ash'
            m2 = re.search(r"-\s*(.+)$", title)
            if m2:
                guess = m2.group(1).strip()
                # create slug from guess
                species_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", guess.lower()).strip('-')
    except Exception:
        species_slug = None

    if species_slug:
        # read species display name from trees/_tree-species-info (underscore-prefixed files) if present
        spec_file = ROOT / 'trees' / '_tree-species-info' / f"_{species_slug}.md"
        display = None
        scientific = None
        family = None
        genus = None
        if spec_file.exists():
            try:
                stext = spec_file.read_text(encoding='utf-8')
                mname = re.search(r"\*\*Common names:\*\*\s*(.+)", stext)
                if mname:
                    raw = strip_markup(mname.group(1).strip())
                    # prefer the first common name (before commas) and title-case it
                    first = raw.split(',')[0].strip()
                    display = first.title() if first else raw.title()
                msc = re.search(r"\*\*Scientific name:\*\*\s*\*?([^\*\n]+)\*?", stext)
                if msc:
                    scientific = strip_markup(msc.group(1).strip())
                mfa = re.search(r"\*\*Family:\*\*\s*(.+)", stext)
                if mfa:
                    family = strip_markup(mfa.group(1).strip())
                # try to parse Genus line (handles italic or linked text)
                mgen = re.search(r"\*\*Genus:\*\*\s*(?:\*([^\*\n]+)\*|\[([^\]]+)\]\([^\)]+\)|([^\n]+))", stext)
                if mgen:
                    genus = strip_markup((mgen.group(1) or mgen.group(2) or mgen.group(3) or '').strip())
                # Do NOT modify the include files in-place. We only parse their content.
            except Exception:
                display = None
        if not display:
            display = strip_markup(species_slug.replace('-', ' ').title())

        species_map.setdefault(species_slug, {"name": display, "scientific": scientific, "family": family, "genus": genus, "trees": []})
        # link from species page will be ../<base>.html because species pages live in trees/species/
        species_map[species_slug]['trees'].append((title, f"../{base}.html", base))

        # register family -> species mapping
        if family:
            # canonicalize family display: prefer a token ending with 'aceae' (common plant families)
            m_famtoken = re.search(r'([A-Za-z]+aceae)', family, re.IGNORECASE)
            if m_famtoken:
                fam_display = m_famtoken.group(1).title()
            else:
                fam_display = strip_markup(family).title()
            # normalize family slug safely
            fam_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", fam_display.lower()).strip('-')
            family_map.setdefault(fam_slug, {"name": fam_display, "species": []})
            family_map[fam_slug]['species'].append((species_slug, display))

            # (we inline the family link earlier; no append needed)

        # register genus -> species mapping
        if genus:
            g_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", strip_markup(genus).lower()).strip('-')
            g_display = genus
            genus_map.setdefault(g_slug, {"name": g_display, "species": []})
            genus_map[g_slug]['species'].append((species_slug, display))
            # inline genus link in the include if not present
            try:
                inc_text = spec_file.read_text(encoding='utf-8')
                g_link = f"/trees/genus/{g_slug}.html"
                # replace Genus line with linked italicised genus
                new_genus_line = f"**Genus:** [*{g_display}*]({g_link})"
                if "**Genus:**" in inc_text:
                    inc_text = re.sub(r"\*\*Genus:\*\*\s*.*", new_genus_line, inc_text)
                else:
                    inc_text = inc_text.rstrip() + "\n\n" + new_genus_line + "\n"
                # remove any old appended 'See all' genus lines
                inc_text = re.sub(r"\n?\[See all species in this genus\]\([^\)]*\)\s*\n?", "\n", inc_text)
                if inc_text != spec_file.read_text(encoding='utf-8'):
                    spec_file.write_text(inc_text, encoding='utf-8')
            except Exception:
                pass

OUT_FILE.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f"Wrote {OUT_FILE}")

# write per-species pages
if not SPECIES_DIR.exists():
    SPECIES_DIR.mkdir(parents=True, exist_ok=True)

for slug, data in species_map.items():
    page_file = SPECIES_DIR / f"{slug}.qmd"
    title = data.get('name')
    scientific = data.get('scientific')
    lines = []
    lines.append('---')
    if scientific:
        # put plain text scientific name in the HTML title
        lines.append(f'title: "{title} ({scientific}) — Trees"')
    else:
        lines.append(f'title: "{title} — Trees"')
    lines.append('toc: true')
    lines.append('---')
    lines.append('')
    lines.append("{{< include ../_tree-search.qmd >}}")
    lines.append('')
    if scientific:
        # italicise scientific name in the H1 using Markdown
        lines.append(f"# {title} (*{scientific}*)")
    else:
        lines.append(f"# Trees of {title}")
    lines.append('')
    lines.append(f"[Back to Tree Database](../index.html)")
    lines.append('')
    for ttitle, tlink, _ in data['trees']:
        lines.append(f"- [{ttitle}]({tlink})")
    lines.append('')
    page_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Wrote species page: {page_file}")

# write per-family pages
FAMILY_DIR = TREES_DIR / 'family'
if not FAMILY_DIR.exists():
    FAMILY_DIR.mkdir(parents=True, exist_ok=True)

for fam_slug, fdata in family_map.items():
    fpage = FAMILY_DIR / f"{fam_slug}.qmd"
    fname = strip_markup(fdata.get('name'))
    flines = []
    flines.append('---')
    flines.append(f'title: "{fname} — Tree families"')
    flines.append('toc: true')
    flines.append('---')
    flines.append('')
    flines.append("{{< include ../_tree-search.qmd >}}")
    flines.append('')
    flines.append(f"# Species in {fname}")
    flines.append('')
    flines.append(f"[Back to Tree Database](../index.html)")
    flines.append('')
    for species_slug, species_name in sorted(fdata.get('species', []), key=lambda x: x[1]):
        flines.append(f"- [{species_name}](/trees/species/{species_slug}.html)")
    flines.append('')
    fpage.write_text('\n'.join(flines) + '\n', encoding='utf-8')
    print(f"Wrote family page: {fpage}")

# write the family folder index (trees/family/index.qmd) listing all families with species counts
flines = []
flines.append('---')
flines.append('title: "Tree families — Index"')
flines.append('toc: true')
flines.append('---')
flines.append('')
flines.append("{{< include ../_tree-search.qmd >}}")
flines.append('')
flines.append('# Tree families')
flines.append('')
if family_map:
    for fam_slug, fdata in sorted(family_map.items(), key=lambda x: x[1].get('name', '')):
        fname = strip_markup(fdata.get('name'))
        count = len(fdata.get('species', []))
        flines.append(f"- [{fname}](/trees/family/{fam_slug}.html) — {count} species")
else:
    flines.append('No families found.')
flines.append('')
FAMILY_INDEX = FAMILY_DIR / 'index.qmd'
FAMILY_INDEX.write_text('\n'.join(flines) + '\n', encoding='utf-8')
print(f"Wrote family folder index: {FAMILY_INDEX}")

# write per-genus pages
GENUS_DIR = TREES_DIR / 'genus'
if not GENUS_DIR.exists():
    GENUS_DIR.mkdir(parents=True, exist_ok=True)

for g_slug, gdata in genus_map.items():
    gpage = GENUS_DIR / f"{g_slug}.qmd"
    gname = gdata.get('name')
    glines = []
    glines.append('---')
    glines.append(f'title: "{gname} — Tree genera"')
    glines.append('toc: true')
    glines.append('---')
    glines.append('')
    glines.append("{{< include ../_tree-search.qmd >}}")
    glines.append('')
    glines.append(f"# Species in the genus {gname}")
    glines.append('')
    glines.append(f"[Back to Tree Database](../index.html)")
    glines.append('')
    for species_slug, species_name in sorted(gdata.get('species', []), key=lambda x: x[1]):
        glines.append(f"- [{species_name}](/trees/species/{species_slug}.html)")
    glines.append('')
    gpage.write_text('\n'.join(glines) + '\n', encoding='utf-8')
    print(f"Wrote genus page: {gpage}")
