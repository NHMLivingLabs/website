#!/usr/bin/env python3
"""
Render PDFs for reports using pandoc -> LaTeX -> xelatex.

By default this script will render every `.qmd` file in the `reports/` directory.
This script will NEVER render a top-level `articles.qmd` to PDF.

Use --all to render every .qmd file found (excludes `docs/`, `assets/`, `site_libs`, and `scripts/`).

Notes:
 - This script uses `pandoc` to convert QMD/Markdown to LaTeX and then runs a TeX engine
     (`xelatex` preferred, falls back to `pdflatex`).
 - A working TeX distribution (TinyTeX, TeX Live, MikTeX) is required for PDF creation.
 - This script supports a --dry-run mode which will list files without invoking the renderer.
"""

import argparse
import shutil
import subprocess
from pathlib import Path
import sys
import re


ROOT = Path(__file__).resolve().parents[1]
PERSIST_SANITIZED = False


def find_targets(all_qmd: bool):
    files = []
    if all_qmd:
        # find all .qmd except in excluded folders
        for p in ROOT.rglob('*.qmd'):
            if any(part in ('docs', 'assets', 'site_libs', 'scripts') for part in p.parts):
                continue
            # always exclude the top-level articles.qmd from PDF rendering
            if p.name == 'articles.qmd' and p.parent == ROOT:
                continue
            files.append(p)
    else:
        # default: anything in reports/ (explicitly do NOT render top-level articles.qmd)
        repdir = ROOT / 'reports'
        if repdir.exists() and repdir.is_dir():
            files.extend(sorted(repdir.glob('*.qmd')))

    # dedupe and return
    seen = set()
    out = []
    for p in files:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(rp)
    return out


def extract_author_name_from_frontmatter(path: Path):
    """Return a string with one or more author names (comma-joined), or None.

        Strategy:
        - Use a resilient line-based heuristic that handles:
      * scalar: author: Ed Baker
      * list of strings: author: ["A", "B"]
      * list of mappings: author:\n  - name: Ed Baker\n    affiliation: ...
      * mapping: author: { name: Ed Baker }
    """
    try:
        txt = path.read_text(encoding='utf-8')
    except Exception:
        return None

    # Extract frontmatter block
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
    fm_text = '\n'.join(lines[1:end])

    # Note: we intentionally avoid external YAML parsers. Use resilient line-based
    # heuristics below to extract author information from the frontmatter.

    # Fallback heuristic parsing (no external YAML parser dependency)
    # Look for scalar author: line
    for ln in fm_text.splitlines():
        m = re.match(r"^\s*author\s*:\s*(?:\[)?\s*['\"]?(.+?)['\"]?\s*(?:\])?\s*$", ln)
        if m:
            # Might be a scalar or first element of inline list
            candidate = m.group(1).strip()
            if candidate.lower() in ('true', 'false'):
                # ignore boolean-like misparses
                continue
            return candidate

    # Look for a YAML list block 'author:' followed by '- name: ...' or '- "Name"' lines
    in_author = False
    names = []
    for ln in fm_text.splitlines():
        if re.match(r"^\s*author\s*:\s*$", ln):
            in_author = True
            continue
        if in_author:
            # end of author block if new top-level key
            if re.match(r"^\S", ln) and ':' in ln:
                break
            # - name: Foo
            m = re.match(r"^\s*-\s*name\s*:\s*(.+)$", ln)
            if m:
                names.append(m.group(1).strip().strip('"\''))
                continue
            # - Foo  (list of strings)
            m2 = re.match(r"^\s*-\s*(?:['\"]?)(.+?)(?:['\"]?)\s*$", ln)
            if m2:
                val = m2.group(1).strip()
                if val.lower() not in ('true', 'false'):
                    names.append(val)
                    continue
            # name: Foo inside an author mapping
            m3 = re.match(r"^\s*name\s*:\s*(.+)$", ln)
            if m3:
                names.append(m3.group(1).strip().strip('"\''))
                continue

    if names:
        return ', '.join(names)

    return None


