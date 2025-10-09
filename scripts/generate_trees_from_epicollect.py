"""Minimal tree page generator using Epicollect documented export API.

This file is intentionally small and focused. It:
- Fetches entries from /api/export/entries/{project_slug} using the
  provided FORM_REF.
- Prefers the `2_Tree_Number` field as the canonical identifier and falls
  back to `ec5_uuid`/`id` when missing.
- Optionally downloads the primary image referenced in the entry using
  /api/export/media/{project_slug} and writes it to
  `assets/images/trees/tree<id>.jpg`.
- Writes a simple Quarto page to `trees/<id>.qmd` and does not overwrite
  existing pages unless `--force` is supplied.

Auth: set EPICOLLECT_TOKEN in the environment for a bearer token, or set
EPICOLLECT_CLIENT_ID and EPICOLLECT_CLIENT_SECRET (and optionally
EPICOLLECT_TOKEN_URL) to obtain a token using the client_credentials flow.

Usage:
  python scripts/generate_trees_from_epicollect.py [--force] [--no-download] [--dry-run]
"""

from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error
import json
import os
import argparse
import re
from datetime import datetime


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / 'trees'
IMG_DIR = ROOT / 'assets' / 'images' / 'trees'


def load_dotenv_if_exists(root: Path):
    """Minimal .env loader: reads KEY=VALUE lines from repo .env and sets os.environ if not present.
    Handles UTF-8 BOM by decoding with utf-8-sig."""
    env_path = root / '.env'
    if not env_path.exists():
        return
    try:
        text = env_path.read_text(encoding='utf8')
    except Exception:
        # fallback to utf-8-sig to handle BOMs
        try:
            text = env_path.read_text(encoding='utf-8-sig')
        except Exception:
            return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, v = line.split('=', 1)
            k = k.strip()
            v = v.strip()
            # do not overwrite existing environment variables; allow explicit env to take precedence
            if k and (k not in os.environ or not os.environ.get(k)):
                os.environ[k] = v


# Load .env from repo root if present so that Quarto-invoked processes pick up credentials
load_dotenv_if_exists(ROOT)

# Project-specific configuration
PROJECT_SLUG = 'nhm-urs-tree-dbh'
# Hard-coded form_ref (per instructions)
FORM_REF = 'cfdf37225027464f8102e8a1ff29637a_68df814906e40'

# Environment-driven auth (token OR client credentials)
EPICOLLECT_TOKEN = os.environ.get('EPICOLLECT_TOKEN')
EPICOLLECT_CLIENT_ID = os.environ.get('EPICOLLECT_CLIENT_ID')
EPICOLLECT_CLIENT_SECRET = os.environ.get('EPICOLLECT_CLIENT_SECRET')
EPICOLLECT_TOKEN_URL = os.environ.get('EPICOLLECT_TOKEN_URL', 'https://five.epicollect.net/oauth/token')


