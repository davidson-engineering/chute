from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def fake_pandoc(monkeypatch):
    """Capture pandoc invocations and emit a stub output file at -o <path>."""
    calls: list[list[str]] = []

    def fake_run(cmd, check=False, **kwargs):
        calls.append(list(cmd))
        if "-o" in cmd:
            out = Path(cmd[cmd.index("-o") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"stub")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("chute.cli.subprocess.run", fake_run)
    monkeypatch.setattr("chute.cli.shutil.which", lambda name: f"/usr/bin/{name}")
    return calls


@pytest.fixture
def fake_pymupdf(monkeypatch):
    """Stub pymupdf4llm so pdf→md doesn't require a real PDF.

    Models the modern layout parser (`_use_layout=True`) and records each
    to_markdown call's kwargs on `mod.calls` so tests can assert chute
    suppresses the implicit OCR pass.
    """
    import types

    mod = types.ModuleType("pymupdf4llm")
    mod._use_layout = True
    mod.calls = []

    def to_markdown(path, **kwargs):
        mod.calls.append((path, kwargs))
        return f"# stub markdown for {path}\n"

    mod.to_markdown = to_markdown
    monkeypatch.setitem(__import__("sys").modules, "pymupdf4llm", mod)
    return mod


@pytest.fixture
def fake_ollama(monkeypatch):
    """Stub the Llama/Ollama OCR path so pdf→md --ocr-engine llama needs no PDF,
    no pymupdf render, and no Ollama server.

    Rasterizing is faked to two pages; each POST to Ollama is captured on
    `mod.requests` and answered with a per-page markdown stub.
    """
    import io
    import json
    import types
    import urllib.request

    mod = types.SimpleNamespace(requests=[])

    monkeypatch.setattr(
        "chute.cli._iter_pdf_pages",
        lambda path, dpi: iter([(1, 2, b"png-1"), (2, 2, b"png-2")]),
    )

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def fake_urlopen(req, *args, **kwargs):
        payload = json.loads(req.data.decode("utf-8"))
        mod.requests.append((req.full_url, payload))
        page = len(mod.requests)
        body = json.dumps({"response": f"# page {page}\n"}).encode("utf-8")
        return FakeResponse(body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return mod


@pytest.fixture
def sample_files(tmp_path: Path) -> Path:
    """Tree of dummy inputs — content doesn't matter when pandoc is faked."""
    (tmp_path / "a.docx").write_bytes(b"fake docx")
    (tmp_path / "b.md").write_text("# hi")
    (tmp_path / "c.pdf").write_bytes(b"fake pdf")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.md").write_text("# nested")
    (tmp_path / "ignore.txt").write_text("skip me")
    return tmp_path


def has_tool(name: str) -> bool:
    return shutil.which(name) is not None


needs_pandoc = pytest.mark.skipif(not has_tool("pandoc"), reason="pandoc not installed")
needs_weasyprint = pytest.mark.skipif(
    not has_tool("weasyprint"), reason="weasyprint not installed"
)
needs_ocrmypdf = pytest.mark.skipif(
    not has_tool("ocrmypdf"), reason="ocrmypdf not installed"
)
