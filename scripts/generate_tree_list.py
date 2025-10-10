#!/usr/bin/env python3
"""Generate trees/_tree-list.md listing tree pages (qmd or html) in the trees/ folder.
Runs cross-platform and mirrors the earlier PowerShell behavior.
"""
import json
import re
from pathlib import Path
from collections import OrderedDict

ROOT = Path.cwd()
TREES_DIR = ROOT / "trees"
OUT_FILE = TREES_DIR / "_tree-list.md"
SPECIES_DIR = TREES_DIR / "species"

# optional mapping file: family slug or name -> common name
DATA_FAM_FILE_CANDIDATES = [ROOT / "data" / "common-names.json", ROOT / "assets" / "data" / "common-names.json"]
family_common_map = {}
genus_common_map = {}
for DATA_FAM_FILE in DATA_FAM_FILE_CANDIDATES:
    if not DATA_FAM_FILE.exists():
        continue
    try:
        raw = json.loads(DATA_FAM_FILE.read_text(encoding="utf-8"))
        # support either dict {"Family": "Common"} or list of objects
        if isinstance(raw, dict):
            for k, v in raw.items():
                if not isinstance(v, str):
                    continue
                key_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", str(k).lower()).strip("-")
                family_common_map[key_slug] = v.strip()
                family_common_map[str(k).lower().strip()] = v.strip()
        elif isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                # support keys: family/genus and common_name
                if "family" in item and "common_name" in item:
                    k = str(item.get("family"))
                    v = str(item.get("common_name"))
                    key_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", k.lower()).strip("-")
                    family_common_map[key_slug] = v.strip()
                    family_common_map[k.lower().strip()] = v.strip()
                if "genus" in item and "common_name" in item:
                    k = str(item.get("genus"))
                    v = str(item.get("common_name"))
                    key_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", k.lower()).strip("-")
                    genus_common_map[key_slug] = v.strip()
                    genus_common_map[k.lower().strip()] = v.strip()
    except (OSError, json.JSONDecodeError, UnicodeError) as e:
        # ignore parse/read errors but warn for visibility during runs
        print(f"Warning: failed to load family/genus mapping from {DATA_FAM_FILE}: {e}")
        continue

if not TREES_DIR.exists():
    print(f"Trees directory not found: {TREES_DIR}")
    raise SystemExit(1)

items = [p for p in TREES_DIR.iterdir() if p.is_file() and not p.name.startswith("_") and p.name.lower() not in ("index.qmd","index.html")]
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
heading_re = re.compile(r"^#\s*(.+)$", re.MULTILINE)


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


def _format_tree_table(tree_rows):
    """Return lines for a Markdown table of tree rows (Tree | Planted)."""
    out = []
    if not tree_rows:
        return out
    out.append("| Tree | Planted |")
    out.append("| --- | --- |")
    for ttitle, tlink, planted_val in tree_rows:
        out.append(f"| [{ttitle}]({tlink}) | {planted_val} |")
    out.append("")
    return out


def _compute_species_summary(species_iterable):
    """Return list of (slug, name, count, planted_locations_str) for species iterable."""
    summary = []
    for species_slug, species_name in species_iterable:
        trees = species_map.get(species_slug, {}).get("trees", [])
        sp_count = len(trees)
        locs = []
        for _ttitle, _tlink, base in trees:
            pv = _get_planted_from_tree(base)
            if pv:
                locs.append(pv)
        locs_unique = sorted(set(locs))
        locs_str = ", ".join(locs_unique) if locs_unique else "—"
        summary.append((species_slug, species_name, sp_count, locs_str))
    return summary


def _render_species_summary_lines(species_summary):
    """Return lines for the Species summary Markdown table."""
    if not species_summary:
        return []
    out = []
    out.append("## Planting summary")
    out.append("")
    out.append("| Species | Trees | Planted locations |")
    out.append("|---|---:|---|")
    for sslug, sname, scount, locs_str in species_summary:
        out.append(f"| [{sname}](/trees/species/{sslug}.html) | {scount} | {locs_str} |")
    out.append("")
    return out