def extract_authors_with_affiliations(path: Path):
    """Return a list of {'name':..., 'affiliation':...} dicts parsed from frontmatter.

    Uses resilient heuristics to avoid depending on an external YAML parser.
    """
    try:
        txt = path.read_text(encoding='utf-8')
    except Exception:
        return []

    # Extract frontmatter block
    lines = txt.splitlines()
    if not lines or not lines[0].strip().startswith('---'):
        return []
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            end = i
            break
    if end is None:
        return []
    fm_text = '\n'.join(lines[1:end])

    # Note: avoid external YAML parser dependency; use heuristic parsing below.
    out = []

    # Heuristic parsing if PyYAML unavailable or failed
    def _unq(s: str) -> str:
        return (s or '').strip().strip('"\'')

    in_author = False
    current = None
    for ln in fm_text.splitlines():
        if re.match(r"^\s*author\s*:\s*$", ln):
            in_author = True
            continue
        if in_author:
            # new list item like '- name: Foo' or '- Foo'
            m = re.match(r'^\s*-\s*(?:name\s*:\s*)?["\']?(.*?)["\']?\s*$', ln)
            if m:
                if current:
                    out.append(current)
                current = {'name': _unq(m.group(1)), 'affiliation': ''}
                continue
            m_name = re.match(r"^\s*name\s*:\s*(.+)$", ln)
            if m_name:
                if not current:
                    current = {'name': _unq(m_name.group(1)), 'affiliation': ''}
                else:
                    current['name'] = _unq(m_name.group(1))
                continue
            m_aff = re.match(r"^\s*(?:affiliation|affil)\s*:\s*(.+)$", ln)
            if m_aff:
                if not current:
                    current = {'name': '', 'affiliation': _unq(m_aff.group(1))}
                else:
                    current['affiliation'] = _unq(m_aff.group(1))
                continue
            # end if new top-level key appears
            if re.match(r"^\S", ln) and ':' in ln:
                in_author = False
                if current:
                    out.append(current)
                    current = None
                break
    if current:
        out.append(current)
    # Fallback: if nothing parsed, attempt to locate inline author scalar
    if not out:
        m = re.search(r"^\s*author\s*:\s*['\"]?(.+?)['\"]?\s*$", fm_text, re.MULTILINE)
        if m:
            vals = [s.strip() for s in re.split(r"\s*,\s*", m.group(1)) if s.strip()]
            for v in vals:
                out.append({'name': v, 'affiliation': ''})
    return out


