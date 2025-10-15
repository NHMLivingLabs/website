#!/usr/bin/env python3
"""Generate species, family, and genus pages for the Urban Research Stations tree database.
Parses tree QMD files and species metadata to create indexed pages.
"""

import json
import re
from pathlib import Path
from collections import OrderedDict

ROOT = Path.cwd()
TREES_DIR = ROOT / "trees"
SPECIES_DIR = TREES_DIR / "species"


def _slugify(text: str) -> str:
    """Convert text to a slug (lowercase, alphanumeric + hyphens only)."""
    return re.sub(r"[^0-9a-zA-Z-]+", "-", str(text).lower()).strip("-")


# Load family/genus common name mappings from JSON files
family_common_map = {}
genus_common_map = {}
for data_file in [ROOT / "data" / "common-names.json", ROOT / "assets" / "data" / "common-names.json"]:
    if not data_file.exists():
        continue
    try:
        raw = json.loads(data_file.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k, v in ((k, v) for k, v in raw.items() if isinstance(v, str)):
                family_common_map[_slugify(k)] = v.strip()
                family_common_map[str(k).lower().strip()] = v.strip()
        elif isinstance(raw, list):
            for item in (i for i in raw if isinstance(i, dict)):
                if "family" in item and "common_name" in item:
                    k, v = str(item["family"]), str(item["common_name"]).strip()
                    family_common_map[_slugify(k)] = family_common_map[k.lower().strip()] = v
                if "genus" in item and "common_name" in item:
                    k, v = str(item["genus"]), str(item["common_name"]).strip()
                    genus_common_map[_slugify(k)] = genus_common_map[k.lower().strip()] = v
    except (OSError, json.JSONDecodeError, UnicodeError) as e:
        print(f"Warning: failed to load family/genus mapping from {data_file}: {e}")

if not TREES_DIR.exists():
    print(f"Trees directory not found: {TREES_DIR}")
    raise SystemExit(1)

# Get tree QMD files (exclude _-prefixed, index files)
items = sorted(
    (p for p in TREES_DIR.iterdir()
     if p.is_file() and not p.name.startswith("_")
     and p.name.lower() not in ("index.qmd", "index.html")),
    key=lambda p: (0, int(p.stem)) if p.stem.isdigit() else (1, p.stem)
)


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
    s = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", s)  # [text](url) -> text
    s = re.sub(r"<[^>]+>", "", s)  # remove HTML tags
    return s.replace("*", "").strip()  # remove asterisks



def _canonicalize_family(family_text: str) -> str:
    """Canonicalize family display name: prefer token ending with 'aceae'."""
    m = re.search(r"([A-Za-z]+aceae)", family_text, re.IGNORECASE)
    return m.group(1).title() if m else strip_markup(family_text).title()


def _format_tree_table(tree_rows):
    """Return lines for a Markdown table of tree rows (Tree | Planted)."""
    if not tree_rows:
        return []
    return (
        ["| Tree | Planted |", "| --- | --- |"]
        + [f"| [{ttitle}]({tlink}) | {pval} |" for ttitle, tlink, pval in tree_rows]
        + [""]
    )



def _compute_species_summary(species_iterable):
    """Return list of (slug, name, count, planted_locations_str) for species iterable."""
    return [
        (slug, name, len(trees := species_map.get(slug, {}).get("trees", [])),
         ", ".join(locs) if (locs := sorted(set(pv for _, _, base in trees if (pv := _get_planted_from_tree(base))))) else "—")
        for slug, name in species_iterable
    ]


def _render_species_summary_lines(species_summary):
    """Return lines for the Species summary Markdown table."""
    if not species_summary:
        return []
    return (
        ["## Planting summary", "", "| Species | Trees | Planted locations |", "|---|---:|---|"]
        + [f"| [{sname}](/trees/species/{sslug}.html) | {scount} | {locs_str} |"
           for sslug, sname, scount, locs_str in species_summary]
        + [""]
    )



def _dedupe_species_list(species_list):
    """Return a de-duplicated list of (slug, name) sorted by name."""
    seen = set()
    return [(slug, name) for slug, name in sorted(species_list or [], key=lambda x: x[1])
            if slug not in seen and not seen.add(slug)]



# cache for per-tree planted/location values to avoid repeated file IO
_planted_cache = {}


def _get_planted_from_tree(base: str) -> str:
    """Return the 'Planted' metadata string for a tree. Cached to avoid repeated disk reads."""
    if not base or base in _planted_cache:
        return _planted_cache.get(base, "")
    
    for cand in [TREES_DIR / f"{base}.qmd", TREES_DIR / f"{base}.html"]:
        if cand.exists() and cand.is_file():
            try:
                if m := re.search(r"\*\*Planted(?::| on:)?\*\*[:\s]*(.+)", 
                                 cand.read_text(encoding="utf-8"), re.IGNORECASE):
                    _planted_cache[base] = strip_markup(m.group(1).strip())
                    return _planted_cache[base]
            except (OSError, UnicodeError):
                continue
    
    _planted_cache[base] = ""
    return ""



def _get_family_common(name):
    """Return the common name for a family display name, or None."""
    return name and (family_common_map.get(_slugify(name)) or family_common_map.get(name.lower()))


def _get_genus_common(name):
    """Return the common name for a genus display name, or None."""
    return name and (genus_common_map.get(_slugify(name)) or genus_common_map.get(str(name).lower()))


def _write_page(path: Path, lines: list):
    """Write a page given a Path and list of lines; ensure trailing newline."""
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _page_header(title_text: str, subtitle: str = None, toc: bool = True, extra_lines=None):
    """Return a list of lines for a standard page header (YAML front-matter + generated file warning)."""
    lines = ["---", f'title: "{title_text} ({subtitle})"' if subtitle else f'title: "{title_text}"']
    if toc:
        lines.append("toc: true")
    lines.extend(["---", "", "", 
        "<!-- This file is generated by scripts/generate_tree_list.py. Do not edit this file directly; update the generator or the underlying data sources instead. -->", ""])
    if extra_lines:
        lines.extend(extra_lines)
    return lines



def _generate_genus_index(title: str, sort_by: str, link_to_other: str, species_map: dict, genus_map: dict, family_map: dict) -> list:
    """Generate lines for a genus index page (common or scientific name sorting)."""
    # build reverse lookup maps
    species_to_genus = {s_slug: g_slug for g_slug, gdata in genus_map.items() for s_slug, _ in gdata.get("species", [])}
    species_to_family = {s_slug: f_slug for f_slug, fdata in family_map.items() for s_slug, _ in fdata.get("species", [])}

    # build and sort species list
    species_list = [
        (s_slug, (scientific or "").strip() or common if sort_by == "scientific" else common, scientific, common)
        for s_slug, sdata in species_map.items()
        if (common := sdata.get("name") or s_slug) and (scientific := sdata.get("scientific"))
    ]
    species_list.sort(key=lambda x: x[1].lower())

    # group by first letter
    alpha_groups = OrderedDict()
    for s_slug, key, scientific, common in species_list:
        first = key[0].upper() if key and key[0].isalpha() else "#"
        alpha_groups.setdefault(first, []).append((s_slug, scientific, common))

    # generate page content
    lines = _page_header(title)
    lines.extend([
        f"[View A–Z by {'scientific' if sort_by == 'common' else 'common'} name]({link_to_other})",
        "",
        f"# Species index (A–Z{' by scientific name' if sort_by == 'scientific' else ''})",
        ""
    ])

    for letter, entries in alpha_groups.items():
        lines.extend([f"## {letter}", ""])
        for s_slug, scientific, common in entries:
            sp_link = f"/trees/species/{s_slug}.html"
            
            # build label with appropriate name ordering
            if sort_by == "scientific" and scientific:
                label = f"[*{scientific}*]({sp_link}) — [{common}]({sp_link})"
            elif sort_by == "common" and scientific:
                label = f"[{common}]({sp_link}) — [*{scientific}*]({sp_link})"
            else:
                label = f"[{common}]({sp_link})"
            
            # add genus/family links
            if sort_by == "common":
                g_slug = species_to_genus.get(s_slug)
                f_source = species_to_family.get(s_slug)
                g_part = f"Genus: [{genus_map[g_slug].get('name')}](/trees/genus/{g_slug}.html)" if g_slug and g_slug in genus_map else ""
                f_part = f"Family: [{family_map[f_source].get('name')}](/trees/family/{f_source}.html)" if f_source and f_source in family_map else ""
            else:  # scientific
                g_slug = species_map.get(s_slug, {}).get("genus")
                f_source = species_map.get(s_slug, {}).get("family")
                g_part = f"Genus: [{g_slug}](/trees/genus/{_slugify(g_slug)}.html)" if g_slug else ""
                if f_source:
                    fam_display = _canonicalize_family(f_source)
                    f_part = f"Family: [{fam_display}](/trees/family/{_slugify(fam_display)}.html)"
                else:
                    f_part = ""
            
            parts = " — ".join([p for p in (g_part, f_part) if p])
            lines.append(f"- {label} — {parts}" if parts else f"- {label}")
        lines.append("")

    return lines



def _parse_species_include(spec_file: Path):
    """Parse a species include file and return (display, scientific, family, genus)."""
    display = scientific = family = genus = None
    try:
        stext = spec_file.read_text(encoding="utf-8")
        if mname := re.search(r"\*\*Common names:\*\*\s*(.+)", stext):
            raw = strip_markup(mname.group(1).strip())
            display = (first.title() if (first := raw.split(",")[0].strip()) else raw.title())
        scientific = strip_markup(msc.group(1).strip()) if (msc := re.search(r"\*\*Scientific name:\*\*\s*\*?([^\*\n]+)\*?", stext)) else None
        family = strip_markup(mfa.group(1).strip()) if (mfa := re.search(r"\*\*Family:\*\*\s*(.+)", stext)) else None
        genus = strip_markup((mgen.group(1) or mgen.group(2) or mgen.group(3) or "").strip()) if (mgen := re.search(r"\*\*Genus:\*\*\s*(?:\*([^\*\n]+)\*|\[([^\]]+)\]\([^\)]+\)|([^\n]+))", stext)) else None
    except Exception:
        pass
    return display, scientific, family, genus



def _find_species_include_file(species_slug: str, inc_dir: Path) -> Path:
    """Find the species include file for a given slug, with fuzzy matching."""
    spec_file = inc_dir / f"_{species_slug}.md"
    
    if spec_file.exists() or not inc_dir.exists():
        return spec_file
    
    slug_common = species_slug.lower()
    
    # try filename matching
    for f in (f for f in inc_dir.iterdir() if f.is_file() and f.suffix.lower() == ".md"):
        stem = f.name.lstrip("_").rsplit(".md", 1)[0].lower()
        if slug_common in (stem, ) or slug_common in stem or stem.endswith(f"-{slug_common}") or stem.startswith(f"{slug_common}-"):
            return f
    
    # fallback: search file contents
    guess = species_slug.replace("-", " ").lower()
    for f in (f for f in inc_dir.iterdir() if f.is_file() and f.suffix.lower() == ".md"):
        try:
            if guess in (txt := f.read_text(encoding="utf-8").lower()) or slug_common in txt:
                return f
        except Exception:
            continue
    
    return spec_file


for p in items:
    ext, base = p.suffix.lower(), p.stem
    link = f"{base}.html" if ext == ".qmd" else p.name
    title = None

    if ext == ".qmd":
        try:
            text = p.read_text(encoding="utf-8")
            if m := (title_re1.search(text) or title_re2.search(text)):
                title = m.group(1).strip()
            elif m2 := heading_re.search(text):
                title = m2.group(1).strip()
        except (OSError, UnicodeError) as e:
            print(f"Warning: failed to read {p}: {e}")

    title = title or f"Tree {base}"

    # detect species from include reference or title
    species_slug = None
    try:
        text = p.read_text(encoding="utf-8")
        if m := re.search(r"(?:tree-species-info/|_tree-species-info/_)(?:_?)([\w\-]+)\.md", text):
            species_slug = m.group(1)
        elif m2 := re.search(r"-\s*(.+)$", title):
            species_slug = _slugify(m2.group(1).strip())
    except (OSError, UnicodeError) as e:
        print(f"Warning: failed to read {p} for species detection: {e}")

    if species_slug:
        inc_dir = ROOT / "trees" / "_tree-species-info"
        spec_file = _find_species_include_file(species_slug, inc_dir)
        
        display, scientific, family, genus = _parse_species_include(spec_file) if spec_file.exists() else (None, None, None, None)
        display = display or strip_markup(species_slug.replace("-", " ").title())

        species_map.setdefault(species_slug, {
            "name": display, "scientific": scientific, "family": family, "genus": genus, "trees": []
        })["trees"].append((title, f"../{base}.html", base))

        # register family -> species mapping
        if family:
            fam_display, fam_slug = _canonicalize_family(family), _slugify(_canonicalize_family(family))
            family_map.setdefault(fam_slug, {"name": fam_display, "species": []})["species"].append((species_slug, display))

        # register genus -> species mapping and update include file
        if genus:
            g_slug, g_display = _slugify(strip_markup(genus)), genus
            genus_map.setdefault(g_slug, {"name": g_display, "species": []})["species"].append((species_slug, display))
            
            try:
                inc_text = spec_file.read_text(encoding="utf-8")
                g_link = f"/trees/genus/{g_slug}.html"
                new_genus_line = f"**Genus:** [*{g_display}*]({g_link})"
                inc_text = re.sub(r"\*\*Genus:\*\*\s*.*", new_genus_line, inc_text) if "**Genus:**" in inc_text else inc_text.rstrip() + "\n\n" + new_genus_line + "\n"
                inc_text = re.sub(r"\n?\[See all species in this genus\]\([^\)]*\)\s*\n?", "\n", inc_text)
                if inc_text != spec_file.read_text(encoding="utf-8"):
                    spec_file.write_text(inc_text, encoding="utf-8")
            except (OSError, UnicodeError) as e:
                print(f"Warning: failed to update include {spec_file}: {e}")


# Ensure species_map contains entries for any include files under trees/_tree-species-info
inc_dir = ROOT / "trees" / "_tree-species-info"
if inc_dir.exists():
    for f in (f for f in inc_dir.iterdir() if f.is_file() and f.suffix.lower() == ".md"):
        slug = f.name.lstrip("_").rsplit(".md", 1)[0].lower()
        if slug in species_map:
            continue
        
        display, scientific, family, genus = _parse_species_include(f)
        display = display or strip_markup(slug.replace("-", " ").title())
        species_map.setdefault(slug, {
            "name": display, "scientific": scientific, "family": family, "genus": genus, "trees": []
        })
        
        if family:
            fam_display, fam_slug = _canonicalize_family(family), _slugify(_canonicalize_family(family))
            family_map.setdefault(fam_slug, {"name": fam_display, "species": []})
            if slug not in [s for s, _ in family_map[fam_slug]["species"]]:
                family_map[fam_slug]["species"].append((slug, display))
        
        if genus:
            g_slug = _slugify(strip_markup(genus))
            genus_map.setdefault(g_slug, {"name": genus, "species": []})
            if slug not in [s for s, _ in genus_map[g_slug]["species"]]:
                genus_map[g_slug]["species"].append((slug, display))

# write per-species pages
SPECIES_DIR.mkdir(parents=True, exist_ok=True)

for slug, data in species_map.items():
    spage_lines = _page_header(data.get("name"), subtitle=data.get("scientific"), toc=True)
    
    # add family and genus links
    if fam_text := data.get("family"):
        fam_canon = _canonicalize_family(fam_text)
        spage_lines.append(f"**Family:** [{fam_canon}](/trees/family/{_slugify(fam_canon)}.html)")
    if gen_text := data.get("genus"):
        g_display = strip_markup(gen_text)
        spage_lines.append(f"**Genus:** [*{g_display}*](/trees/genus/{_slugify(g_display)}.html)")
    
    if (fam_text := data.get("family")) and data.get("genus"):
        spage_lines.insert(-1, "")
    if data.get("family") or data.get("genus"):
        spage_lines.append("")

    # append per-tree planted table
    if tree_rows := [(t, l, _get_planted_from_tree(b)) for t, l, b in data.get("trees", [])]:
        spage_lines.extend(_format_tree_table(tree_rows))
    
    _write_page(SPECIES_DIR / f"{slug}.qmd", spage_lines)
    print(f"Wrote species page: {SPECIES_DIR / f'{slug}.qmd'}")

# write per-family pages
FAMILY_DIR = TREES_DIR / "family"
FAMILY_DIR.mkdir(parents=True, exist_ok=True)

for fam_slug, fdata in family_map.items():
    fname = strip_markup(fdata.get("name"))
    fname_display = f"{fname} ({fam_common})" if (fam_common := _get_family_common(fname)) else fname
    
    flines = _page_header(fname_display)
    flines.append("")
    
    if species_summary := _compute_species_summary(_dedupe_species_list(fdata.get("species", []))):
        flines.extend(_render_species_summary_lines(species_summary))
    
    _write_page(FAMILY_DIR / f"{fam_slug}.qmd", flines)
    print(f"Wrote family page: {FAMILY_DIR / f'{fam_slug}.qmd'}")

# write the family index
flines = _page_header("Tree families")
for fam_slug, fdata in sorted(family_map.items(), key=lambda x: x[1].get("name", "")):
    fname = strip_markup(fdata.get("name"))
    fam_common = _get_family_common(fname)
    fname_display = f"{fname} ({fam_common})" if fam_common else fname
    unique_species = set(s for s, _ in fdata.get("species", []) or [])
    flines.append(f"- [{fname_display}](/trees/family/{fam_slug}.html) — {len(unique_species)} species")
flines.append("")
_write_page(FAMILY_DIR / "index.qmd", flines)

# write per-genus pages
GENUS_DIR = TREES_DIR / "genus"
GENUS_DIR.mkdir(parents=True, exist_ok=True)

for g_slug, gdata in genus_map.items():
    glines = _page_header(gdata.get("name"))
    
    # find family for this genus
    if not (fam_candidates := [(fam_display := _canonicalize_family(f_name), _slugify(fam_display))
                               for s_slug, _ in gdata.get("species") or []
                               if (f_name := species_map.get(s_slug, {}).get("family"))]):
        # fallback: try to infer from family_map
        for f_slug, fdata in family_map.items():
            fam_species_slugs = set(s for s, _ in fdata.get("species") or [])
            fam_species_names = set((n or "").strip().lower() for _, n in fdata.get("species") or [])
            if any(s_slug in fam_species_slugs or (s_name or "").strip().lower() in fam_species_names
                   for s_slug, s_name in gdata.get("species") or []):
                fam_candidates = [(strip_markup(fdata.get("name")), f_slug)]
                break

    if fam_candidates:
        fam_display, fam_slug = fam_candidates[0]
        glines.extend([f"**Family:** [{fam_display}](/trees/family/{fam_slug}.html)", ""])
    
    if species_summary := _compute_species_summary(_dedupe_species_list(gdata.get("species", []))):
        glines.extend(_render_species_summary_lines(species_summary))
    
    _write_page(GENUS_DIR / f"{g_slug}.qmd", glines)
    print(f"Wrote genus page: {GENUS_DIR / f'{g_slug}.qmd'}")

# write genus index: alphabetical list of species with genus and family links
GENUS_INDEX = GENUS_DIR / "index.qmd"
_write_page(GENUS_INDEX, _generate_genus_index(
    "Species index — A–Z (by common name)", "common", "/trees/genus/index2.html",
    species_map, genus_map, family_map
))

# write alternative genus index sorted by scientific name (A–Z)
GENUS_INDEX2 = GENUS_DIR / "index2.qmd"
_write_page(GENUS_INDEX2, _generate_genus_index(
    "Species index — A–Z (by scientific name)", "scientific", "/trees/genus/index.html",
    species_map, genus_map, family_map
))
print(f"Wrote genus index (scientific): {GENUS_INDEX2}")