def _dedupe_species_list(species_list):
    """Return a de-duplicated list of (slug, name) sorted by name, preserving first occurrence."""
    seen = set()
    out = []
    for species_slug, species_name in sorted(species_list or [], key=lambda x: x[1]):
        if species_slug in seen:
            continue
        seen.add(species_slug)
        out.append((species_slug, species_name))
    return out


# cache for per-tree planted/location values to avoid repeated file IO
_planted_cache = {}


def _get_planted_from_tree(base: str) -> str:
    """Return the 'Planted' metadata string for a tree given its base name.

    This reads the corresponding trees/<base>.qmd (or .html) file and looks
    for a line like "**Planted:** ..." or similar. The value is cached to
    avoid repeated disk reads.
    """
    if not base:
        return ""
    if base in _planted_cache:
        return _planted_cache.get(base, "")
    # attempt qmd first, fall back to html
    candidates = [TREES_DIR / f"{base}.qmd", TREES_DIR / f"{base}.html"]
    planted = ""
    for cand in candidates:
        if not cand.exists() or not cand.is_file():
            continue
        try:
            txt = cand.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        m = re.search(r"\*\*Planted(?::| on:)?\*\*[:\s]*(.+)", txt, re.IGNORECASE)
        if m:
            planted = strip_markup(m.group(1).strip())
            break
    # cache and return (empty string if not found)
    _planted_cache[base] = planted
    return planted


def _get_family_common(name):
    """Return the common name for a family display name, or None."""
    if not name:
        return None
    fam_key = re.sub(r"[^0-9a-zA-Z-]+", "-", name.lower()).strip("-")
    return family_common_map.get(fam_key) or family_common_map.get(name.lower())


def _get_genus_common(name):
    """Return the common name for a genus display name, or None."""
    if not name:
        return None
    g_key = re.sub(r"[^0-9a-zA-Z-]+", "-", str(name).lower()).strip("-")
    return genus_common_map.get(g_key) or genus_common_map.get(str(name).lower())


def _write_page(path: Path, lines: list):
    """Write a page given a Path and list of lines; ensure trailing newline and print a message."""
    new_text = "\n".join(lines) + "\n"
    path.write_text(new_text, encoding="utf-8")

def _aggregate_planted_counts_for_genus(deduped):
    """Aggregate planted location counts across a list of (species_slug, name).

    Returns a dict mapping location -> count.
    """
    planted_counts = {}
    for species_slug, _ in (deduped or []):
        for _ttitle, _tlink, base in species_map.get(species_slug, {}).get("trees", []):
            pv = _get_planted_from_tree(base)
            if pv:
                planted_counts[pv] = planted_counts.get(pv, 0) + 1
    return planted_counts


def _page_header(title_text: str, subtitle: str = None, toc: bool = True, extra_lines=None):
    """Return a list of lines for a standard page header (YAML front-matter + include).

    - title_text: main title string (will be used in title field)
    - subtitle: optional subtitle to include in the title field
    - toc: whether to include toc: true
    - extra_lines: iterable of extra lines to append after include
    """
    lines = []
    lines.append("---")
    if subtitle:
        lines.append(f'title: "{title_text} ({subtitle})"')
    else:
        lines.append(f'title: "{title_text}"')
    if toc:
        lines.append("toc: true")
    lines.append("---")
    lines.append("")
    # include of _tree-search.qmd removed: search box will only be present on trees/index.html
    lines.append("")
    # advisory comment for developers: generated file warning
    lines.append("<!-- This file is generated by scripts/generate_tree_list.py. Do not edit this file directly; update the generator or the underlying data sources instead. -->")
    lines.append("")
    if extra_lines:
        for line in extra_lines:
            lines.append(line)
    return lines


