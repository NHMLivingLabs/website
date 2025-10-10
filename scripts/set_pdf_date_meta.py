"""Set PDF /CreationDate and /ModDate to a provided YYYY-MM-DD date (or infer from corresponding .qmd).

Usage:
  python scripts/set_pdf_date_meta.py <pdf-path> <yyyy-mm-dd>

If date is omitted, the script will try to find a matching .qmd in reports/ and extract the `date:` frontmatter.
"""
from pathlib import Path
import sys
from datetime import datetime

try:
    from PyPDF2 import PdfReader, PdfWriter
except Exception:
    print("PyPDF2 is required. Install with: python -m pip install PyPDF2")
    raise


def extract_date_from_frontmatter(qmd_path: Path):
    try:
        txt = qmd_path.read_text(encoding='utf-8')
    except Exception:
        return None
    lines = txt.splitlines()
    if not lines or not lines[0].strip().startswith('---'):
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            end = i
            break
    if end is None:
        return None
    fm_lines = lines[1:end]
    for ln in fm_lines:
        if ln.strip().lower().startswith('date'):
            parts = ln.split(':', 1)
            if len(parts) == 2:
                return parts[1].strip().strip('"\'')
    return None


def to_pdf_date(ymd: str):
    # ymd expected like YYYY-MM-DD or other human forms; try parse with datetime
    # we'll output PDF date in format: D:YYYYMMDDHHmmSS+00'00'
    for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%d %b %Y', '%d %B %Y'):
        try:
            dt = datetime.strptime(ymd, fmt)
            break
        except Exception:
            dt = None
    if dt is None:
        # try to parse ISO-ish
        try:
            dt = datetime.fromisoformat(ymd)
        except Exception:
            # fallback: date only parse by splitting
            parts = ymd.split()[0].split('-')
            if len(parts) >= 3:
                try:
                    dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
                except Exception:
                    dt = None
    if dt is None:
        raise ValueError(f"Unable to parse date string: {ymd}")
    pdf_date = dt.strftime("D:%Y%m%d%H%M%S+00'00'")
    return pdf_date


def main():
    if len(sys.argv) < 2:
        print('Usage: python scripts/set_pdf_date_meta.py <pdf-path> [yyyy-mm-dd]')
        raise SystemExit(2)
    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print('PDF not found:', pdf_path)
        raise SystemExit(1)
    date_arg = sys.argv[2] if len(sys.argv) >= 3 else None
    if not date_arg:
        # try infer from reports/<stem>.qmd
        stem = pdf_path.stem
        qmd = Path('reports') / (stem + '.qmd')
        if qmd.exists():
            date_arg = extract_date_from_frontmatter(qmd)
            if not date_arg:
                print('No date in frontmatter of', qmd)
                raise SystemExit(1)
        else:
            print('No date provided and no matching .qmd found to infer date')
            raise SystemExit(1)
    # normalize
    try:
        pdf_date = to_pdf_date(date_arg)
    except Exception as e:
        print('Failed to parse date:', e)
        raise

    # Read original PDF and write new one with updated metadata
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    # preserve existing metadata as base
    orig_md = reader.metadata or {}
    new_md = {}
    # Copy string metadata but we'll overwrite CreationDate/ModDate
    for k, v in orig_md.items():
        # PyPDF2 metadata keys are like '/Producer'
        if k in ('/CreationDate', '/ModDate'):
            continue
        new_md[k] = v
    new_md['/CreationDate'] = pdf_date
    new_md['/ModDate'] = pdf_date
    writer.add_metadata(new_md)
    tmp = pdf_path.with_suffix('.meta.tmp.pdf')
    with tmp.open('wb') as f:
        writer.write(f)
    tmp.replace(pdf_path)
    print('Updated PDF metadata for', pdf_path, 'to', pdf_date)


if __name__ == '__main__':
    main()
