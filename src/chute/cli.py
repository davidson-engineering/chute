"""chute — document pipeline.

Routes documents to the right converter for each (input, output) format pair.

Inputs:  docx, pdf, md
Outputs: md, pdf, docx, html
"""
from __future__ import annotations

import argparse
import importlib.resources
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

from chute import __version__

PDF_ENGINE = os.environ.get("CHUTE_PDF_ENGINE", "weasyprint")

SUPPORTED_INPUTS = {"docx", "pdf", "md"}
SUPPORTED_OUTPUTS = {"md", "pdf", "docx", "html"}

STYLED_OUTPUTS = {"pdf", "html"}

STDIO = "-"


def fail(msg: str) -> None:
    sys.exit(f"chute: {msg}")


def warn(msg: str, *, quiet: bool = False) -> None:
    if not quiet:
        print(f"chute: {msg}", file=sys.stderr)


def info(msg: str, *, verbose: bool = False) -> None:
    if verbose:
        print(msg, file=sys.stderr)


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        fail(f"'{name}' not found on PATH")


def default_stylesheet() -> Path:
    with importlib.resources.as_file(
        importlib.resources.files("chute.styles").joinpath("default.css")
    ) as p:
        return Path(p)


def resolved_css(user_css: list[Path] | None, no_style: bool) -> list[Path]:
    if no_style:
        return []
    if user_css:
        return list(user_css)
    return [default_stylesheet()]


Converter = Callable[[Path, Path, list[Path]], None]


def _pandoc(args: list[str]) -> None:
    require_tool("pandoc")
    subprocess.run(["pandoc", *args], check=True)


def _pandoc_css_args(css_files: list[Path]) -> list[str]:
    args: list[str] = []
    for c in css_files:
        args += ["--css", str(c)]
    return args


def docx_to_md(src: Path, dst: Path, _css: list[Path]) -> None:
    _pandoc([str(src), "-o", str(dst)])


def docx_to_pdf(src: Path, dst: Path, css: list[Path]) -> None:
    require_tool(PDF_ENGINE)
    _pandoc([
        str(src),
        f"--pdf-engine={PDF_ENGINE}",
        "--standalone",
        *_pandoc_css_args(css),
        "-o", str(dst),
    ])


def docx_to_html(src: Path, dst: Path, css: list[Path]) -> None:
    _pandoc([
        str(src),
        "--standalone",
        "--embed-resources",
        *_pandoc_css_args(css),
        "-o", str(dst),
    ])


def pdf_to_md(src: Path, dst: Path, _css: list[Path]) -> None:
    import pymupdf4llm

    dst.write_text(pymupdf4llm.to_markdown(str(src)))


def pdf_to_md_ocr(src: Path, dst: Path, _css: list[Path]) -> None:
    """OCR a (scanned/image-only) PDF, then extract markdown.

    ocrmypdf lays down a Tesseract text layer; pymupdf4llm reads it back the
    same way it reads a born-digital PDF.
    """
    import pymupdf4llm

    require_tool("ocrmypdf")
    ocr_pdf = _stdout_target("pdf")  # scratch PDF with a fresh text layer
    try:
        subprocess.run(
            ["ocrmypdf", "--force-ocr", str(src), str(ocr_pdf)],
            check=True,
        )
        dst.write_text(pymupdf4llm.to_markdown(str(ocr_pdf)))
    finally:
        _unlink_quietly(ocr_pdf)


def md_to_pdf(src: Path, dst: Path, css: list[Path]) -> None:
    require_tool(PDF_ENGINE)
    _pandoc([
        str(src),
        f"--pdf-engine={PDF_ENGINE}",
        "--standalone",
        *_pandoc_css_args(css),
        "-o", str(dst),
    ])


def md_to_docx(src: Path, dst: Path, _css: list[Path]) -> None:
    _pandoc([str(src), "-o", str(dst)])


def md_to_html(src: Path, dst: Path, css: list[Path]) -> None:
    _pandoc([
        str(src),
        "--standalone",
        "--embed-resources",
        *_pandoc_css_args(css),
        "-o", str(dst),
    ])


ROUTES: dict[tuple[str, str], Converter] = {
    ("docx", "md"):   docx_to_md,
    ("docx", "pdf"):  docx_to_pdf,
    ("docx", "html"): docx_to_html,
    ("pdf",  "md"):   pdf_to_md,
    ("md",   "pdf"):  md_to_pdf,
    ("md",   "docx"): md_to_docx,
    ("md",   "html"): md_to_html,
}


def route_tag(in_ext: str, out_ext: str, *, ocr: bool = False) -> str:
    if (in_ext, out_ext) == ("pdf", "md"):
        return "ocrmypdf+pymupdf4llm" if ocr else "pymupdf4llm"
    if out_ext == "pdf":
        return f"pandoc+{PDF_ENGINE}"
    return "pandoc"


