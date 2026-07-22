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
from typing import Callable, Iterator

from chute import __version__

PDF_ENGINE = os.environ.get("CHUTE_PDF_ENGINE", "weasyprint")

# OCR backends for the pdf→md route (selected with --ocr-engine).
OCR_ENGINES = ("tesseract", "llama")
DEFAULT_OCR_ENGINE = "tesseract"

# Llama (Ollama) OCR knobs. The vision model transcribes rasterized pages;
# host/model are env-tunable so the CLI surface stays small.
OLLAMA_HOST = os.environ.get("CHUTE_OLLAMA_HOST", "http://localhost:11434")
OLLAMA_OCR_MODEL = os.environ.get("CHUTE_OCR_MODEL", "qwen3-vl:8b")
OCR_RENDER_DPI = int(os.environ.get("CHUTE_OCR_DPI", "150"))
# Cap the context window: a single rendered page's image tokens + transcription
# fit comfortably in ~16k. Modern vision models (e.g. qwen3-vl) otherwise
# default to a 256k window, which balloons KV-cache memory and makes per-page
# inference crawl. Override with CHUTE_OCR_NUM_CTX (0 = leave to the server).
OCR_NUM_CTX = int(os.environ.get("CHUTE_OCR_NUM_CTX", "16384"))
# Per-page HTTP timeout (seconds). Vision inference is legitimately slow, so
# this is generous; 0 disables it. Without a bound a wedged model hangs chute
# indefinitely. Override with CHUTE_OCR_TIMEOUT.
OCR_TIMEOUT = int(os.environ.get("CHUTE_OCR_TIMEOUT", "300"))
# Cap generated tokens per page. Vision models frequently fall into repetition
# loops on dense numeric tables (e.g. transaction rows), generating until they
# fill the context — which reads as a "slow"/timed-out page. One page's text
# comfortably fits in a few thousand tokens; this bounds worst-case time and
# truncates runaway loops. Override with CHUTE_OCR_NUM_PREDICT (0 = unbounded).
OCR_NUM_PREDICT = int(os.environ.get("CHUTE_OCR_NUM_PREDICT", "4096"))

SUPPORTED_INPUTS = {"docx", "pdf", "md"}
SUPPORTED_OUTPUTS = {"md", "pdf", "docx", "html"}

STYLED_OUTPUTS = {"pdf", "html"}

STDIO = "-"


class ConversionError(Exception):
    """A converter failed in a way worth reporting per-file.

    Unlike ``fail()`` (which exits), this is caught by ``convert_one`` so a
    batch run reports the bad file and carries on with the rest.
    """


def fail(msg: str) -> None:
    sys.exit(f"chute: {msg}")


def error(msg: str) -> None:
    """Report a non-fatal per-file error (never gated by -q)."""
    print(f"chute: {msg}", file=sys.stderr)


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


def _pdf_markdown(path: Path, *, allow_ocr: bool) -> str:
    """Extract markdown from a PDF via pymupdf4llm.

    `allow_ocr` controls pymupdf4llm's own (layout-parser) OCR pass:

    - False — the default pdf→md route. Newer pymupdf4llm rasterizes and OCRs
      image-heavy pages, silently discarding a page's real text layer when its
      own OCR does worse (e.g. a statement page dominated by a logo). chute
      owns OCR explicitly via --ocr, so suppress the implicit pass and keep the
      native text.
    - True — the --ocr route. The source has just been through ocrmypdf, so
      every page carries a fresh OCR text layer; let pymupdf4llm read it back.

    `use_ocr` only exists on the layout path, so gate on `_use_layout` to stay
    quiet on older, legacy-parser builds.
    """
    import pymupdf4llm

    kwargs = {}
    if not allow_ocr and getattr(pymupdf4llm, "_use_layout", False):
        kwargs["use_ocr"] = False
    return pymupdf4llm.to_markdown(str(path), **kwargs)


def pdf_to_md(src: Path, dst: Path, _css: list[Path]) -> None:
    dst.write_text(_pdf_markdown(src, allow_ocr=False))


def pdf_to_md_ocr(src: Path, dst: Path, _css: list[Path]) -> None:
    """OCR a (scanned/image-only) PDF, then extract markdown.

    ocrmypdf lays down a Tesseract text layer; pymupdf4llm reads it back the
    same way it reads a born-digital PDF.
    """
    require_tool("ocrmypdf")
    ocr_pdf = _stdout_target("pdf")  # scratch PDF with a fresh text layer
    try:
        subprocess.run(
            ["ocrmypdf", "--force-ocr", str(src), str(ocr_pdf)],
            check=True,
        )
        dst.write_text(_pdf_markdown(ocr_pdf, allow_ocr=True))
    finally:
        _unlink_quietly(ocr_pdf)


OCR_PROMPT = (
    "You are an OCR engine. Transcribe ALL text visible in this page image "
    "into clean GitHub-flavored Markdown. Preserve reading order, headings, "
    "lists, and tables. Reproduce the text verbatim — do not translate, "
    "summarize, or add commentary. Output only the Markdown for the page, with "
    "no surrounding code fences."
)


def _iter_pdf_pages(path: Path, dpi: int) -> Iterator[tuple[int, int, bytes]]:
    """Yield (page_number, total_pages, PNG bytes) one page at a time.

    Rendering lazily keeps only one page's image in memory, so a large PDF
    doesn't rasterize entirely up front.
    """
    import pymupdf  # bundled with pymupdf4llm

    with pymupdf.open(str(path)) as doc:
        total = doc.page_count
        for i, page in enumerate(doc, start=1):
            yield i, total, page.get_pixmap(dpi=dpi).tobytes("png")


