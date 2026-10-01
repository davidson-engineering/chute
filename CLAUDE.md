# chute — context for Claude

A small CLI that converts between document formats by dispatching to the right
tool (`pandoc`, `pymupdf4llm`, `weasyprint`, and, for `--ocr`, `ocrmypdf` or a
local vision model via Ollama) for each (input, output) pair.

## Shape

- Single-file CLI: `src/chute/cli.py`. Routes are a dict keyed on
  `(in_ext, out_ext)` → converter function.
- Each converter is a thin shell over a subprocess (pandoc) or a library call
  (`pymupdf4llm`). They should not print or log — `convert_one` owns
  user-facing output.
- A converter that can't handle a file raises `ConversionError`;
  `convert_one` reports it and a batch carries on. Run external tools through
  `_run()` and open PDFs through `_open_pdf()` so their failures arrive that
  way instead of as a traceback that aborts the batch.
- Styling: bundled `src/chute/styles/default.css` with embedded woff2 fonts
  (IBM Plex Sans, JetBrains Mono). The fonts are load-bearing for reproducible
  PDF/HTML output, so don't strip them from packaging.
- Version comes from git tags via `hatch-vcs` (writes `_version.py` at build).

## CLI conventions

The CLI is modeled on pandoc's surface to minimize what a user has to learn.

- `-f`/`--from`, `-t`/`--to`, `-o`/`--output` — pandoc-style format flags
- `-v`/`--verbose`, `-q`/`--quiet` — universal Unix pair
- `-` for stdin/stdout; stdin requires `-f`, stdout requires `-t`
- All chute-emitted output goes to **stderr**. Stdout is reserved for
  `-o -` binary content. If you add new logging, use `info()`/`warn()` (both
  stderr) — never bare `print()`.
- `fail()` writes `chute: <msg>` to stderr and exits 1. It is not gated by
  `-q`.

## Tests

```sh
uv sync --group dev
uv run pytest         # unit + integration
```

- `tests/conftest.py` stubs `subprocess.run` (pandoc) and the `pymupdf4llm`
  module via fixtures. Unit tests run with no external tools and finish in
  under a second.
- `tests/test_integration.py` exercises the real toolchain; tests are skipped
  if `pandoc` or `weasyprint` aren't on `PATH` (see `needs_pandoc` /
  `needs_weasyprint` in conftest).

When adding a new route, add a unit test using `fake_pandoc` (or
`fake_pymupdf`) and — if the route ends in PDF — an integration test guarded
by `needs_weasyprint`.

## Conventions I want to keep

- **Keep the surface small.** Don't add flags that mirror pandoc options the
  user could already pass via configuration. The CLI's job is routing and
  defaults, not exposing every pandoc knob.
- **No format heuristics.** Extension is the default; `-f` is the override.
  Don't sniff file contents.
- **stdin/stdout staging is intentional.** Both pandoc subprocesses and
  `pymupdf4llm` want real paths. The temp-file approach trades streaming for
  uniform route handling — don't try to push `-` through to pandoc directly
  unless you also handle the `pymupdf4llm` path.
- **`--css` not `--stylesheet`.** Spelled to match pandoc (which is what the
  CSS is actually piped to), even though weasyprint and md-to-pdf prefer
  `--stylesheet`.
