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
ERROR_DIR = ROOT / "errors"
MISSING_SPECIES_FILE = ERROR_DIR / "missing_species.txt"


def slugify(text: str) -> str:
    """Convert text to a slug (lowercase, alphanumeric + hyphens only)."""
    return re.sub(r"[^0-9a-zA-Z-]+", "-", str(text).lower()).strip("-")


def normalize_species_name(taxon: str) -> str:
    """Normalize known species name variations."""
    if not taxon:
        return taxon
    
    taxon = taxon.strip()
    
    # Specific normalization for London Plane
    # Use × (multiplication sign) instead of x for hybrid notation
    if "Platanus occidentalis x orientalis" in taxon or "platanus occidentalis x orientalis" in taxon.lower():
        return "Platanus × hispanica"
    
    return taxon


def parse_taxon_name(taxon):
    """Parse TaxonName field to extract common and scientific names."""
    if not taxon:
        return "", taxon
    
    # Normalize species name first
    taxon = normalize_species_name(taxon)
    
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
    # Normalize both 'x' and '×' for matching
    guess = species_slug.replace("-", " ").lower()
    # Handle hybrid notation - if the slug removed × or x, try both forms
    guess_with_x = guess.replace("platanus hispanica", "platanus x hispanica")
    guess_with_times = guess.replace("platanus hispanica", "platanus × hispanica")
    
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
                            # Check original guess and both forms of hybrid notation
                            if (guess in sci_name or sci_name in guess or 
                                guess_with_x in sci_name or sci_name in guess_with_x or
                                guess_with_times in sci_name or sci_name in guess_with_times):
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


def extract_existing_dbh(file_path: Path) -> str:
    """Extract DBH value from existing tree file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        for line in content.split('\n'):
            if '**Diameter at breast height' in line:
                # Extract the DBH value (e.g., "15.7cm" from "**Diameter at breast height (1.3m):** 15.7cm")
                match = re.search(r':\*\*\s*([\d.]+)cm', line)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return None


def write_tree_page(tree_id: str, row: dict, force=False):
    """Generate a tree page from CSV row. Returns (success, missing_species_info)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    outpath = OUT_DIR / f"{tree_id}.qmd"
    
    # Check if file exists and extract existing DBH
    existing_dbh = None
    if outpath.exists():
        existing_dbh = extract_existing_dbh(outpath)
        if not force:
            print(f"Skipping existing {outpath} (use --force to overwrite)")
            return True, None
    
    taxon = row.get("TaxonName", "")
    common_name, scientific = parse_taxon_name(taxon)
    
    # Use first part of scientific name as display (will be replaced if species file found)
    display_name = scientific.split()[0] if scientific else f"Tree {tree_id}"
    
    # Try to find species include file and extract common name
    inc_file = None
    missing_species = None
    if scientific:
        species_slug = slugify(scientific.split("'")[0].strip())  # Remove cultivar for slug
        inc_file = find_species_include_file(species_slug)
        if inc_file:
            # Extract common name from species file
            if extracted_common := extract_common_name(inc_file):
                display_name = extracted_common
        else:
            # No species file found - log this
            missing_species = f"Tree {tree_id}: {scientific} (from CSV: {taxon})"
    
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
    
    # Add DBH if available - prefer existing value from file
    dbh_to_use = existing_dbh if existing_dbh else row.get("DBH", "").strip()
    if dbh_to_use:
        try:
            if float(dbh_to_use) > 0:
                lines.extend([f"**Diameter at breast height (1.3m):** {dbh_to_use}cm", ""])
        except ValueError:
            if dbh_to_use:
                lines.extend([f"**Diameter at breast height (1.3m):** {dbh_to_use}cm", ""])
    
    # Add age group if available
    if age := row.get("AgeGroup", "").strip():
        lines.extend([f"**Age group:** {age}", ""])
    
    # Add additional info if available
    if addinfo := row.get("AddInfo", "").strip():
        lines.extend([f"**Notes:** {addinfo}", ""])
    
    outpath.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {outpath}")
    return True, missing_species


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
    missing_species_list = []
    
    with CSV_FILE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Use TagInfo as tree ID, stripping leading zeroes
            tree_id = row.get("TagInfo", "").strip().lstrip("0") or "0"
            if not tree_id:
                print(f"Skipping row without TagInfo: {row}")
                continue
            
            try:
                success, missing_species = write_tree_page(tree_id, row, force=args.force)
                if success:
                    trees_created += 1
                    if missing_species:
                        missing_species_list.append(missing_species)
                else:
                    trees_skipped += 1
            except Exception as e:
                print(f"Error processing tree {tree_id}: {e}")
                trees_skipped += 1
    
    # Write missing species to error file
    if missing_species_list:
        ERROR_DIR.mkdir(parents=True, exist_ok=True)
        MISSING_SPECIES_FILE.write_text(
            "\n".join(sorted(set(missing_species_list))) + "\n",
            encoding="utf-8"
        )
        print(f"\nWrote {len(missing_species_list)} missing species to {MISSING_SPECIES_FILE}")
    
    print(f"\nSummary:")
    print(f"  Trees created: {trees_created}")
    print(f"  Trees skipped: {trees_skipped}")
    print(f"  Missing species info: {len(missing_species_list)}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