def _ollama_ocr_page(png: bytes, *, model: str, host: str) -> str:
    """Send one page image to a local Ollama vision model; return its text."""
    import base64
    import http.client
    import json
    import urllib.error
    import urllib.request

    options: dict[str, object] = {"temperature": 0}
    if OCR_NUM_CTX > 0:
        options["num_ctx"] = OCR_NUM_CTX
    if OCR_NUM_PREDICT > 0:
        options["num_predict"] = OCR_NUM_PREDICT
    payload = json.dumps({
        "model": model,
        "prompt": OCR_PROMPT,
        "images": [base64.b64encode(png).decode("ascii")],
        "stream": False,
        "options": options,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    timeout = OCR_TIMEOUT if OCR_TIMEOUT > 0 else None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace").strip()
        try:
            detail = json.loads(detail).get("error", detail)
        except json.JSONDecodeError:
            pass
        raise ConversionError(
            f"Ollama returned HTTP {e.code} for model '{model}': {detail}"
        )
    except TimeoutError:
        # socket.timeout is TimeoutError in 3.10+, and is NOT a URLError.
        raise ConversionError(
            f"Ollama timed out after {OCR_TIMEOUT}s on model '{model}'. Raise "
            f"CHUTE_OCR_TIMEOUT, lower CHUTE_OCR_DPI, or try a smaller model."
        )
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, TimeoutError):
            raise ConversionError(
                f"Ollama timed out after {OCR_TIMEOUT}s on model '{model}'. "
                f"Raise CHUTE_OCR_TIMEOUT, lower CHUTE_OCR_DPI, or try a "
                f"smaller model."
            )
        raise ConversionError(
            f"could not reach Ollama at {host} ({reason}). Is 'ollama serve' "
            f"running and the '{model}' model pulled?"
        )
    except (ConnectionError, http.client.HTTPException) as e:
        # Server went away mid-request (e.g. restarted) — not a URLError.
        raise ConversionError(
            f"connection to Ollama at {host} dropped ({e.__class__.__name__}). "
            f"Did the server restart or the model crash? Ensure 'ollama serve' "
            f"is up, then retry."
        )
    return body.get("response", "").strip()


def pdf_to_md_llama(
    src: Path,
    dst: Path,
    _css: list[Path],
    *,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """OCR a PDF with a local Llama vision model via Ollama.

    Each page is rasterized to PNG and transcribed to Markdown by the vision
    model; pages are joined with a horizontal rule. Unlike the tesseract route
    this reads figures and complex layouts, at the cost of a running Ollama
    server and per-page inference time.

    `progress(page, total)` is invoked before each page so the caller (which
    owns user-facing output) can report advancement on long multi-page runs.
    """
    chunks: list[str] = []
    for page_no, total, png in _iter_pdf_pages(src, OCR_RENDER_DPI):
        if progress is not None:
            progress(page_no, total)
        text = _ollama_ocr_page(png, model=OLLAMA_OCR_MODEL, host=OLLAMA_HOST)
        if text:
            chunks.append(text)
    dst.write_text("\n\n---\n\n".join(chunks) + "\n")


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


def route_tag(
    in_ext: str, out_ext: str, *, ocr: bool = False, ocr_engine: str = DEFAULT_OCR_ENGINE
) -> str:
    if (in_ext, out_ext) == ("pdf", "md"):
        if not ocr:
            return "pymupdf4llm"
        if ocr_engine == "llama":
            return f"ollama:{OLLAMA_OCR_MODEL}"
        return "ocrmypdf+pymupdf4llm"
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
    ocr_engine: str = DEFAULT_OCR_ENGINE,
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
    use_llama = ocr and ocr_engine == "llama"
    if ocr:
        route = pdf_to_md_llama if use_llama else pdf_to_md_ocr
    dst.parent.mkdir(parents=True, exist_ok=True)
    effective_css = css if out_ext in STYLED_OUTPUTS else []
    info(
        f"[{route_tag(in_ext, out_ext, ocr=ocr, ocr_engine=ocr_engine)}] "
        f"{src_label} → {dst_label}",
        verbose=verbose,
    )
    try:
        if use_llama:
            pdf_to_md_llama(
                src, dst, effective_css,
                progress=lambda i, n: info(
                    f"  page {i}/{n} → {route_tag(in_ext, out_ext, ocr=ocr, ocr_engine=ocr_engine)}",
                    verbose=verbose,
                ),
            )
        else:
            route(src, dst, effective_css)
    except ConversionError as e:
        error(f"{src_label}: {e}")
        return False
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
            "scanned or image-only PDFs."
        ),
    )
    p.add_argument(
        "--ocr-engine", choices=OCR_ENGINES, default=DEFAULT_OCR_ENGINE,
        help=(
            "OCR backend for --ocr: 'tesseract' (via ocrmypdf, the default) or "
            "'llama' (a local vision model via Ollama, default qwen3-vl:8b). The "
            "llama engine reads figures and complex layouts but needs a running "
            "Ollama server; tune with CHUTE_OCR_MODEL / CHUTE_OLLAMA_HOST."
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
    ocr_engine = args.ocr_engine
    verbose = args.verbose
    quiet = args.quiet

    if ocr_engine != DEFAULT_OCR_ENGINE and not ocr:
        warn(
            f"--ocr-engine {ocr_engine} has no effect without --ocr; "
            "extracting text without OCR",
            quiet=quiet,
        )

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
            ocr_engine=ocr_engine,
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
            ocr_engine=ocr_engine,
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
    ocr_engine: str,
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
                ocr=ocr, ocr_engine=ocr_engine, verbose=verbose, quiet=quiet,
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
    ocr_engine: str,
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
            ocr=ocr, ocr_engine=ocr_engine, verbose=verbose, quiet=quiet,
        ):
            ok = False
    if not found:
        fail(f"no convertible files (→ .{out_ext}) found in {inp}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