def run_pandoc_xelatex(src: Path, outdir: Path):
    """Render a single QMD -> PDF using pandoc to create .tex and xelatex to build PDF.

    """
    outdir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    outtex = outdir / (stem + '.tex')
    outpdf = outdir / (stem + '.pdf')

    # Ensure pandoc available; prefer PATH, but fall back to Quarto/RStudio-bundled pandoc
    pandoc_path = shutil.which('pandoc')
    if not pandoc_path:
        # Common place: RStudio/Quarto bundled pandoc
        possible = Path('C:/Program Files/RStudio/resources/app/bin/quarto/bin/tools/pandoc.exe')
        if possible.exists():
            pandoc_path = str(possible)
        else:
            possible2 = Path('C:/Program Files/Quarto/bin/pandoc.exe')
            if possible2.exists():
                pandoc_path = str(possible2)

    if not pandoc_path:
        print('Error: pandoc not found on PATH and no bundled pandoc detected. Install pandoc and retry.', file=sys.stderr)
        return subprocess.CompletedProcess(args=['pandoc'], returncode=2)

    # Choose TeX engine
    tex_engine = 'xelatex' if shutil.which('xelatex') else ('pdflatex' if shutil.which('pdflatex') else None)
    if tex_engine is None:
        print('Error: No TeX engine found (xelatex or pdflatex). Install a TeX distribution and retry.', file=sys.stderr)
        return subprocess.CompletedProcess(args=['xelatex'], returncode=3)

    # 1) Run pandoc to produce .tex
    # Try to extract a simple author name from the QMD frontmatter and pass
    # it explicitly to pandoc to avoid metadata parsing oddities (which can
    # produce 'true' for complex author YAML blocks).
    def extract_author_name_from_frontmatter(path: Path):
        """Return a string with one or more author names (comma-joined), or None.

        Strategy:
                - Use a resilient line-based heuristic that handles:
          * scalar: author: Ed Baker
          * list of strings: author: ["A", "B"]
          * list of mappings: author:\n  - name: Ed Baker\n    affiliation: ...
          * mapping: author: { name: Ed Baker }
        """
        try:
            txt = path.read_text(encoding='utf-8')
        except Exception:
            return None

        # Extract frontmatter block
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
        fm_text = '\n'.join(lines[1:end])

    # Note: avoid PyYAML dependency; use heuristic parsing below.

    # Fallback heuristic parsing when an external YAML parser isn't present or parsing fails
        # Look for scalar author: line
        for ln in fm_text.splitlines():
            m = re.match(r"^\s*author\s*:\s*(?:\[)?\s*['\"]?(.+?)['\"]?\s*(?:\])?\s*$", ln)
            if m:
                # Might be a scalar or first element of inline list
                candidate = m.group(1).strip()
                if candidate.lower() in ('true', 'false'):
                    # ignore boolean-like misparses
                    continue
                return candidate

        # Look for a YAML list block 'author:' followed by '- name: ...' or '- "Name"' lines
        in_author = False
        names = []
        for ln in fm_text.splitlines():
            if re.match(r"^\s*author\s*:\s*$", ln):
                in_author = True
                continue
            if in_author:
                # end of author block if new top-level key
                if re.match(r"^\S", ln) and ':' in ln:
                    break
                # - name: Foo
                m = re.match(r"^\s*-\s*name\s*:\s*(.+)$", ln)
                if m:
                    names.append(m.group(1).strip().strip('"\''))
                    continue
                # - Foo  (list of strings)
                m2 = re.match(r"^\s*-\s*(?:['\"]?)(.+?)(?:['\"]?)\s*$", ln)
                if m2:
                    val = m2.group(1).strip()
                    if val.lower() not in ('true', 'false'):
                        names.append(val)
                        continue
                # name: Foo inside an author mapping
                m3 = re.match(r"^\s*name\s*:\s*(.+)$", ln)
                if m3:
                    names.append(m3.group(1).strip().strip('"\''))
                    continue

        if names:
            return ', '.join(names)

        return None

    author_name = extract_author_name_from_frontmatter(src)
    pandoc_cmd = [pandoc_path, str(src), '--from', 'markdown', '--to', 'latex', '--standalone', '-o', str(outtex)]
    tmp_meta = None
    temp_input = None
    persistent_sanitized_path = None
    try:
        # Preprocess the QMD to remove HTML-only/quarto-only blocks so pandoc -> LaTeX
        # rendering does not accidentally include HTML-only content.
        orig_text = src.read_text(encoding='utf-8')

        def _remove_html_only_quarto_blocks(text: str) -> str:
            # Remove fenced raw HTML blocks: ```{=html} ... ``` (handles variations)
            text = re.sub(r"```\{\s*=\s*html[^}]*\}[\s\S]*?```\s*", "", text, flags=re.IGNORECASE)
            # Remove Quarto conditional blocks like ::: {.content-visible when-format="html"} ... :::
            # Use a non-greedy match and allow single or double quotes in attributes.
            text = re.sub(r":::\s*\{[^}]*when-format\s*=\s*(?:\"|')?html(?:\"|')?[^}]*\}[\s\S]*?:::\s*", "", text, flags=re.IGNORECASE)
            # Remove HTML tags with when-format attribute: <div ... when-format="html">...</div>
            text = re.sub(r"<[^>]*when-format\s*=\s*(?:\"|')?html(?:\"|')?[^>]*>[\s\S]*?<\/[a-zA-Z0-9:_-]+>\s*", "", text, flags=re.IGNORECASE)
            # Remove markdown elements that have inline when-format="html" attributes, e.g. [text](url){... when-format="html"}
            text = re.sub(r"(!?\[[^\]]*\]\([^\)]*\)\s*\{[^}]*when-format\s*=\s*(?:\"|')?html(?:\"|')?[^}]*\})", "", text, flags=re.IGNORECASE)
            # As a last resort, remove any attribute blocks that only contain when-format="html" to avoid leaving stray attributes
            text = re.sub(r"\{[^}]*when-format\s*=\s*(?:\"|')?html(?:\"|')?[^}]*\}", "", text, flags=re.IGNORECASE)
            return text

        sanitized = _remove_html_only_quarto_blocks(orig_text)
        if sanitized != orig_text:
            import tempfile
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=src.suffix, mode='w', encoding='utf-8')
            tf.write(sanitized)
            tf.close()
            temp_input = tf.name
            pandoc_cmd[1] = str(temp_input)
            print('Created temporary input with HTML-only content removed:', temp_input)
            # If requested, also write a persistent sanitized copy for inspection
            if PERSIST_SANITIZED:
                try:
                    sanitized_dir = outdir / 'sanitized_inputs'
                    sanitized_dir.mkdir(parents=True, exist_ok=True)
                    persistent_sanitized_path = sanitized_dir / (stem + '.sanitized' + src.suffix)
                    Path(temp_input).replace(persistent_sanitized_path)
                    # Use the persistent file as the pandoc input
                    pandoc_cmd[1] = str(persistent_sanitized_path)
                    # Keep temp_input reference for cleanup logic, but mark persistent as kept
                    temp_input = None
                    print('Wrote persistent sanitized input:', persistent_sanitized_path)
                except Exception:
                    # If moving fails, continue using temp file
                    pass
            # Also write a persistent copy for verification (not cleaned automatically)
            try:
                persistent_dir = outdir / 'sanitized_inputs'
                persistent_dir.mkdir(parents=True, exist_ok=True)
                pers_path = persistent_dir / (stem + '.qmd')
                pers_path.write_text(sanitized, encoding='utf-8')
                print('Wrote persistent sanitized copy for verification:', pers_path)
            except Exception:
                pass

        # Normalize authors by creating a temporary QMD copy with an inline
        # YAML author list of strings. This avoids pandoc/metadata-file
        # merging issues that in some environments lead to boolean 'true'.
        if author_name:
            names = [n.strip() for n in re.split(r"\s*,\s*", author_name) if n.strip()]
            if names:
                # Read the current pandoc input content (could be original src or sanitized temp)
                current_input = pandoc_cmd[1]
                try:
                    orig = Path(current_input).read_text(encoding='utf-8')
                except Exception:
                    orig = src.read_text(encoding='utf-8')
                # Build inline YAML author list: author: ["A","B"]
                quoted = ', '.join(f'"{n.replace("\"", "\\\"") }"' for n in names)
                inline = f'author: [{quoted}]\n'
                # Replace the author: block in the frontmatter using a simple heuristic
                lines = orig.splitlines()
                if lines and lines[0].strip().startswith('---'):
                    # find end of frontmatter
                    end = None
                    for i in range(1, len(lines)):
                        if lines[i].strip() == '---':
                            end = i
                            break
                    if end is not None:
                        # rebuild frontmatter but replace any existing author: block
                        fm_lines = lines[1:end]
                        # remove existing author block lines
                        new_fm = []
                        in_author = False
                        for ln in fm_lines:
                            if re.match(r"^\s*author\s*:\s*(?:\[|$)", ln):
                                in_author = True
                                # if inline list, skip this line entirely
                                if '[' in ln:
                                    in_author = False
                                continue
                            if in_author:
                                # end of author block if new top-level key
                                if re.match(r"^\S", ln) and ':' in ln:
                                    in_author = False
                                else:
                                    continue
                            if not in_author:
                                new_fm.append(ln)
                        # insert our inline author at the start of frontmatter
                        new_fm.insert(0, inline.rstrip())
                        new_content = '\n'.join(['---'] + new_fm + ['---'] + lines[end+1:]) + '\n'
                        import tempfile
                        tf = tempfile.NamedTemporaryFile(delete=False, suffix=src.suffix, mode='w', encoding='utf-8')
                        tf.write(new_content)
                        tf.close()
                        temp_name = tf.name
                        # If persistent sanitized file was requested earlier, overwrite that path with normalized content
                        if PERSIST_SANITIZED and persistent_sanitized_path:
                            try:
                                Path(temp_name).replace(persistent_sanitized_path)
                                pandoc_cmd[1] = str(persistent_sanitized_path)
                                print('Updated persistent sanitized input with normalized authors:', persistent_sanitized_path)
                                # ensure cleanup does not delete the persistent file
                                temp_input = None
                            except Exception:
                                # fallback to using temp_name
                                temp_input = temp_name
                                pandoc_cmd[1] = str(temp_input)
                                print('Created temporary input with normalized authors:', temp_input)
                        else:
                            temp_input = temp_name
                            pandoc_cmd[1] = str(temp_input)
                            print('Created temporary input with normalized authors:', temp_input)

        print('Running:', ' '.join(pandoc_cmd))
        p = subprocess.run(pandoc_cmd, cwd=str(Path.cwd()))
    finally:
        # remove temporary metadata file if created
        try:
            if tmp_meta and Path(tmp_meta).exists():
                Path(tmp_meta).unlink()
        except Exception:
            pass
        # remove temporary input if created
        try:
            if temp_input and Path(temp_input).exists():
                Path(temp_input).unlink()
        except Exception:
            pass
    if p.returncode != 0:
        return p
    if p.returncode != 0:
        return p

    # 2) Run TeX engine passes in outdir
    # Before running TeX, post-process the generated .tex to inject affiliations
    try:
        authors_info = extract_authors_with_affiliations(src)
        if authors_info:
            try:
                tex_text = outtex.read_text(encoding='utf-8', errors='ignore')
                m = re.search(r"\\author\{(.+?)\}", tex_text, flags=re.DOTALL)
                if m:
                    # Deduplicate affiliations and emit numeric superscripts.
                    # Build unique affiliation list preserving first-seen order.
                    uniq = []
                    idx_map = {}
                    for a in authors_info:
                        aff = (a.get('affiliation') or '').strip()
                        if aff and aff not in idx_map:
                            idx_map[aff] = len(uniq) + 1
                            uniq.append(aff)

                    parts = []
                    for a in authors_info:
                        name = a.get('name', '').strip()
                        aff = (a.get('affiliation') or '').strip()
                        if aff:
                            i = idx_map.get(aff)
                            parts.append(f"{name}\\textsuperscript{{{i}}}")
                        else:
                            parts.append(name)

                    new_auth = ' \\and '.join(parts)
                    tex_text = tex_text[:m.start()] + "\\author{" + new_auth + "}" + tex_text[m.end():]

                    # Insert affiliation block after \maketitle if we have any affiliations
                    if uniq:
                        aff_lines = [f"\\textsuperscript{{{i}}} {uniq[i-1]}" for i in range(1, len(uniq)+1)]
                        # Build a small centered affiliation block. Use '\\' (LaTeX linebreak)
                        # and real newline characters in the generated .tex.
                        aff_block = "\n" + "\\begin{center}\\footnotesize " + ' \\ '.join(aff_lines) + "\n\\end{center}\n"
                        # Insert the affiliation block immediately after \maketitle (with a real newline)
                        tex_text = tex_text.replace('\\maketitle', '\\maketitle' + '\n' + aff_block)

                    outtex.write_text(tex_text, encoding='utf-8')
                    print('Injected deduplicated author affiliations into', outtex)
            except Exception:
                pass
    except Exception:
        pass

    # We'll run: tex_engine (1) -> bibtex (if needed) -> tex_engine (2) -> tex_engine (3)
    def run_tex(cmd_args):
        print('Running:', ' '.join(cmd_args), ' (cwd=', outdir, ')')
        return subprocess.run(cmd_args, cwd=str(outdir))

    # First pass
    res = run_tex([tex_engine, '-interaction=nonstopmode', outtex.name])
    if res.returncode != 0:
        return res

    # Check if bibliography processing is needed by inspecting .aux
    aux_path = outdir / (stem + '.aux')
    if aux_path.exists():
        try:
            aux_text = aux_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            aux_text = ''
        if '\\bibdata' in aux_text or '\\citation' in aux_text:
            # run bibtex
            bibres = run_tex(['bibtex', stem])
            if bibres.returncode != 0:
                return bibres

    # Second and third passes
    res = run_tex([tex_engine, '-interaction=nonstopmode', outtex.name])
    if res.returncode != 0:
        return res
    res = run_tex([tex_engine, '-interaction=nonstopmode', outtex.name])
    if res.returncode != 0:
        return res

    # At this point outpdf should exist next to outtex
    if not outpdf.exists():
        # Some engines write .pdf in the same dir but different name; attempt to find any pdf with stem
        possible = list(outdir.glob(stem + '*.pdf'))
        if possible:
            print('Found PDF:', possible[0])
            return subprocess.CompletedProcess(args=['tex'], returncode=0)
        print('Error: PDF not produced for', stem, file=sys.stderr)
        return subprocess.CompletedProcess(args=['tex'], returncode=4)

    print('Output created:', outpdf)
    return subprocess.CompletedProcess(args=['tex'], returncode=0)


