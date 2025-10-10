"""Check whether generated PDFs contain the frontmatter date visibly.

Checks performed per-PDF:
- raw bytes scan for the date string
- try to read PDF metadata using PyPDF2 (if available)
- try to extract first page text using PyPDF2

Usage: python scripts/check_pdf_date.py
"""
from pathlib import Path

PDFS = [
    Path('docs/assets/pdfs/1_Published_Protocol_2025_Tree-Tagging.pdf'),
    Path('docs/assets/pdfs/2_Published-Protocol_2025_Tree-Survey.pdf'),
    Path('docs/assets/pdfs/3_Implementation-Report_DS18B20-Thermometers.pdf'),
]

# The date we injected from frontmatter in previous run(s).
EXPECTED_DATE = '2025-10-05'


def check_pdf(p: Path, date_str: str):
    print('\n---')
    print('Checking', p)
    if not p.exists():
        print('MISSING:', p)
        return
    b = p.read_bytes()
    found_raw = date_str.encode('utf-8') in b
    print('Found date string in raw PDF bytes:', found_raw)

    try:
        from PyPDF2 import PdfReader
    except Exception as e:
        print('PyPDF2 not available:', e)
        if found_raw:
            idx = b.find(date_str.encode('utf-8'))
            start = max(0, idx-100)
            end = min(len(b), idx+100)
            print('Raw context around match (bytes):')
            print(b[start:end])
        return

    try:
        r = PdfReader(str(p))
        md = r.metadata
        print('PDF metadata:', md)
        text = ''
        try:
            page = r.pages[0]
            text = page.extract_text() or ''
            print('First page text (first 400 chars):')
            print(text[:400])
        except Exception as e:
            print('Failed to extract page text:', e)
        if date_str in text:
            print('Date string found in page text')
        else:
            print('Date string NOT found in page text')
    except Exception as e:
        print('Failed to open/read PDF with PyPDF2:', e)


if __name__ == '__main__':
    for p in PDFS:
        check_pdf(p, EXPECTED_DATE)
    print('\nDone')
