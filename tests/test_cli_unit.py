"""Unit tests for the CLI logic — pandoc and pymupdf4llm are stubbed."""
from __future__ import annotations

from pathlib import Path

import pytest

from chute import cli


# ---- helpers --------------------------------------------------------------


def _last_pandoc_args(calls: list[list[str]]) -> list[str]:
    assert calls, "expected at least one pandoc invocation"
    cmd = calls[-1]
    assert cmd[0] == "pandoc"
    return cmd[1:]


# ---- pure helpers ---------------------------------------------------------


class TestNormalizeExt:
    @pytest.mark.parametrize("raw,expected", [
        (".PDF", "pdf"),
        ("MD", "md"),
        (".docx", "docx"),
        ("html", "html"),
    ])
    def test_normalize(self, raw, expected):
        assert cli.normalize_ext(raw) == expected


class TestResolveTarget:
    def test_explicit_output_with_extension_wins(self, tmp_path):
        out = tmp_path / "explicit.pdf"
        result = cli.resolve_target(out, "html", "doc")
        assert result == out  # extension on -o overrides -t

    def test_to_format_only_uses_cwd(self):
        result = cli.resolve_target(None, "pdf", "report")
        assert result == Path("report.pdf")

    def test_output_dir_plus_to_format(self, tmp_path):
        result = cli.resolve_target(tmp_path, "html", "report")
        assert result == tmp_path / "report.html"

    def test_missing_both_exits(self):
        with pytest.raises(SystemExit) as exc:
            cli.resolve_target(None, None, "doc")
        assert "specify either" in str(exc.value)

    def test_unsupported_format_exits(self):
        with pytest.raises(SystemExit) as exc:
            cli.resolve_target(None, "rtf", "doc")
        assert "unsupported" in str(exc.value)


class TestResolvedCss:
    def test_default_when_nothing_provided(self):
        css = cli.resolved_css(None, no_style=False)
        assert len(css) == 1
        assert css[0].name == "default.css"

    def test_no_style_drops_default(self):
        assert cli.resolved_css(None, no_style=True) == []

    def test_user_css_replaces_default(self, tmp_path):
        user = tmp_path / "user.css"
        user.write_text("body{}")
        assert cli.resolved_css([user], no_style=False) == [user]

    def test_no_style_overrides_user_css(self, tmp_path):
        user = tmp_path / "user.css"
        user.write_text("body{}")
        assert cli.resolved_css([user], no_style=True) == []


# ---- single-file routing --------------------------------------------------


class TestConvertOne:
    def test_unknown_route_returns_false(self, tmp_path, capsys):
        src = tmp_path / "x.pdf"
        src.write_bytes(b"")
        dst = tmp_path / "x.docx"  # not a supported route
        assert cli.convert_one(src, dst, []) is False
        err = capsys.readouterr().err
        assert "no route" in err

    def test_creates_parent_dirs(self, tmp_path, fake_pandoc):
        src = tmp_path / "a.md"
        src.write_text("# hi")
        dst = tmp_path / "nested" / "deep" / "a.html"
        assert cli.convert_one(src, dst, []) is True
        assert dst.exists()

    def test_strips_css_for_unstyled_targets(self, tmp_path, fake_pandoc):
        """md→docx is not in STYLED_OUTPUTS — css must not be passed to pandoc."""
        src = tmp_path / "a.md"
        src.write_text("# hi")
        dst = tmp_path / "a.docx"
        fake_css = tmp_path / "style.css"
        fake_css.write_text("body{}")
        cli.convert_one(src, dst, [fake_css])
        args = _last_pandoc_args(fake_pandoc)
        assert "--css" not in args

    def test_passes_css_for_styled_targets(self, tmp_path, fake_pandoc):
        src = tmp_path / "a.md"
        src.write_text("# hi")
        dst = tmp_path / "a.pdf"
        css = tmp_path / "style.css"
        css.write_text("body{}")
        cli.convert_one(src, dst, [css])
        args = _last_pandoc_args(fake_pandoc)
        assert "--css" in args
        assert str(css) in args


