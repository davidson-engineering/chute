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
from pathlib import Path
from typing import Callable

from chute import __version__

PDF_ENGINE = os.environ.get("CHUTE_PDF_ENGINE", "weasyprint")

SUPPORTED_INPUTS = {"docx", "pdf", "md"}
SUPPORTED_OUTPUTS = {"md", "pdf", "docx", "html"}

STYLED_OUTPUTS = {"pdf", "html"}


def fail(msg: str) -> None:
    sys.exit(f"chute: {msg}")


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
        return list(user_css or [])
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
    print(f"[pandoc] {src} → {dst}")
    _pandoc([str(src), "-o", str(dst)])


def docx_to_pdf(src: Path, dst: Path, css: list[Path]) -> None:
    require_tool(PDF_ENGINE)
    print(f"[pandoc+{PDF_ENGINE}] {src} → {dst}")
    _pandoc([
        str(src),
        f"--pdf-engine={PDF_ENGINE}",
        "--standalone",
        *_pandoc_css_args(css),
        "-o", str(dst),
    ])


def docx_to_html(src: Path, dst: Path, css: list[Path]) -> None:
    print(f"[pandoc] {src} → {dst}")
    _pandoc([
        str(src),
        "--standalone",
        "--embed-resources",
        *_pandoc_css_args(css),
        "-o", str(dst),
    ])


def pdf_to_md(src: Path, dst: Path, _css: list[Path]) -> None:
    import pymupdf4llm

    print(f"[pymupdf4llm] {src} → {dst}")
    dst.write_text(pymupdf4llm.to_markdown(str(src)))


def md_to_pdf(src: Path, dst: Path, css: list[Path]) -> None:
    require_tool(PDF_ENGINE)
    print(f"[pandoc+{PDF_ENGINE}] {src} → {dst}")
    _pandoc([
        str(src),
        f"--pdf-engine={PDF_ENGINE}",
        "--standalone",
        *_pandoc_css_args(css),
        "-o", str(dst),
    ])


def md_to_docx(src: Path, dst: Path, _css: list[Path]) -> None:
    print(f"[pandoc] {src} → {dst}")
    _pandoc([str(src), "-o", str(dst)])


def md_to_html(src: Path, dst: Path, css: list[Path]) -> None:
    print(f"[pandoc] {src} → {dst}")
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


def normalize_ext(value: str) -> str:
    return value.lower().lstrip(".")


def convert_one(src: Path, dst: Path, css: list[Path]) -> bool:
    in_ext = normalize_ext(src.suffix)
    out_ext = normalize_ext(dst.suffix)
    route = ROUTES.get((in_ext, out_ext))
    if route is None:
        print(
            f"chute: skipping {src} — no route from .{in_ext} to .{out_ext}",
            file=sys.stderr,
        )
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    effective_css = css if out_ext in STYLED_OUTPUTS else []
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
            "  md   → pdf, docx, html\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", type=Path, help="input file or directory")
    p.add_argument(
        "-o", "--output", type=Path,
        help="output file (with extension) or directory",
    )
    p.add_argument(
        "-t", "--to", dest="to_format",
        help="target format (md, pdf, docx, html). Required if -o is a directory.",
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
        "-V", "--version", action="version", version=f"chute {__version__}",
    )
    return p.parse_args(argv)


def resolve_target(out: Path | None, to_format: str | None, src_stem: str) -> Path:
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    inp: Path = args.input

    if not inp.exists():
        fail(f"input not found: {inp}")

    css = resolved_css(args.css, args.no_style)

    if inp.is_file():
        dst = resolve_target(args.output, args.to_format, inp.stem)
        return 0 if convert_one(inp, dst, css) else 1

    if inp.is_dir():
        if args.to_format is None:
            fail("directory input requires -t <format>")
        out_ext = normalize_ext(args.to_format)
        if out_ext not in SUPPORTED_OUTPUTS:
            fail(f"unsupported target format: {args.to_format}")
        out_dir = args.output or Path("./out")
        pattern = "**/*" if args.recursive else "*"
        found = False
        ok = True
        for f in sorted(inp.glob(pattern)):
            if not f.is_file():
                continue
            in_ext = normalize_ext(f.suffix)
            if in_ext not in SUPPORTED_INPUTS or (in_ext, out_ext) not in ROUTES:
                continue
            found = True
            rel_dir = f.parent.relative_to(inp)
            target_dir = out_dir if str(rel_dir) == "." else out_dir / rel_dir
            dst = target_dir / f"{f.stem}.{out_ext}"
            if not convert_one(f, dst, css):
                ok = False
        if not found:
            fail(f"no convertible files (→ .{out_ext}) found in {inp}")
        return 0 if ok else 1

    fail(f"input must be a file or directory: {inp}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