def http_get_bytes(url, headers=None, timeout=20):
    headers = headers or {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

"""Minimal tree page generator using Epicollect documented export API.

This file is intentionally small and focused. It:
- Fetches entries from /api/export/entries/{project_slug} using the
  provided FORM_REF.
- Prefers the `2_Tree_Number` field as the canonical identifier and falls
  back to `ec5_uuid`/`id` when missing.
- Optionally downloads the primary image referenced in the entry using
  /api/export/media/{project_slug} and writes it to
  `assets/images/trees/tree<id>.jpg`.
- Writes a simple Quarto page to `trees/<id>.qmd` and does not overwrite
  existing pages unless `--force` is supplied.

Auth: set EPICOLLECT_TOKEN in the environment for a bearer token, or set
EPICOLLECT_CLIENT_ID and EPICOLLECT_CLIENT_SECRET (and optionally
EPICOLLECT_TOKEN_URL) to obtain a token using the client_credentials flow.

Usage:
  python scripts/generate_trees_from_epicollect.py [--force] [--no-download] [--dry-run]
"""

from pathlib import Path
import urllib.request
import urllib.parse
import json
import os
import argparse
import re
from datetime import datetime


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / 'trees'
IMG_DIR = ROOT / 'assets' / 'images' / 'trees'


def load_dotenv_if_exists(root: Path):
    """Minimal .env loader: reads KEY=VALUE lines from repo .env and sets os.environ if not present.
    Handles UTF-8 BOM by decoding with utf-8-sig."""
    env_path = root / '.env'
    if not env_path.exists():
        return
    try:
        text = env_path.read_text(encoding='utf8')
    except Exception:
        # fallback to utf-8-sig to handle BOMs
        try:
            text = env_path.read_text(encoding='utf-8-sig')
        except Exception:
            return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, v = line.split('=', 1)
            k = k.strip()
            v = v.strip()
            # do not overwrite existing environment variables; allow explicit env to take precedence
            if k and (k not in os.environ or not os.environ.get(k)):
                os.environ[k] = v


# Load .env from repo root if present so that Quarto-invoked processes pick up credentials
load_dotenv_if_exists(ROOT)

# Project-specific configuration
PROJECT_SLUG = 'nhm-urs-tree-dbh'
# Hard-coded form_ref (per instructions)
FORM_REF = 'cfdf37225027464f8102e8a1ff29637a_68df814906e40'

# Environment-driven auth (token OR client credentials)
EPICOLLECT_TOKEN = os.environ.get('EPICOLLECT_TOKEN')
EPICOLLECT_CLIENT_ID = os.environ.get('EPICOLLECT_CLIENT_ID')
EPICOLLECT_CLIENT_SECRET = os.environ.get('EPICOLLECT_CLIENT_SECRET')
EPICOLLECT_TOKEN_URL = os.environ.get('EPICOLLECT_TOKEN_URL', 'https://five.epicollect.net/oauth/token')


def http_get_bytes(url, headers=None, timeout=20):
    headers = headers or {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def obtain_client_credentials_token(client_id, client_secret, token_url):
    if not (client_id and client_secret and token_url):
        return None
    payload = {'grant_type': 'client_credentials', 'client_id': client_id, 'client_secret': client_secret}
    data = json.dumps(payload).encode('utf8')
    headers = {'Content-Type': 'application/vnd.api+json', 'User-Agent': 'nhm-urs-tree-downloader/1.0', 'Accept': 'application/json'}
    try:
        req = urllib.request.Request(token_url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            j = json.loads(resp.read().decode('utf8'))
            return j.get('access_token')
    except Exception as e:
        print('Failed to obtain client_credentials token:', e)
        return None


def fetch_entries(project_slug, form_ref, token=None):
    base = f'https://five.epicollect.net/api/export/entries/{project_slug}'
    params = {'form_ref': form_ref, 'format': 'json', 'headers': 'true'}
    url = base + '?' + urllib.parse.urlencode(params)
    headers = {'User-Agent': 'nhm-urs-tree-downloader/1.0', 'Accept': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        print('Fetching entries from', url)
        raw = http_get_bytes(url, headers=headers)
        j = json.loads(raw.decode('utf8'))
        # cache Epicollect exports under the repo-level cache directory (ignored by git)
        meta_dir = ROOT / 'cache' / 'epicollect-meta'
        meta_dir.mkdir(parents=True, exist_ok=True)
        outp = meta_dir / f'entries_{project_slug}.json'
        outp.write_text(json.dumps(j, indent=2), encoding='utf8')
        return j
    except Exception as e:
        print('Failed to fetch entries:', e)
        return None


def find_tree_number_in_entry(entry):
    # prefer explicit 2_Tree_Number-like keys (case-insensitive)
    if isinstance(entry, dict):
        for k, v in entry.items():
            if isinstance(k, str) and re.match(r"^\s*2[_\s-]*tree[_\s-]*number\s*$", k, re.I):
                if isinstance(v, (int, float)):
                    try:
                        if float(v).is_integer():
                            return str(int(v))
                    except Exception:
                        return str(v)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        # fallback: any key containing 'tree' and a numeric-looking value
        for k, v in entry.items():
            if isinstance(k, str) and 'tree' in k.lower():
                if isinstance(v, (int, float)):
                    try:
                        if float(v).is_integer():
                            return str(int(v))
                    except Exception:
                        return str(v)
                if isinstance(v, str) and v.strip().isdigit():
                    return v.strip()
    return None


def find_photo_filename(entry):
    # recursively find the first filename-like value in the entry
    def walk(o):
        if isinstance(o, dict):
            for vv in o.values():
                r = walk(vv)
                if r:
                    return r
        elif isinstance(o, list):
            for it in o:
                r = walk(it)
                if r:
                    return r
        elif isinstance(o, str):
            s = o.strip()
            if s and (s.lower().endswith(('.jpg', '.jpeg', '.png')) or re.search(r'[0-9a-fA-F\-]{8,}_\d+\.jpg', s)):
                return s
        return None

    return walk(entry)


def write_tree_page(tree_id, cols, species_raw, photo_path, force=False):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    outpath = OUT_DIR / f'{tree_id}.qmd'
    if outpath.exists() and not force:
        print('Skipping existing', outpath, '(use --force to overwrite)')
        return outpath

    # Basic display name extraction
    common_name = ''
    m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", species_raw or '')
    if m:
        common_name = m.group(1).strip()
    else:
        common_name = (species_raw or '').strip()

    display_name = common_name or f'Tree {tree_id}'

    lines = []
    lines.append('---')
    lines.append(f'title: "Tree {tree_id} - {display_name}"')
    lines.append('toc: false')
    lines.append('---\n')
    # _tree-search include intentionally omitted here; search UI is only on /trees/index.html
    lines.append('')
    # advisory comment for developers: generated file warning
    lines.append('<!-- This file is generated by scripts/generate_trees_from_epicollect.py. Do not edit this file directly; update the generator or the underlying data sources instead. -->')
    lines.append('')
    # attempt to find a species info include from trees/_tree-species-info
    inc_rel = None
    try:
        common = ''
        m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", species_raw or '')
        if m:
            common = m.group(1).strip()
        else:
            common = (species_raw or '').strip()

        if common:
            inc_dir = ROOT / 'trees' / '_tree-species-info'
            inc_file = None
            slug_common = re.sub(r"[^0-9a-zA-Z-]+", "-", common.lower()).strip('-')
            # look for direct filename matches first
            if inc_dir.exists():
                for f in inc_dir.iterdir():
                    if not f.is_file() or f.suffix.lower() != '.md':
                        continue
                    stem = f.name.lstrip('_').rsplit('.md', 1)[0]
                    if stem == slug_common or stem.endswith('-' + slug_common) or stem.startswith(slug_common + '-'):
                        inc_file = f
                        break
                # if not found, search file contents for the common name
                if not inc_file:
                    for f in inc_dir.iterdir():
                        if not f.is_file() or f.suffix.lower() != '.md':
                            continue
                        try:
                            txt = f.read_text(encoding='utf-8').lower()
                            if common.lower() in txt:
                                inc_file = f
                                break
                        except Exception:
                            continue

            if inc_file and inc_file.exists():
                try:
                    rel = os.path.relpath(inc_file, OUT_DIR)
                    rel = rel.replace('\\', '/')
                    inc_rel = rel
                except Exception:
                    pass
    except Exception:
        pass
    if photo_path and photo_path.exists():
        img_rel = f'/assets/images/trees/{photo_path.name}'
        lines.append(f'![Tree {tree_id} - {display_name}]({img_rel})')
    else:
        lines.append(f'![Tree {tree_id} - {display_name}](/assets/images/trees/tree{tree_id}.jpg)')
    # one clear blank line between image and include (if present)
    lines.append('')
    if inc_rel:
        # Emit positional include syntax (no file=) to match project conventions
        lines.append(f"{{{{< include '{inc_rel}' >}}}}")
        lines.append('')
    lines.append('## Tree data')
    lines.append('')
    site = cols.get('1_Site') or cols.get('site') or ''
    if isinstance(site, list):
        site = '; '.join(site)
    lines.append(f'**Planted:** {site or "Wildlife Garden (1994?)"}')
    lines.append('')

    diameter = cols.get('6_Diameter_at_12m_fr') or cols.get('diameter') or ''
    dateval = cols.get('5_Date') or cols.get('date') or ''
    diam_text = ''
    try:
        if diameter is not None and str(diameter).strip() not in ('', '0', '0.0', '0cm'):
            dflt = float(diameter)
            if dflt != 0:
                diam_text = f"{int(dflt) if dflt.is_integer() else dflt}cm"
    except Exception:
        if diameter:
            diam_text = f'{diameter}cm'
    if diam_text and dateval:
        diam_text = f'{diam_text} ({dateval})'
    if diam_text:
        lines.append(f'**Diameter at breast height (1.2m):** {diam_text}')
        lines.append('')

    if not photo_path or not photo_path.exists():
        lines.append('<!-- Image not available locally -->')
        lines.append('')

    outpath.write_text('\n'.join(lines), encoding='utf8')
    print('Wrote', outpath)
    return outpath


def download_image(project_slug, photo_filename, target_path, token=None):
    if not photo_filename:
        return False
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    media_url = f'https://five.epicollect.net/api/export/media/{project_slug}?type=photo&format=entry_original&name=' + urllib.parse.quote(photo_filename)
    headers = {'User-Agent': 'nhm-urs-tree-downloader/1.0', 'Accept': 'image/*,*/*;q=0.8'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        print('Attempting download from', media_url)
        data = http_get_bytes(media_url, headers=headers)
        if data:
            target_path.write_bytes(data)
            print('Saved image to', target_path)
            return True
    except Exception as e:
        print('Image download failed:', e)
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--force', action='store_true', help='Overwrite existing tree pages')
    p.add_argument('--no-download', action='store_true', help='Do not attempt to download images')
    p.add_argument('--dry-run', action='store_true', help='Show what would be done')
    args = p.parse_args()

    # Resolve token: explicit EPICOLLECT_TOKEN takes precedence; otherwise try client credentials
    token = EPICOLLECT_TOKEN
    if not token and EPICOLLECT_CLIENT_ID and EPICOLLECT_CLIENT_SECRET:
        token = obtain_client_credentials_token(EPICOLLECT_CLIENT_ID, EPICOLLECT_CLIENT_SECRET, EPICOLLECT_TOKEN_URL)

    entries_json = fetch_entries(PROJECT_SLUG, FORM_REF, token=token)
    if not entries_json:
        print('No entries fetched. Exiting.')
        return

    # extract entries list from typical export shapes
    entries = []
    if isinstance(entries_json, dict):
        data = entries_json.get('data') or entries_json.get('entries') or entries_json
        if isinstance(data, dict):
            entries = data.get('entries') or data.get('data') or []
        elif isinstance(data, list):
            entries = data

    if not entries:
        print('No entries found in export.')
        return

    for entry in entries:
        # canonical id: prefer 2_Tree_Number, else ec5_uuid/id
        tree_no = find_tree_number_in_entry(entry)
        ec5 = None
        if isinstance(entry, dict):
            ec5 = entry.get('ec5_uuid') or entry.get('id')
        tree_id = tree_no or ec5
        if not tree_id:
            print('Skipping entry without id')
            continue

        # simple flat mapping for fields used by template
        cols = {}
        if isinstance(entry, dict):
            for k, v in entry.items():
                cols[k] = v

        # species extraction (best-effort)
        species_raw = ''
        if isinstance(entry, dict):
            if '3_Species' in entry:
                sp = entry.get('3_Species')
                if isinstance(sp, list):
                    species_raw = '; '.join(str(x) for x in sp)
                else:
                    species_raw = str(sp)
            else:
                for k in entry.keys():
                    if 'species' in k.lower():
                        val = entry.get(k)
                        if isinstance(val, list):
                            species_raw = '; '.join(str(x) for x in val)
                        else:
                            species_raw = str(val)
                        break

        photo_filename = find_photo_filename(entry)
        local_img_path = IMG_DIR / f'tree{tree_id}.jpg'

        if not args.no_download and photo_filename:
            if not args.dry_run:
                success = download_image(PROJECT_SLUG, photo_filename, local_img_path, token=token)
                if not success:
                    print('Could not download media for', tree_id)

        if args.dry_run:
            print('Would write page for', tree_id)
        else:
            write_tree_page(tree_id, cols, species_raw, local_img_path if local_img_path.exists() else None, force=args.force)


if __name__ == '__main__':
    main()
