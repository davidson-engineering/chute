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


# ---- packaging sanity -----------------------------------------------------


def test_default_stylesheet_resource_exists():
    p = cli.default_stylesheet()
    assert p.exists()
    assert p.read_text().strip(), "default.css should not be empty"


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "chute" in capsys.readouterr().out