def _parse_species_include(spec_file: Path):
    """Parse a species include file and return (display, scientific, family, genus).

    This centralises the regexes used in two places in the script. Values may be None.
    """
    display = None
    scientific = None
    family = None
    genus = None
    try:
        stext = spec_file.read_text(encoding="utf-8")
        mname = re.search(r"\*\*Common names:\*\*\s*(.+)", stext)
        if mname:
            raw = strip_markup(mname.group(1).strip())
            first = raw.split(",")[0].strip()
            display = first.title() if first else raw.title()
        msc = re.search(r"\*\*Scientific name:\*\*\s*\*?([^\*\n]+)\*?", stext)
        if msc:
            scientific = strip_markup(msc.group(1).strip())
        mfa = re.search(r"\*\*Family:\*\*\s*(.+)", stext)
        if mfa:
            family = strip_markup(mfa.group(1).strip())
        mgen = re.search(r"\*\*Genus:\*\*\s*(?:\*([^\*\n]+)\*|\[([^\]]+)\]\([^\)]+\)|([^\n]+))", stext)
        if mgen:
            genus = strip_markup((mgen.group(1) or mgen.group(2) or mgen.group(3) or "").strip())
    except Exception:
        pass
    return display, scientific, family, genus

for p in items:
    name = p.name
    ext = p.suffix.lower()
    base = p.stem
    if ext == ".qmd":
        link = f"{base}.html"
    else:
        link = name

    title = None
    if ext == ".qmd":
        try:
            text = p.read_text(encoding="utf-8")
            m = title_re1.search(text) or title_re2.search(text)
            if m:
                title = m.group(1).strip()
            else:
                m2 = heading_re.search(text)
                if m2:
                    title = m2.group(1).strip()
        except (OSError, UnicodeError) as e:
            print(f"Warning: failed to read {p}: {e}")
            title = None

    if not title:
        title = f"Tree {base}"

    # try to detect species from an include to trees/_tree-species-info/_*.md (or the old assets path)
    species_slug = None
    try:
        text = p.read_text(encoding="utf-8")
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
                species_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", guess.lower()).strip("-")
    except (OSError, UnicodeError) as e:
        print(f"Warning: failed to read {p} for species detection: {e}")
        species_slug = None

    if species_slug:
        # read species display name from trees/_tree-species-info (underscore-prefixed files) if present
        inc_dir = ROOT / "trees" / "_tree-species-info"
        spec_file = inc_dir / f"_{species_slug}.md"
        display = None
        scientific = None
        family = None
        genus = None
        # if the exact include file doesn't exist, try to find a file whose
        # name contains the common-name token (e.g. _european-ash.md for 'ash')
        if not spec_file.exists() and inc_dir.exists():
            slug_common = species_slug.lower()
            found = None
            for f in inc_dir.iterdir():
                if not f.is_file() or f.suffix.lower() != ".md":
                    continue
                stem = f.name.lstrip("_").rsplit(".md", 1)[0].lower()
                if slug_common == stem or slug_common in stem or stem.endswith("-" + slug_common) or stem.startswith(slug_common + "-"):
                    found = f
                    break
            if not found:
                # fallback: search file contents for the common name token
                guess = species_slug.replace("-", " ").lower()
                for f in inc_dir.iterdir():
                    if not f.is_file() or f.suffix.lower() != ".md":
                        continue
                    try:
                        txt = f.read_text(encoding="utf-8").lower()
                        if guess in txt or slug_common in txt:
                            found = f
                            break
                    except Exception:
                        continue
            if found:
                spec_file = found

        if spec_file.exists():
            display, scientific, family, genus = _parse_species_include(spec_file)
        if not display:
            display = strip_markup(species_slug.replace("-", " ").title())

        species_map.setdefault(species_slug, {"name": display, "scientific": scientific, "family": family, "genus": genus, "trees": []})
        # link from species page will be ../<base>.html because species pages live in trees/species/
        species_map[species_slug]["trees"].append((title, f"../{base}.html", base))

        # register family -> species mapping
        if family:
            # canonicalize family display: prefer a token ending with 'aceae' (common plant families)
            m_famtoken = re.search(r"([A-Za-z]+aceae)", family, re.IGNORECASE)
            if m_famtoken:
                fam_display = m_famtoken.group(1).title()
            else:
                fam_display = strip_markup(family).title()
            # normalize family slug safely
            fam_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", fam_display.lower()).strip("-")
            family_map.setdefault(fam_slug, {"name": fam_display, "species": []})
            family_map[fam_slug]["species"].append((species_slug, display))

            # (we inline the family link earlier; no append needed)

        # register genus -> species mapping
        if genus:
            g_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", strip_markup(genus).lower()).strip("-")
            g_display = genus
            genus_map.setdefault(g_slug, {"name": g_display, "species": []})
            genus_map[g_slug]["species"].append((species_slug, display))
            # inline genus link in the include if not present
            try:
                inc_text = spec_file.read_text(encoding="utf-8")
                g_link = f"/trees/genus/{g_slug}.html"
                # replace Genus line with linked italicised genus
                new_genus_line = f"**Genus:** [*{g_display}*]({g_link})"
                if "**Genus:**" in inc_text:
                    inc_text = re.sub(r"\*\*Genus:\*\*\s*.*", new_genus_line, inc_text)
                else:
                    inc_text = inc_text.rstrip() + "\n\n" + new_genus_line + "\n"
                # remove any old appended 'See all' genus lines
                inc_text = re.sub(r"\n?\[See all species in this genus\]\([^\)]*\)\s*\n?", "\n", inc_text)
                try:
                    old = spec_file.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    old = None
                if old is None or inc_text != old:
                    try:
                        spec_file.write_text(inc_text, encoding="utf-8")
                    except (OSError, UnicodeError) as e:
                        print(f"Warning: failed to write updated include {spec_file}: {e}")
            except (OSError, UnicodeError) as e:
                print(f"Warning: failed to read/update include {spec_file}: {e}")

    # append the list entry for this tree; include scientific name when available
    entry = f"- [{title}]({link})"
    sci_name = None
    try:
        # prefer the scientific value we parsed above, otherwise look up species_map
        if species_slug and 'scientific' in locals() and scientific:
            sci_name = scientific
        elif species_slug and species_slug in species_map:
            sci_name = species_map[species_slug].get('scientific')
    except Exception:
        sci_name = None
    if sci_name:
        entry = f"{entry} — *{sci_name}*"
    lines.append(entry)
    

