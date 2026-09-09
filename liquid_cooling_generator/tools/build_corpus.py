#!/usr/bin/env python3
"""Regenerate the reference corpus from the actual source PDFs.

The corpus is what `verify.py` checks every evidence quote against. The files
shipped in references/corpus/ are PARTIAL EXTRACTS seeded by hand; running this
against the real PDFs replaces them with full text plus a sha256 of the source,
which is what makes evidence verification authoritative rather than indicative.

    pip install pypdf
    python3 tools/build_corpus.py /path/to/pdfs

Each PDF becomes <slug>.txt and an entry in references/corpus/manifest.json
recording the source filename, sha256, page count and extraction timestamp.
"""
import hashlib, json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'references' / 'corpus'


def slug(name):
    sys.path.insert(0,str(ROOT))
    from verify import canonical_document_id
    return canonical_document_id(name)


def main(src_dir):
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit('pip install pypdf')
    OUT.mkdir(parents=True, exist_ok=True)
    existing=OUT/'manifest.json'
    manifest=json.loads(existing.read_text()) if existing.exists() else {}
    for pdf in sorted(Path(src_dir).glob('*.pdf')):
        raw = pdf.read_bytes()
        reader = PdfReader(pdf)
        text = '\n'.join((p.extract_text() or '') for p in reader.pages)
        name = slug(pdf.name) + '.txt'
        (OUT / name).write_text(text, encoding='utf-8')
        manifest[name] = {'source_pdf': pdf.name, 'sha256': hashlib.sha256(raw).hexdigest(),
                          'pages': len(reader.pages), 'characters': len(text),
                          'extracted_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                          'extractor': 'pypdf', 'partial': False}
        print(f'{pdf.name} -> {name} ({len(reader.pages)} pages, {len(text)} chars)')
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'\nwrote {OUT / "manifest.json"} with {len(manifest)} documents')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
