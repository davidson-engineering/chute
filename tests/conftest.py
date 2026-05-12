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
    """Stub pymupdf4llm so pdf→md doesn't require a real PDF."""
    import types

    mod = types.ModuleType("pymupdf4llm")
    mod.to_markdown = lambda path: f"# stub markdown for {path}\n"
    monkeypatch.setitem(__import__("sys").modules, "pymupdf4llm", mod)
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