# Ensure species_map contains entries for any include files under trees/_tree-species-info
inc_dir = ROOT / "trees" / "_tree-species-info"
if inc_dir.exists():
    for f in inc_dir.iterdir():
        if not f.is_file() or f.suffix.lower() != ".md":
            continue
        # canonical slug (strip leading underscores and extension)
        slug = f.name.lstrip("_").rsplit(".md", 1)[0].lower()
        if slug in species_map:
            continue
        # parse file for metadata (common name, scientific, family, genus)
        display, scientific, family, genus = _parse_species_include(f)
        if not display:
            display = strip_markup(slug.replace("-", " ").title())
        species_map.setdefault(slug, {"name": display, "scientific": scientific, "family": family, "genus": genus, "trees": []})
        # register family -> species mapping for includes (so family pages are created)
        if family:
            m_famtoken = re.search(r"([A-Za-z]+aceae)", family, re.IGNORECASE)
            if m_famtoken:
                fam_display = m_famtoken.group(1).title()
            else:
                fam_display = strip_markup(family).title()
            fam_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", fam_display.lower()).strip("-")
            family_map.setdefault(fam_slug, {"name": fam_display, "species": []})
            # avoid duplicates
            if slug not in [s for s, _ in family_map[fam_slug]["species"]]:
                family_map[fam_slug]["species"].append((slug, display))
        # register genus -> species mapping for includes (so genus pages are created)
        if genus:
            g_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", strip_markup(genus).lower()).strip("-")
            g_display = genus
            genus_map.setdefault(g_slug, {"name": g_display, "species": []})
            if slug not in [s for s, _ in genus_map[g_slug]["species"]]:
                genus_map[g_slug]["species"].append((slug, display))

# write per-species pages
if not SPECIES_DIR.exists():
    SPECIES_DIR.mkdir(parents=True, exist_ok=True)

