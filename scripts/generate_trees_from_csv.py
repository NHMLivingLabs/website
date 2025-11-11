"""Generate tree pages from CSV file in assets/data.

This script reads the NHMGardenTrees CSV file and generates Quarto pages for each tree.
It uses the Handle column as the tree ID and extracts species information from TaxonName.

Usage:
    python scripts/generate_trees_from_csv.py [--force]
"""

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_FILE = ROOT / "assets" / "data" / "NHMGardenTrees_0.csv"
OUT_DIR = ROOT / "trees"


def slugify(text: str) -> str:
    """Convert text to a slug (lowercase, alphanumeric + hyphens only)."""
    return re.sub(r"[^0-9a-zA-Z-]+", "-", str(text).lower()).strip("-")


def parse_taxon_name(taxon):
    """Parse TaxonName field to extract common and scientific names."""
    if not taxon:
        return "", taxon
    
    # Handle various formats:
    # "Betula pendula" -> scientific name
    # "Tilia tomentosa 'Petiolaris'" -> scientific with cultivar
    # "Platanus occidentalis x orientalis = p. x hispanica" -> hybrid
    
    taxon = taxon.strip()
    
    # Clean up hybrid notation
    if "=" in taxon:
        # Take the standardized name after =
        parts = taxon.split("=")
        if len(parts) > 1:
            taxon = parts[1].strip()
    
    # Remove "x " hybrid marker for slug generation but keep for display
    slug_base = taxon.replace(" x ", "-").replace("x ", "")
    
    return "", taxon


def find_species_include_file(species_slug: str) -> Path:
    """Find species include file with fuzzy matching."""
    inc_dir = ROOT / "trees" / "_tree-species-info"
    if not inc_dir.exists():
        return None
    
    spec_file = inc_dir / f"_{species_slug}.md"
    if spec_file.exists():
        return spec_file
    
    slug_common = species_slug.lower()
    
    # Try filename matching - prioritize exact matches
    for f in (f for f in inc_dir.iterdir() if f.is_file() and f.suffix.lower() == ".md"):
        stem = f.name.lstrip("_").rsplit(".md", 1)[0].lower()
        if slug_common == stem:
            return f
    
    # Try partial filename matching
    for f in (f for f in inc_dir.iterdir() if f.is_file() and f.suffix.lower() == ".md"):
        stem = f.name.lstrip("_").rsplit(".md", 1)[0].lower()
        if slug_common in stem or stem.endswith(f"-{slug_common}") or stem.startswith(f"{slug_common}-"):
            return f
    
    # Fallback: search file contents for scientific name match
    # This avoids false matches like "ilex" matching "Quercus ilex"
    guess = species_slug.replace("-", " ").lower()
    for f in (f for f in inc_dir.iterdir() if f.is_file() and f.suffix.lower() == ".md"):
        try:
            txt = f.read_text(encoding="utf-8")
            # Search for scientific name match which is more reliable
            for line in txt.split('\n'):
                if line.startswith('**Scientific name:**'):
                    # Extract scientific name from **Scientific name:** *Sci name*
                    parts = line.split('**')
                    if len(parts) >= 3:
                        after_label = parts[2]
                        sci_match = re.search(r'\*([^*]+)\*', after_label)
                        if sci_match:
                            sci_name = sci_match.group(1).strip().lower()
                            if guess in sci_name or sci_name in guess:
                                return f
        except Exception:
            continue
    
    return None


def extract_common_name(species_file: Path) -> str:
    """Extract common name from species include file."""
    try:
        content = species_file.read_text(encoding="utf-8")
        for line in content.split('\n'):
            if line.startswith('**Common name:**'):
                # Extract text between brackets [Common Name](url)
                import re
                match = re.search(r'\[([^\]]+)\]', line)
                if match:
                    return match.group(1).strip()
    except Exception as e:
        print(f"Warning: failed to extract common name from {species_file}: {e}")
    return None


def write_tree_page(tree_id: str, row: dict, force=False):
    """Generate a tree page from CSV row."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    outpath = OUT_DIR / f"{tree_id}.qmd"
    
    if outpath.exists() and not force:
        print(f"Skipping existing {outpath} (use --force to overwrite)")
        return outpath
    
    taxon = row.get("TaxonName", "")
    common_name, scientific = parse_taxon_name(taxon)
    
    # Use first part of scientific name as display (will be replaced if species file found)
    display_name = scientific.split()[0] if scientific else f"Tree {tree_id}"
    
    # Try to find species include file and extract common name
    inc_file = None
    if scientific:
        species_slug = slugify(scientific.split("'")[0].strip())  # Remove cultivar for slug
        inc_file = find_species_include_file(species_slug)
        if inc_file:
            # Extract common name from species file
            if extracted_common := extract_common_name(inc_file):
                display_name = extracted_common
    
    lines = [
        "---",
        f'title: "Tree {tree_id} — {display_name}"',
        "toc: false",
        "---\n",
        "",
        "<!-- This file is generated by scripts/generate_trees_from_csv.py. Do not edit this file directly; update the generator or the underlying data sources instead. -->",
        ""
    ]
    
    # Add species include if found
    if inc_file:
        try:
            rel = inc_file.relative_to(OUT_DIR).as_posix()
            lines.extend([f"{{{{< include '{rel}' >}}}}", ""])
        except Exception as e:
            print(f"Warning: failed to compute relative path for {inc_file}: {e}")
    
    lines.extend(["## Tree data", ""])
    
    # Add DBH if available
    if dbh := row.get("DBH", "").strip():
        try:
            if float(dbh) > 0:
                lines.extend([f"**Diameter at breast height (1.3m):** {dbh}cm", ""])
        except ValueError:
            if dbh:
                lines.extend([f"**Diameter at breast height (1.3m):** {dbh}cm", ""])
    
    # Add age group if available
    if age := row.get("AgeGroup", "").strip():
        lines.extend([f"**Age group:** {age}", ""])
    
    # Add additional info if available
    if addinfo := row.get("AddInfo", "").strip():
        lines.extend([f"**Notes:** {addinfo}", ""])
    
    outpath.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {outpath}")
    return outpath


def main():
    p = argparse.ArgumentParser(description="Generate tree pages from CSV file")
    p.add_argument("--force", action="store_true", help="Overwrite existing tree pages")
    args = p.parse_args()
    
    if not CSV_FILE.exists():
        print(f"CSV file not found: {CSV_FILE}")
        return 1
    
    print(f"Reading CSV from {CSV_FILE}")
    
    trees_created = 0
    trees_skipped = 0
    
    with CSV_FILE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Use TagInfo as tree ID, stripping leading zeroes
            tree_id = row.get("TagInfo", "").strip().lstrip("0") or "0"
            if not tree_id:
                print(f"Skipping row without TagInfo: {row}")
                continue
            
            try:
                write_tree_page(tree_id, row, force=args.force)
                trees_created += 1
            except Exception as e:
                print(f"Error processing tree {tree_id}: {e}")
                trees_skipped += 1
    
    print(f"\nSummary:")
    print(f"  Trees created: {trees_created}")
    print(f"  Trees skipped: {trees_skipped}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