def normalize_ext(value: str) -> str:
    return value.lower().lstrip(".")


def convert_one(
    src: Path,
    dst: Path,
    css: list[Path],
    *,
    in_ext: str | None = None,
    out_ext: str | None = None,
    src_display: str | None = None,
    dst_display: str | None = None,
    ocr: bool = False,
    verbose: bool = False,
    quiet: bool = False,
) -> bool:
    in_ext = in_ext or normalize_ext(src.suffix)
    out_ext = out_ext or normalize_ext(dst.suffix)
    route = ROUTES.get((in_ext, out_ext))
    src_label = src_display or str(src)
    dst_label = dst_display or str(dst)
    if route is None:
        warn(
            f"skipping {src_label} — no route from .{in_ext} to .{out_ext}",
            quiet=quiet,
        )
        return False
    # --ocr only reshapes the pdf→md route; it is a no-op for anything else.
    ocr = ocr and (in_ext, out_ext) == ("pdf", "md")
    if ocr:
        route = pdf_to_md_ocr
    dst.parent.mkdir(parents=True, exist_ok=True)
    effective_css = css if out_ext in STYLED_OUTPUTS else []
    info(
        f"[{route_tag(in_ext, out_ext, ocr=ocr)}] {src_label} → {dst_label}",
        verbose=verbose,
    )
    route(src, dst, effective_css)
    return True


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="chute",
        description=(
            "Convert between document formats with a curated tool stack.\n\n"
            "Supported routes:\n"
            "  docx → md, pdf, html\n"
            "  pdf  → md\n"
            "  md   → pdf, docx, html\n\n"
            "Use '-' as input or output for stdin/stdout.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", type=str, help="input file, directory, or '-' for stdin")
    p.add_argument(
        "-o", "--output", type=str, default=None,
        help="output file (with extension), directory, or '-' for stdout",
    )
    p.add_argument(
        "-f", "--from", dest="from_format",
        help=(
            "source format (md, docx, pdf). Overrides the input file's extension; "
            "required when reading from stdin."
        ),
    )
    p.add_argument(
        "-t", "--to", dest="to_format",
        help=(
            "target format (md, pdf, docx, html). Required when -o is a directory "
            "or when writing to stdout."
        ),
    )
    p.add_argument(
        "-r", "--recursive", action="store_true",
        help="recurse into subdirectories",
    )
    p.add_argument(
        "--css", action="append", type=Path, default=None, metavar="FILE",
        help="stylesheet to apply (repeatable). Replaces the default stylesheet.",
    )
    p.add_argument(
        "--no-style", action="store_true",
        help="disable the default stylesheet (and any --css)",
    )
    p.add_argument(
        "--ocr", action="store_true",
        help=(
            "OCR the source before extracting text (pdf → md only). Use for "
            "scanned or image-only PDFs; requires 'ocrmypdf'."
        ),
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="print per-file progress to stderr",
    )
    p.add_argument(
        "-q", "--quiet", action="store_true",
        help="suppress skip warnings (errors still print)",
    )
    p.add_argument(
        "-V", "--version", action="version", version=f"chute {__version__}",
    )
    return p.parse_args(argv)


def resolve_target(
    out: Path | None, to_format: str | None, src_stem: str
) -> Path:
    if out is not None and out.suffix:
        return out
    if to_format is None:
        fail("specify either -o <file.ext> or -t <format>")
    ext = normalize_ext(to_format)
    if ext not in SUPPORTED_OUTPUTS:
        fail(f"unsupported target format: {to_format}")
    if out is None:
        return Path(f"{src_stem}.{ext}")
    return out / f"{src_stem}.{ext}"


def _stage_stdin(in_fmt: str) -> Path:
    """Write stdin to a temp file with the right extension; return its path."""
    tmp = tempfile.NamedTemporaryFile(suffix=f".{in_fmt}", delete=False)
    try:
        shutil.copyfileobj(sys.stdin.buffer, tmp)
    finally:
        tmp.close()
    return Path(tmp.name)


def _stdout_target(out_fmt: str) -> Path:
    """Allocate a temp file for an output that will be dumped to stdout."""
    tmp = tempfile.NamedTemporaryFile(suffix=f".{out_fmt}", delete=False)
    tmp.close()
    return Path(tmp.name)