for slug, data in species_map.items():
    page_file = SPECIES_DIR / f"{slug}.qmd"
    title = data.get("name")
    scientific = data.get("scientific")
    # header: title (with optional scientific), toc and search include
    # Do not append a literal ' — Trees' to the HTML title field (remove highlighted text)
    header_title = title
    header_sub = scientific
    lines = _page_header(header_title, subtitle=header_sub, toc=True)
    # add family and genus links (computed from parsed metadata) so every species page has them
    fam_text = data.get("family")
    if fam_text:
        # canonicalize family display: prefer a token ending with 'aceae'
        m_famtoken = re.search(r"([A-Za-z]+aceae)", fam_text, re.IGNORECASE)
        if m_famtoken:
            fam_display = m_famtoken.group(1).title()
        else:
            fam_display = strip_markup(fam_text).title()
        fam_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", fam_display.lower()).strip("-")
        lines.append(f"**Family:** [{fam_display}](/trees/family/{fam_slug}.html)")

    gen_text = data.get("genus")
    if gen_text:
        g_display = strip_markup(gen_text)
        g_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", g_display.lower()).strip("-")
        lines.append(f"**Genus:** [*{g_display}*](/trees/genus/{g_slug}.html)")
    # ensure a blank line between family and genus when both are present
    if fam_text and gen_text:
        # insert a visual separator between the two metadata lines
        # since family was appended before genus, add an extra blank line
        # between them by inserting a blank after the family line (we've
        # already appended genus, so add a blank before continuing)
        # to keep code simple, ensure there's at least one blank here
        lines.insert(len(lines) - 1, "")

    # add a blank line after metadata (family/genus) before the page body
    if fam_text or gen_text:
        lines.append("")

    # Do not emit an H1 here; the page title is provided in the YAML header.
    # Append the per-tree planted table as before.
    tree_rows = []
    for ttitle, tlink, base in data.get("trees", []):
        # read per-tree planted metadata from the corresponding tree file when present
        planted_val = _get_planted_from_tree(base)
        tree_rows.append((ttitle, tlink, planted_val))
    if tree_rows:
        lines.extend(_format_tree_table(tree_rows))
    # removed trailing Back link and per-tree bullet list (no longer needed)
    _write_page(page_file, lines)
    # keep previous message for backwards-compatibility
    print(f"Wrote species page: {page_file}")

# write per-family pages
FAMILY_DIR = TREES_DIR / "family"
if not FAMILY_DIR.exists():
    FAMILY_DIR.mkdir(parents=True, exist_ok=True)

for fam_slug, fdata in family_map.items():
    fpage = FAMILY_DIR / f"{fam_slug}.qmd"
    fname = strip_markup(fdata.get("name"))
    # append common name (from data/plant-family-names.json) in brackets when available
    fam_common = _get_family_common(fname)
    if fam_common:
        fname_display = f"{fname} ({fam_common})"
    else:
        fname_display = fname
    flines = _page_header(f"{fname_display}")
    # The YAML header provides the page title; omit a duplicate H1 in the body
    flines.append("")
    # de-duplicate species list while preserving order
    deduped_sp = _dedupe_species_list(fdata.get("species", []))

    # species summary: one row per species with tree count and unique planted locations
    species_summary = _compute_species_summary(deduped_sp)
    if species_summary:
        flines.extend(_render_species_summary_lines(species_summary))
    # (removed per-species bullet list; species are shown in the summary table above)
    _write_page(fpage, flines)
    print(f"Wrote family page: {fpage}")

# write the family folder index (trees/family/index.qmd) listing all families with species counts
flines = _page_header("Tree families")
if family_map:
    for fam_slug, fdata in sorted(family_map.items(), key=lambda x: x[1].get("name", "")):
        fname = strip_markup(fdata.get("name"))
        fam_common = _get_family_common(fname)
        if fam_common:
            fname_display = f"{fname} ({fam_common})"
        else:
            fname_display = fname
        # count unique species (avoid counting per-tree duplicates)
        species_entries = fdata.get("species", []) or []
        unique_species = set(s for s, _ in species_entries)
        count = len(unique_species)
        flines.append(f"- [{fname_display}](/trees/family/{fam_slug}.html) — {count} species")
