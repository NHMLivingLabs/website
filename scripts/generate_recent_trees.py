"""Generate trees/_tree-list.md listing the 10 most recently created/updated trees.

This script looks for the Epicollect export cached at `cache/epicollect-meta/entries_{project}.json`.
If the cache is missing it will attempt to run the existing fetch script
`scripts/generate_trees_from_epicollect.py` to refresh the cache.

Output: writes `trees/_tree-list.md` with 10 bullets linking to `trees/<id>.qmd`, ordered
by `created_at` descending (most recent first).
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_SLUG = "nhm-urs-tree-dbh"
CACHED = ROOT / "cache" / "epicollect-meta" / f"entries_{PROJECT_SLUG}.json"
OUT = ROOT / "trees" / "_tree-list.md"


def ensure_cache():
    if CACHED.exists():
        return True
    print("Cache not found at", CACHED)
    print("Attempting to run fetch script to create cache")
    try:
        # run the existing fetcher to populate the cache; the fetcher no longer supports --dry-run
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_trees_from_epicollect.py")],
            check=False,
        )
        if CACHED.exists():
            return True
        print("Fetch script completed but cache still missing.")
        return False
    except Exception as e:
        print("Failed to run fetch script:", e)
        return False


def load_entries():
    j = json.loads(CACHED.read_text(encoding="utf8"))
    # normalize to list of entries
    if isinstance(j, dict):
        data = j.get("data") or j.get("entries") or j
        return data.get("entries") or data.get("data") or [] if isinstance(data, dict) else (data if isinstance(data, list) else [])
    return j if isinstance(j, list) else []


def entry_created_at(e):
    for k in ("created_at", "createdAt", "created"):
        if v := e.get(k):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except Exception:
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(v[:19], fmt)
                    except Exception:
                        continue
    return None


def tree_id_from_entry(entry):
    if not isinstance(entry, dict):
        return None
    # prefer 2_Tree_Number
    for k, v in entry.items():
        if isinstance(k, str) and k.strip().lower().startswith("2_") and "tree" in k.lower():
            return str(v)
    return str(entry.get("ec5_uuid") or entry.get("id") or "")


def main():
    if not ensure_cache():
        print("Cache unavailable; cannot generate recent tree list.")
        raise SystemExit(1)

    if not (entries := load_entries()):
        print("No entries found in cache; aborting")
        raise SystemExit(1)

    rows = []
    for e in entries:
        created = entry_created_at(e) or datetime.min
        tid = tree_id_from_entry(e) or e.get("ec5_uuid") or e.get("id")
        species = ""
        if isinstance(e, dict):
            for k in ("3_Species", "species"):
                if k in e:
                    v = e.get(k)
                    species = "; ".join(str(x) for x in v) if isinstance(v, list) else str(v)
                    break
        rows.append((created, tid, species))

    top = sorted(rows, key=lambda r: r[0], reverse=True)[:10]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Recent tree updates", ""]
    for created, tid, species in top:
        created_str = created.strftime("%d %b %Y") if created and created != datetime.min else ""
        link = f"{tid}.qmd" if tid else ""
        title = f"Tree {tid}" + (f" — {species}" if species else "") if tid else "Tree"
        lines.append(f"- [{title}]({link}) — {created_str}" if link else f"- {title} — {created_str}")

    OUT.write_text("\n".join(lines), encoding="utf8")
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