# ---- end-to-end main() with fakes -----------------------------------------


class TestMainSingleFile:
    def test_md_to_pdf_explicit_output(self, tmp_path, fake_pandoc, monkeypatch):
        src = tmp_path / "doc.md"
        src.write_text("# hi")
        dst = tmp_path / "doc.pdf"
        rc = cli.main([str(src), "-o", str(dst)])
        assert rc == 0
        assert dst.exists()
        args = _last_pandoc_args(fake_pandoc)
        assert "--pdf-engine=weasyprint" in args
        # default stylesheet is applied
        assert any(a.endswith("default.css") for a in args)

    def test_to_flag_implicit_path(self, tmp_path, fake_pandoc, monkeypatch):
        src = tmp_path / "doc.md"
        src.write_text("# hi")
        monkeypatch.chdir(tmp_path)
        rc = cli.main([str(src), "-t", "html"])
        assert rc == 0
        assert (tmp_path / "doc.html").exists()

    def test_no_style_omits_default(self, tmp_path, fake_pandoc):
        src = tmp_path / "doc.md"
        src.write_text("# hi")
        rc = cli.main([str(src), "-o", str(tmp_path / "doc.pdf"), "--no-style"])
        assert rc == 0
        args = _last_pandoc_args(fake_pandoc)
        assert "--css" not in args

    def test_custom_css_replaces_default(self, tmp_path, fake_pandoc):
        src = tmp_path / "doc.md"
        src.write_text("# hi")
        css1 = tmp_path / "a.css"
        css2 = tmp_path / "b.css"
        css1.write_text("")
        css2.write_text("")
        rc = cli.main([
            str(src), "-o", str(tmp_path / "doc.pdf"),
            "--css", str(css1), "--css", str(css2),
        ])
        assert rc == 0
        args = _last_pandoc_args(fake_pandoc)
        assert str(css1) in args and str(css2) in args
        assert not any(a.endswith("default.css") for a in args)

    def test_pdf_to_md_uses_pymupdf(self, tmp_path, fake_pymupdf):
        src = tmp_path / "p.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        dst = tmp_path / "p.md"
        rc = cli.main([str(src), "-o", str(dst)])
        assert rc == 0
        assert dst.read_text().startswith("# stub markdown")

    def test_pdf_to_md_ocr_runs_ocrmypdf(self, tmp_path, fake_pandoc, fake_pymupdf):
        src = tmp_path / "scan.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        dst = tmp_path / "scan.md"
        rc = cli.main([str(src), "-o", str(dst), "--ocr"])
        assert rc == 0
        assert dst.read_text().startswith("# stub markdown")
        ocr_calls = [c for c in fake_pandoc if c and c[0] == "ocrmypdf"]
        assert len(ocr_calls) == 1
        assert "--force-ocr" in ocr_calls[0]
        assert ocr_calls[0][1] == "--force-ocr"

    def test_ocr_ignored_for_non_pdf_route(self, tmp_path, fake_pandoc):
        """--ocr is a no-op for routes other than pdf→md; no ocrmypdf call."""
        src = tmp_path / "note.md"
        src.write_text("# hi")
        dst = tmp_path / "note.html"
        rc = cli.main([str(src), "-o", str(dst), "--ocr"])
        assert rc == 0
        assert not any(c and c[0] == "ocrmypdf" for c in fake_pandoc)

    def test_env_var_overrides_pdf_engine(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHUTE_PDF_ENGINE", "wkhtmltopdf")
        # PDF_ENGINE is captured at import time — reimport to pick it up.
        import importlib
        from chute import cli as cli_mod
        importlib.reload(cli_mod)
        try:
            calls: list[list[str]] = []

            def fake_run(cmd, check=False, **kwargs):
                calls.append(list(cmd))
                if "-o" in cmd:
                    Path(cmd[cmd.index("-o") + 1]).write_bytes(b"")
                import subprocess as _sp
                return _sp.CompletedProcess(cmd, 0)

            monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
            monkeypatch.setattr(cli_mod.shutil, "which", lambda n: f"/usr/bin/{n}")

            src = tmp_path / "doc.md"
            src.write_text("# hi")
            rc = cli_mod.main([str(src), "-o", str(tmp_path / "doc.pdf")])
            assert rc == 0
            assert "--pdf-engine=wkhtmltopdf" in calls[-1]
        finally:
            monkeypatch.delenv("CHUTE_PDF_ENGINE", raising=False)
            importlib.reload(cli_mod)

    def test_unknown_route_returns_1(self, tmp_path):
        src = tmp_path / "p.pdf"
        src.write_bytes(b"")
        rc = cli.main([str(src), "-o", str(tmp_path / "p.docx")])
        assert rc == 1

    def test_missing_input_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            cli.main([str(tmp_path / "nope.md"), "-t", "pdf"])
        assert "not found" in str(exc.value)


class TestMainBatch:
    def test_directory_requires_to_flag(self, sample_files):
        with pytest.raises(SystemExit) as exc:
            cli.main([str(sample_files)])
        assert "requires -t" in str(exc.value)

    def test_non_recursive_skips_subdir(self, sample_files, fake_pandoc, tmp_path):
        out = tmp_path / "out"
        rc = cli.main([str(sample_files), "-t", "html", "-o", str(out)])
        assert rc == 0
        # top-level md and docx converted, sub/nested.md NOT touched
        assert (out / "b.html").exists()
        assert (out / "a.html").exists()
        assert not (out / "sub").exists()

    def test_recursive_mirrors_tree(self, sample_files, fake_pandoc, tmp_path):
        out = tmp_path / "out"
        rc = cli.main([str(sample_files), "-t", "html", "-r", "-o", str(out)])
        assert rc == 0
        assert (out / "b.html").exists()
        assert (out / "sub" / "nested.html").exists()

    def test_skips_unconvertible_routes(self, sample_files, fake_pandoc, tmp_path):
        """pdf→html has no route; c.pdf must be skipped silently in batch."""
        out = tmp_path / "out"
        rc = cli.main([str(sample_files), "-t", "html", "-o", str(out)])
        assert rc == 0
        assert not (out / "c.html").exists()

    def test_no_matches_exits(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        (empty / "x.txt").write_text("nope")
        with pytest.raises(SystemExit) as exc:
            cli.main([str(empty), "-t", "pdf"])
        assert "no convertible files" in str(exc.value)


# ---- new flags: -f/--from, -v, -q, stdin/stdout ---------------------------


class TestFromFlag:
    def test_from_overrides_extension(self, tmp_path, fake_pandoc):
        """A .txt file processed with -f md should follow the md→html route."""
        src = tmp_path / "doc.txt"
        src.write_text("# hi")
        dst = tmp_path / "doc.html"
        rc = cli.main([str(src), "-o", str(dst), "-f", "md"])
        assert rc == 0
        # the pandoc invocation should have happened (md→html route)
        assert fake_pandoc, "expected pandoc to be invoked"

    def test_from_unsupported_exits(self, tmp_path):
        src = tmp_path / "doc.md"
        src.write_text("# hi")
        with pytest.raises(SystemExit) as exc:
            cli.main([str(src), "-o", str(tmp_path / "doc.html"), "-f", "rtf"])
        assert "unsupported source format" in str(exc.value)

    def test_from_filters_batch(self, sample_files, fake_pandoc, tmp_path):
        """-f md in a batch should only convert .md files, skipping docx."""
        out = tmp_path / "out"
        rc = cli.main([str(sample_files), "-t", "html", "-f", "md", "-o", str(out)])
        assert rc == 0
        assert (out / "b.html").exists()           # b.md picked up
        assert not (out / "a.html").exists()       # a.docx filtered out


class TestVerbosity:
    def test_default_is_silent_on_stdout(self, tmp_path, fake_pandoc, capsys):
        src = tmp_path / "doc.md"
        src.write_text("# hi")
        rc = cli.main([str(src), "-o", str(tmp_path / "doc.pdf")])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_verbose_prints_progress_to_stderr(self, tmp_path, fake_pandoc, capsys):
        src = tmp_path / "doc.md"
        src.write_text("# hi")
        dst = tmp_path / "doc.pdf"
        rc = cli.main([str(src), "-o", str(dst), "-v"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "[pandoc+weasyprint]" in captured.err
        assert "→" in captured.err

    def test_skip_warning_to_stderr_by_default(self, tmp_path, capsys):
        src = tmp_path / "x.pdf"
        src.write_bytes(b"")
        dst = tmp_path / "x.docx"
        rc = cli.main([str(src), "-o", str(dst)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "no route" in err

    def test_quiet_suppresses_skip_warning(self, tmp_path, capsys):
        src = tmp_path / "x.pdf"
        src.write_bytes(b"")
        dst = tmp_path / "x.docx"
        rc = cli.main([str(src), "-o", str(dst), "-q"])
        assert rc == 1
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_quiet_does_not_suppress_fatal(self, tmp_path):
        """fail() bypasses -q — exit message must still appear."""
        with pytest.raises(SystemExit) as exc:
            cli.main([str(tmp_path / "missing.md"), "-t", "pdf", "-q"])
        assert "not found" in str(exc.value)


class TestStdin:
    def test_stdin_requires_from(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", _stdin_with(b"# hi"))
        with pytest.raises(SystemExit) as exc:
            cli.main(["-", "-o", "out.html"])
        assert "requires -f" in str(exc.value)

    def test_stdin_md_to_html(self, tmp_path, fake_pandoc, monkeypatch):
        dst = tmp_path / "out.html"
        monkeypatch.setattr("sys.stdin", _stdin_with(b"# hi"))
        rc = cli.main(["-", "-f", "md", "-o", str(dst)])
        assert rc == 0
        assert dst.exists()
        # pandoc was called with a temp file (not literally "-")
        args = _last_pandoc_args(fake_pandoc)
        assert any(a.endswith(".md") for a in args)

    def test_stdin_unsupported_format(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", _stdin_with(b"x"))
        with pytest.raises(SystemExit) as exc:
            cli.main(["-", "-f", "rtf", "-o", "out.html"])
        assert "unsupported source format" in str(exc.value)


class TestStdout:
    def test_stdout_requires_to(self, tmp_path):
        src = tmp_path / "doc.md"
        src.write_text("# hi")
        with pytest.raises(SystemExit) as exc:
            cli.main([str(src), "-o", "-"])
        assert "requires -t" in str(exc.value)

    def test_stdout_emits_bytes(self, tmp_path, fake_pandoc, capsysbinary):
        src = tmp_path / "doc.md"
        src.write_text("# hi")
        rc = cli.main([str(src), "-o", "-", "-t", "html"])
        assert rc == 0
        captured = capsysbinary.readouterr()
        # fake_pandoc writes b"stub" to the output path; we should see that on stdout
        assert captured.out == b"stub"

    def test_directory_input_rejects_stdout(self, sample_files):
        with pytest.raises(SystemExit) as exc:
            cli.main([str(sample_files), "-t", "html", "-o", "-"])
        assert "incompatible with a directory input" in str(exc.value)


# ---- packaging sanity -----------------------------------------------------


def _stdin_with(data: bytes):
    """Build a minimal stdin replacement whose .buffer yields `data`."""
    import io
    import types

    buf = io.BytesIO(data)
    stub = types.SimpleNamespace(buffer=buf)
    return stub


def test_default_stylesheet_resource_exists():
    p = cli.default_stylesheet()
    assert p.exists()
    assert p.read_text().strip(), "default.css should not be empty"


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "chute" in capsys.readouterr().out