else:
    flines.append("No families found.")
flines.append("")
FAMILY_INDEX = FAMILY_DIR / "index.qmd"
_write_page(FAMILY_INDEX, flines)

# write per-genus pages
GENUS_DIR = TREES_DIR / "genus"
if not GENUS_DIR.exists():
    GENUS_DIR.mkdir(parents=True, exist_ok=True)

for g_slug, gdata in genus_map.items():
    gpage = GENUS_DIR / f"{g_slug}.qmd"
    gname = gdata.get("name")
    glines = _page_header(f"{gname}")
    # find families referenced by species in this genus
    fam_candidates = []
    for s_slug, _ in (gdata.get("species") or []):
        f_name = species_map.get(s_slug, {}).get("family")
        if f_name:
            # normalize display
            m_famtoken = re.search(r"([A-Za-z]+aceae)", f_name, re.IGNORECASE)
            if m_famtoken:
                fam_display = m_famtoken.group(1).title()
            else:
                fam_display = strip_markup(f_name).title()
            fam_candidates.append((fam_display, re.sub(r"[^0-9a-zA-Z-]+", "-", fam_display.lower()).strip("-")))

    # if none found from species metadata, try to infer from family_map
    if not fam_candidates:
        # try matching by slug or by species display name (case-insensitive)
        for f_slug, fdata in family_map.items():
            fam_species_entries = (fdata.get("species") or [])
            fam_species_slugs = set(s for s, _ in fam_species_entries)
            fam_species_names = set((n or "").strip().lower() for _, n in fam_species_entries)
            matched = False
            for s_slug, s_name in (gdata.get("species") or []):
                if s_slug in fam_species_slugs or (s_name or "").strip().lower() in fam_species_names:
                    fam_display = strip_markup(fdata.get("name"))
                    fam_candidates.append((fam_display, f_slug))
                    matched = True
                    break
            if matched:
                break

    # if we have any candidate families, use the first one and append a linked Family line
    if fam_candidates:
        fam_display, fam_slug = fam_candidates[0]
        glines.append(f"**Family:** [{fam_display}](/trees/family/{fam_slug}.html)")
        glines.append("")
    # italicise genus name and append common name if available
    g_common = _get_genus_common(gname)
    # The page title is provided in the YAML header above; do not insert a duplicate H1 here.
    # de-duplicate species list while preserving order
    deduped = _dedupe_species_list(gdata.get("species", []))
    # species summary for this genus: one row per species with tree count and planted locations
    species_summary = _compute_species_summary(deduped)
    if species_summary:
        glines.extend(_render_species_summary_lines(species_summary))
    # removed per-species bullet list (species are already shown in the Species summary table)
    # aggregate planted locations across all species in this genus (use deduped list)
    # (removed per-genus 'Planted locations' section)
    _write_page(gpage, glines)
    print(f"Wrote genus page: {gpage}")

# write genus index: alphabetical list of species with genus and family links
GENUS_INDEX = GENUS_DIR / "index.qmd"
# build reverse lookup maps: species -> genus_slug, species -> family_slug
species_to_genus = {}
for g_slug, gdata in genus_map.items():
    for s_slug, _ in gdata.get("species", []):
        species_to_genus[s_slug] = g_slug

species_to_family = {}
for f_slug, fdata in family_map.items():
    for s_slug, _ in fdata.get("species", []):
        species_to_family[s_slug] = f_slug

all_species = []
for s_slug, sdata in species_map.items():
    name = sdata.get("name") or s_slug
    all_species.append((s_slug, name))

all_species.sort(key=lambda x: x[1].lower())

alpha_groups = OrderedDict()
for s_slug, name in all_species:
    first = (name[0].upper() if name and name[0].isalpha() else "#")
    alpha_groups.setdefault(first, []).append((s_slug, name))

glines = _page_header("Species index — A–Z (by common name)")
glines.append("[View A–Z by scientific name](/trees/genus/index2.html)")
glines.append("")
glines.append("# Species index (A–Z)")
glines.append("")