def _emit_stdout(path: Path) -> None:
    sys.stdout.buffer.write(path.read_bytes())


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raw_input = args.input
    raw_output = args.output

    using_stdin = raw_input == STDIO
    using_stdout = raw_output == STDIO

    css = resolved_css(args.css, args.no_style)
    ocr = args.ocr
    verbose = args.verbose
    quiet = args.quiet

    # ---- single-file path (real file OR stdin) ----------------------------
    if using_stdin or Path(raw_input).is_file():
        return _convert_single(
            raw_input=raw_input,
            raw_output=raw_output,
            from_format=args.from_format,
            to_format=args.to_format,
            using_stdin=using_stdin,
            using_stdout=using_stdout,
            css=css,
            ocr=ocr,
            verbose=verbose,
            quiet=quiet,
        )

    # ---- everything else is a directory or missing ------------------------
    inp = Path(raw_input)
    if not inp.exists():
        fail(f"input not found: {inp}")

    if inp.is_dir():
        if using_stdout:
            fail("'-o -' (stdout) is incompatible with a directory input")
        return _convert_batch(
            inp=inp,
            out=Path(raw_output) if raw_output else None,
            from_format=args.from_format,
            to_format=args.to_format,
            recursive=args.recursive,
            css=css,
            ocr=ocr,
            verbose=verbose,
            quiet=quiet,
        )

    fail(f"input must be a file or directory: {inp}")
    return 1


def _convert_single(
    *,
    raw_input: str,
    raw_output: str | None,
    from_format: str | None,
    to_format: str | None,
    using_stdin: bool,
    using_stdout: bool,
    css: list[Path],
    ocr: bool,
    verbose: bool,
    quiet: bool,
) -> int:
    # Resolve source path + format + display label.
    src_display: str | None = None
    cleanup_src: Path | None = None

    if using_stdin:
        if from_format is None:
            fail("input '-' requires -f/--from")
        in_ext = normalize_ext(from_format)
        if in_ext not in SUPPORTED_INPUTS:
            fail(f"unsupported source format: {from_format}")
        src = _stage_stdin(in_ext)
        cleanup_src = src
        src_display = "<stdin>"
        src_stem = "stdin"
    else:
        src = Path(raw_input)
        if from_format is not None:
            in_ext = normalize_ext(from_format)
            if in_ext not in SUPPORTED_INPUTS:
                fail(f"unsupported source format: {from_format}")
        else:
            in_ext = normalize_ext(src.suffix)
        src_stem = src.stem

    try:
        # Resolve destination path + format + display label.
        dst_display: str | None = None
        cleanup_dst: Path | None = None

        if using_stdout:
            if to_format is None:
                fail("output '-' requires -t/--to")
            out_ext = normalize_ext(to_format)
            if out_ext not in SUPPORTED_OUTPUTS:
                fail(f"unsupported target format: {to_format}")
            dst = _stdout_target(out_ext)
            cleanup_dst = dst
            dst_display = "<stdout>"
        else:
            out = Path(raw_output) if raw_output else None
            dst = resolve_target(out, to_format, src_stem)
            out_ext = normalize_ext(dst.suffix)

        try:
            ok = convert_one(
                src, dst, css,
                in_ext=in_ext, out_ext=out_ext,
                src_display=src_display, dst_display=dst_display,
                ocr=ocr, verbose=verbose, quiet=quiet,
            )
            if ok and using_stdout:
                _emit_stdout(dst)
            return 0 if ok else 1
        finally:
            if cleanup_dst is not None:
                _unlink_quietly(cleanup_dst)
    finally:
        if cleanup_src is not None:
            _unlink_quietly(cleanup_src)


def _convert_batch(
    *,
    inp: Path,
    out: Path | None,
    from_format: str | None,
    to_format: str | None,
    recursive: bool,
    css: list[Path],
    ocr: bool,
    verbose: bool,
    quiet: bool,
) -> int:
    if to_format is None:
        fail("directory input requires -t <format>")
    out_ext = normalize_ext(to_format)
    if out_ext not in SUPPORTED_OUTPUTS:
        fail(f"unsupported target format: {to_format}")

    if from_format is not None:
        forced = normalize_ext(from_format)
        if forced not in SUPPORTED_INPUTS:
            fail(f"unsupported source format: {from_format}")
        allowed_inputs = {forced}
    else:
        allowed_inputs = set(SUPPORTED_INPUTS)

    out_dir = out or Path("./out")
    pattern = "**/*" if recursive else "*"
    found = False
    ok = True
    for f in sorted(inp.glob(pattern)):
        if not f.is_file():
            continue
        in_ext = normalize_ext(f.suffix)
        if in_ext not in allowed_inputs or (in_ext, out_ext) not in ROUTES:
            continue
        found = True
        rel_dir = f.parent.relative_to(inp)
        target_dir = out_dir if str(rel_dir) == "." else out_dir / rel_dir
        dst = target_dir / f"{f.stem}.{out_ext}"
        if not convert_one(
            f, dst, css,
            in_ext=in_ext, out_ext=out_ext,
            ocr=ocr, verbose=verbose, quiet=quiet,
        ):
            ok = False
    if not found:
        fail(f"no convertible files (→ .{out_ext}) found in {inp}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
