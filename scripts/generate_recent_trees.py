"""Generate trees/_tree-list.md listing the 10 most recently created/updated trees.

This script looks for the Epicollect export cached at `cache/epicollect-meta/entries_{project}.json`.
If the cache is missing it will attempt to run the existing fetch script
`scripts/generate_trees_from_epicollect.py --dry-run` to refresh the cache.

Output: writes `trees/_tree-list.md` with 10 bullets linking to `trees/<id>.qmd`, ordered
by `created_at` descending (most recent first).
"""
from pathlib import Path
import json
from datetime import datetime
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT_SLUG = 'nhm-urs-tree-dbh'
CACHED = ROOT / 'cache' / 'epicollect-meta' / f'entries_{PROJECT_SLUG}.json'
OUT = ROOT / 'trees' / '_tree-list.md'


def ensure_cache():
    if CACHED.exists():
        return True
    print('Cache not found at', CACHED)
    print('Attempting to run fetch script to create cache (dry-run)')
    try:
        # run the existing fetcher in dry-run mode so it populates the cache without overwriting pages
        rc = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'generate_trees_from_epicollect.py'), '--dry-run'], check=False)
        if CACHED.exists():
            return True
        print('Fetch script completed but cache still missing.')
        return False
    except Exception as e:
        print('Failed to run fetch script:', e)
        return False


def load_entries():
    text = CACHED.read_text(encoding='utf8')
    j = json.loads(text)
    # normalize to list of entries in a few common shapes
    entries = []
    if isinstance(j, dict):
        data = j.get('data') or j.get('entries') or j
        if isinstance(data, dict):
            entries = data.get('entries') or data.get('data') or []
        elif isinstance(data, list):
            entries = data
    elif isinstance(j, list):
        entries = j
    return entries


def entry_created_at(e):
    # Epicollect uses created_at or createdAt depending on export shape
    for k in ('created_at', 'createdAt', 'created'):
        v = e.get(k)
        if v:
            try:
                # try parsing ISO-like timestamps
                return datetime.fromisoformat(v.replace('Z', '+00:00'))
            except Exception:
                # fallback: try common date formats
                for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
                    try:
                        return datetime.strptime(v[:19], fmt)
                    except Exception:
                        continue
    return None


def tree_id_from_entry(entry):
    # prefer 2_Tree_Number then ec5_uuid or id
    if isinstance(entry, dict):
        # try keys case-insensitively
        for k, v in entry.items():
            if isinstance(k, str) and k.strip().lower().startswith('2_') and 'tree' in k.lower():
                return str(v)
        if 'ec5_uuid' in entry:
            return str(entry.get('ec5_uuid'))
        if 'id' in entry:
            return str(entry.get('id'))
    return None


def main():
    if not ensure_cache():
        print('Cache unavailable; cannot generate recent tree list.')
        raise SystemExit(1)

    entries = load_entries()
    if not entries:
        print('No entries found in cache; aborting')
        raise SystemExit(1)

    rows = []
    for e in entries:
        created = entry_created_at(e) or datetime.min
        tid = tree_id_from_entry(e) or e.get('ec5_uuid') or e.get('id')
        species = ''
        # try common species fields
        if isinstance(e, dict):
            for k in ('3_Species', 'species'):
                if k in e:
                    v = e.get(k)
                    if isinstance(v, list):
                        species = '; '.join(str(x) for x in v)
                    else:
                        species = str(v)
                    break
        rows.append((created, tid, species))

    # sort descending by created
    rows = sorted(rows, key=lambda r: r[0], reverse=True)
    top = rows[:10]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append('# Recent tree updates')
    lines.append('')
    for created, tid, species in top:
        created_str = created.strftime('%Y') if created and created != datetime.min else ''
        link = f'trees/{tid}.qmd' if tid else ''
        title = f'Tree {tid}' if tid else 'Tree'
        if species:
            title = f'{title} — {species}'
        if link:
            lines.append(f'- [{title}]({link}) — {created_str}')
        else:
            lines.append(f'- {title} — {created_str}')

    OUT.write_text('\n'.join(lines), encoding='utf8')
    print('Wrote', OUT)


if __name__ == '__main__':
    main()
