"""Integration tests — exercise the real pandoc/weasyprint toolchain.

Skipped automatically if the underlying tools aren't installed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from chute import cli
from .conftest import needs_ocrmypdf, needs_pandoc, needs_weasyprint


SAMPLE_MD = """# Hello

This is **chute** integration test content with a [link](https://example.com).

- one
- two
- three

```python
print("code block")
```
"""


@pytest.fixture
def sample_md(tmp_path: Path) -> Path:
    p = tmp_path / "sample.md"
    p.write_text(SAMPLE_MD)
    return p


@needs_pandoc
def test_md_to_docx_real(sample_md, tmp_path):
    dst = tmp_path / "out.docx"
    rc = cli.main([str(sample_md), "-o", str(dst)])
    assert rc == 0
    assert dst.exists() and dst.stat().st_size > 0
    # docx files are zip archives — first bytes are "PK"
    assert dst.read_bytes()[:2] == b"PK"


@needs_pandoc
def test_md_to_html_real(sample_md, tmp_path):
    dst = tmp_path / "out.html"
    rc = cli.main([str(sample_md), "-o", str(dst)])
    assert rc == 0
    html = dst.read_text()
    assert "<h1" in html and "Hello" in html


@needs_pandoc
@needs_weasyprint
def test_md_to_pdf_real(sample_md, tmp_path):
    dst = tmp_path / "out.pdf"
    rc = cli.main([str(sample_md), "-o", str(dst)])
    assert rc == 0
    assert dst.read_bytes().startswith(b"%PDF")


@needs_pandoc
@needs_weasyprint
def test_md_to_pdf_no_style_real(sample_md, tmp_path):
    dst = tmp_path / "plain.pdf"
    rc = cli.main([str(sample_md), "-o", str(dst), "--no-style"])
    assert rc == 0
    assert dst.read_bytes().startswith(b"%PDF")


@needs_weasyprint
@needs_ocrmypdf
def test_pdf_to_md_ocr_real(sample_md, tmp_path):
    # Render a PDF, then round-trip it back to markdown through OCR.
    pdf = tmp_path / "rendered.pdf"
    assert cli.main([str(sample_md), "-o", str(pdf)]) == 0
    dst = tmp_path / "ocr.md"
    rc = cli.main([str(pdf), "-o", str(dst), "--ocr"])
    assert rc == 0
    assert "Hello" in dst.read_text()


@needs_weasyprint
@needs_ocrmypdf
def test_pdf_to_md_ocr_stdout_is_only_markdown(sample_md, tmp_path):
    # pymupdf4llm's progress chatter must go to stderr, not into `-o -` output.
    # Run a real process: in-process, pymupdf binds whatever sys.stdout pytest
    # had installed when it was first imported.
    pdf = tmp_path / "rendered.pdf"
    assert cli.main([str(sample_md), "-o", str(pdf)]) == 0
    proc = subprocess.run(
        [sys.executable, "-m", "chute.cli", str(pdf), "-t", "md", "--ocr", "-o", "-"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Hello" in proc.stdout
    assert "Document parser messages" not in proc.stdout
    assert "OCR on page" not in proc.stdout


@needs_pandoc
def test_batch_recursive_real(tmp_path):
    src = tmp_path / "docs"
    (src / "sub").mkdir(parents=True)
    (src / "a.md").write_text("# A")
    (src / "sub" / "b.md").write_text("# B")
    out = tmp_path / "out"
    rc = cli.main([str(src), "-t", "html", "-r", "-o", str(out)])
    assert rc == 0
    assert (out / "a.html").exists()
    assert (out / "sub" / "b.html").exists()
