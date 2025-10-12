"""Sanitise PDFs by removing non-deterministic metadata.

This script removes or normalizes the following from PDF files:
 - Document Info metadata entries like /Producer, /Creator, /CreationDate, /ModDate, /Title, /Author, /Subject, /Keywords
 - XMP metadata (if present)
 - PDF ID (so file-level IDs are not preserved)

Usage examples:
    python scripts/clean_pdfs.py docs/assets/pdfs
    python scripts/clean_pdfs.py docs/assets/pdfs/*.pdf --inplace
    python scripts/clean_pdfs.py --pattern "docs/assets/pdfs/*.pdf" --dry-run

Behavior:
 - By default the script writes sanitised copies next to originals with a .sanitised.pdf suffix.
 - Use --inplace to overwrite originals (creates a .bak backup unless --no-backup is set).
 - Use --pattern to provide a glob pattern instead of file arguments.
 - The script is careful not to modify files when run with --dry-run.

Note: This script depends on PyPDF2. Install it in your project's virtualenv:
    pip install PyPDF2

"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path
from typing import Iterable

try:
    from PyPDF2 import PdfReader, PdfWriter
except Exception:  # pragma: no cover - runtime dependency
    raise SystemExit("PyPDF2 is required: install with 'pip install PyPDF2'")


def sanitise_pdf(src: Path, dst: Path) -> None:
    """Read a PDF from ``src``, normalize run-dependent metadata, and write to ``dst``.

    The function sets deterministic document-info metadata via the public API and
    post-processes the written bytes to normalize the PDF /ID array and remove
    XMP packets which commonly include timestamps.
    """
    reader = PdfReader(str(src))
    writer = PdfWriter()

    # copy pages
    for p in reader.pages:
        writer.add_page(p)

    # Deterministic metadata values. add_metadata expects keys without leading '/'.
    deterministic_meta = {
        "/Producer": "",
        "/Creator": "",
        "/CreationDate": "D:19700101000000",
        "/ModDate": "D:19700101000000",
    }
    # Use the public API; some PyPDF2 versions expect keys without '/'
    writer.add_metadata(deterministic_meta)

    # Write a first-pass PDF to dst
    with dst.open("wb") as f:
        writer.write(f)

    # Post-process the written PDF bytes to normalize the /ID array and strip XMP packets
    data = dst.read_bytes()

    # Normalize /ID [<hex> <hex>] to a fixed ID
    data = re.sub(
        rb"/ID\s*\[\s*<[^>]+>\s*<[^>]+>\s*\]",
        rb"/ID [<00000000000000000000000000000000> <00000000000000000000000000000000>]",
        data,
    )

    # Remove XMP metadata blocks (<x:xmpmeta> ... </x:xmpmeta>) which often include timestamps
    data = re.sub(rb"<x:xmpmeta[\s\S]*?</x:xmpmeta>", b"", data, flags=re.IGNORECASE)

    dst.write_bytes(data)


def iter_targets(args) -> Iterable[Path]:
    if args.pattern:
        for p in Path().glob(args.pattern):
            if p.is_file() and p.suffix.lower() == ".pdf" and ".sanitised" not in p.name:
                yield p
        return

    for a in args.paths:
        p = Path(a)
        if p.is_dir():
            for f in p.iterdir():
                if f.is_file() and f.suffix.lower() == ".pdf" and ".sanitised" not in f.name:
                    yield f
        elif p.is_file() and p.suffix.lower() == ".pdf":
            if ".sanitised" not in p.name:
                yield p


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sanitise PDFs by removing non-deterministic metadata")
    p.add_argument("paths", nargs="*", help="Files or directories to process", default=["docs/assets/pdfs"])
    p.add_argument("--pattern", help="Glob pattern to select files (e.g. 'docs/assets/pdfs/*.pdf')")
    p.add_argument("--inplace", action="store_true", help="Overwrite original files (creates .bak backups by default)")
    p.add_argument("--no-backup", action="store_true", help="When --inplace is used, do not keep a .bak backup")
    p.add_argument("--dry-run", action="store_true", help="List targets without modifying files")
    p.add_argument("--verbose", action="store_true", help="Print progress messages")
    args = p.parse_args(argv)

    targets = list(iter_targets(args))
    if not targets:
        if args.verbose:
            print("No PDF targets found.")
        return 1

    for src in targets:
        if args.dry_run:
            print("Would sanitise:", src)
            continue
        if args.inplace:
            bak = src.with_suffix(src.suffix + ".bak")
            if not args.no_backup:
                shutil.copy2(src, bak)
            tmp = src.with_suffix(".sanitised.tmp.pdf")
            sanitise_pdf(src, tmp)
            shutil.move(str(tmp), str(src))
            if args.verbose:
                print("Sanitised inplace:", src)
        else:
            out = src.with_name(src.stem + ".sanitised.pdf")
            sanitise_pdf(src, out)
            if args.verbose:
                print("Wrote sanitised copy:", out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