def main():
    parser = argparse.ArgumentParser(description='Render PDFs for site articles/reports using pandoc + xelatex')
    parser.add_argument('--output-dir', '-o', default='docs/assets/pdfs', help='Directory to write PDFs into (default: docs/assets/pdfs)')
    parser.add_argument('--all', action='store_true', help='Render all .qmd files (excludes docs/assets/site_libs/scripts)')
    parser.add_argument('--dry-run', action='store_true', help='Only list files that would be rendered')
    parser.add_argument('--check-authors', action='store_true', help='Check and report extracted author metadata for all targets')
    parser.add_argument('--persist-sanitized', action='store_true', help='Write persistent sanitized QMD copies to output directory for inspection')
    parser.add_argument('targets', nargs='*', help='Optional list of specific .qmd files to render (paths relative to repo root or absolute)')
    args = parser.parse_args()

    global PERSIST_SANITIZED
    if args.persist_sanitized:
        PERSIST_SANITIZED = True

    # If explicit targets provided on the command line, use those. Paths may be
    # relative to the repository root or absolute. Otherwise discover targets
    # via find_targets(). This allows calling the script with a single file.
    if args.targets:
        targets = []
        missing = []
        for t in args.targets:
            p = Path(t)
            if not p.is_absolute():
                p = ROOT / p
            if not p.exists():
                missing.append(str(t))
                continue
            targets.append(p.resolve())
        if missing:
            print('Error: the following targets were not found:', file=sys.stderr)
            for m in missing:
                print(' -', m, file=sys.stderr)
            # exit with non-zero status to indicate user provided bad paths
            raise SystemExit(2)
    else:
        targets = find_targets(args.all)
    if not targets:
        print('No target QMD files found (try --all).')
        return 0

    print(f'Found {len(targets)} files to render:')
    for p in targets:
        print(' -', p.relative_to(ROOT))

    if args.dry_run:
        print('\nDry-run complete. No PDF rendering performed.')
        return 0

    if args.check_authors:
        outdir = ROOT / args.output_dir
        print('\nChecking authors for all targets:')
        targets = find_targets(args.all)
        any_missing = False
        for src in targets:
            author = extract_author_name_from_frontmatter(src)
            tex_path = outdir / (src.stem + '.tex')
            tex_author = None
            if tex_path.exists():
                try:
                    txt = tex_path.read_text(encoding='utf-8', errors='ignore')
                    m = re.search(r"\\author\{(.+?)\}", txt)
                    if m:
                        tex_author = m.group(1)
                except Exception:
                    tex_author = None
            print(f' - {src.relative_to(ROOT)}')
            print(f'     extracted author: {author!s}')
            print(f'     tex author:       {tex_author!s}')
            if not author or (tex_author and tex_author.strip().lower() == 'true'):
                any_missing = True
        if any_missing:
            print('\nSome files lacked a robust author extraction or have tex author=true; consider inspecting their frontmatter.')
        else:
            print('\nAll targets have sensible author metadata extracted.')
        return 0

    outdir = ROOT / args.output_dir
    outdir.mkdir(parents=True, exist_ok=True)

    failures = []
    for src in targets:
        print(f'\nRendering {src} -> {outdir / (src.stem + ".pdf")}')
        res = run_pandoc_xelatex(src, outdir)
        if res.returncode != 0:
            print('--- Render failed ---', file=sys.stderr)
            print(f'  Return code: {res.returncode}', file=sys.stderr)
            failures.append((src, res))
        else:
            print('Success')

    print('\nSummary:')
    print(f'  Rendered: {len(targets) - len(failures)}')
    print(f'  Failed:   {len(failures)}')
    if failures:
        print('\nFailed files:')
        for src, res in failures:
            print('-', src)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