for letter, entries in alpha_groups.items():
    glines.append(f"## {letter}")
    glines.append("")
    for s_slug, s_name in entries:
        # links
        sp_link = f"/trees/species/{s_slug}.html"
        g_slug = species_to_genus.get(s_slug)
        f_slug = species_to_family.get(s_slug)
        g_part = ""
        f_part = ""
        if g_slug and g_slug in genus_map:
            g_name = genus_map[g_slug].get("name")
            g_part = f"Genus: [{g_name}](/trees/genus/{g_slug}.html)"
        if f_slug and f_slug in family_map:
            f_name = family_map[f_slug].get("name")
            f_part = f"Family: [{f_name}](/trees/family/{f_slug}.html)"
        parts = " — ".join([p for p in (g_part, f_part) if p])
        # display common name first, scientific name in italics afterwards when available
        scientific = species_map.get(s_slug, {}).get("scientific")
        if scientific:
            # link common and scientific names separately; keep the dash outside the links
            common_link = f"[{s_name}]({sp_link})"
            sci_link = f"[*{scientific}*]({sp_link})"
            label_html = f"{common_link} — {sci_link}"
        else:
            label_html = f"[{s_name}]({sp_link})"
        if parts:
            glines.append(f"- {label_html} — {parts}")
        else:
            glines.append(f"- {label_html}")
    glines.append("")

_write_page(GENUS_INDEX, glines)

# write alternative genus index sorted by scientific name (A–Z)
GENUS_INDEX2 = GENUS_DIR / "index2.qmd"
sc_list = []
for s_slug, sdata in species_map.items():
    scientific = sdata.get("scientific")
    common = sdata.get("name") or s_slug
    key = (scientific or "").strip() or common
    sc_list.append((s_slug, key, scientific, common))

sc_list.sort(key=lambda x: x[1].lower())

sc_groups = OrderedDict()
for s_slug, key, scientific, common in sc_list:
    first = (key[0].upper() if key and key[0].isalpha() else "#")
    sc_groups.setdefault(first, []).append((s_slug, scientific, common))

slines = _page_header("Species index — A–Z (by scientific name)")
slines.append("[View A–Z by common name](/trees/genus/index.html)")
slines.append("")
slines.append("# Species index (A–Z by scientific name)")
slines.append("")

for letter, entries in sc_groups.items():
    slines.append(f"## {letter}")
    slines.append("")
    for s_slug, scientific, common in entries:
        sp_link = f"/trees/species/{s_slug}.html"
        label = ""
        if scientific:
            # link scientific and common names separately; keep the dash outside the links
            sci_link = f"[*{scientific}*]({sp_link})"
            common_link = f"[{common}]({sp_link})"
            label = f"{sci_link} — {common_link}"
        else:
            label = f"[{common}]({sp_link})"
        # include genus/family when available
        g_slug = species_map.get(s_slug, {}).get("genus")
        f_name = species_map.get(s_slug, {}).get("family")
        g_part = ""
        f_part = ""
        if g_slug:
            g_slug_norm = re.sub(r"[^0-9a-zA-Z-]+", "-", g_slug.lower()).strip("-")
            g_part = f"Genus: [{g_slug}](/trees/genus/{g_slug_norm}.html)"
        if f_name:
            m_famtoken = re.search(r"([A-Za-z]+aceae)", f_name, re.IGNORECASE)
            if m_famtoken:
                fam_display = m_famtoken.group(1).title()
            else:
                fam_display = strip_markup(f_name).title()
            fam_slug = re.sub(r"[^0-9a-zA-Z-]+", "-", fam_display.lower()).strip("-")
            f_part = f"Family: [{fam_display}](/trees/family/{fam_slug}.html)"
        parts = " — ".join([p for p in (g_part, f_part) if p])
        if parts:
            slines.append(f"- [{label}]({sp_link}) — {parts}")
        else:
            slines.append(f"- [{label}]({sp_link})")
    slines.append("")

_write_page(GENUS_INDEX2, slines)
print(f"Wrote genus index (scientific): {GENUS_INDEX2}")

# finally, write the top-level tree list which was accumulated in `lines`
_write_page(OUT_FILE, lines)
