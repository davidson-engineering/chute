# chute — document pipeline

A small CLI that converts between document formats with a curated tool stack — Pandoc for the structural conversions, `pymupdf4llm` for reading PDFs, WeasyPrint for clean PDF output. Ships with a bundled stylesheet and two web fonts (IBM Plex Sans, JetBrains Mono) so PDF/HTML output looks identical on any machine, with no configuration.

## Supported routes

| From \ To | `md` | `pdf` | `docx` | `html` |
|-----------|:---:|:---:|:---:|:---:|
| `docx`    | ✓   | ✓ +css | — | ✓ +css |
| `pdf`     | ✓   | —      | — | —      |
| `md`      | —   | ✓ +css | ✓ | ✓ +css |

`+css` means the conversion is styled by default. Pass `--css <file>` to replace the bundled stylesheet, or `--no-style` to disable styling entirely.

## Install

### Recommended: `uv tool install`

```sh
uv tool install git+https://github.com/davidson-engineering/chute.git
```

To pin a specific release:

```sh
uv tool install git+https://github.com/davidson-engineering/chute.git@v0.1.0
```

You'll also need `pandoc` and `weasyprint` on `PATH`.

**macOS:**

```sh
brew install pandoc weasyprint
```

**Debian / Ubuntu:**

```sh
sudo apt install pandoc libpango-1.0-0 libpangoft2-1.0-0
uv tool install weasyprint  # or pipx install weasyprint
```

(WeasyPrint depends on Pango/Cairo native libraries — the `libpango*` packages provide them.)

To upgrade later:

```sh
uv tool upgrade chute
```

### From source

```sh
git clone https://github.com/davidson-engineering/chute.git
cd chute
uv tool install .
```

## Usage

```text
chute <input> [-o <output>] [-t <format>] [-r] [--css <file>] [--no-style]
```

**Rules for choosing the output:**
- `-o file.ext` — exact path; extension determines target format
- `-t format` — implicit path `./<stem>.<format>` (or `<dir>/<stem>.<format>` if `-o` is a directory)
- For a directory input, `-t` is required

### Examples

```sh
chute report.docx -o report.pdf                # docx → styled PDF
chute report.docx -t html                      # → ./report.html, styled
chute paper.pdf -t md                          # → ./paper.md
chute notes.md -o notes.pdf --css print.css    # md → PDF with your CSS
chute notes.md -o notes.pdf --no-style         # md → PDF, no styling at all
chute ./docs -t pdf -r -o ./out                # batch: mirror tree, convert to PDF
```

## Styling

By default, every `pdf` or `html` output is rendered with the bundled stylesheet — minimal grayscale, IBM Plex Sans for prose, JetBrains Mono for code. Both fonts are embedded in the package, so output renders identically regardless of what's installed on the host.

- `--css <file>` — replaces the default stylesheet. Pass multiple times to concatenate.
- `--no-style` — disable the default (and any `--css`).

CSS is plumbed through pandoc to weasyprint, so anything WeasyPrint supports (including `@page` rules for margins, page size, headers/footers) works.

### Callouts

The default stylesheet recognises pandoc fenced divs as callout boxes:

```md
::: note
Heads-up about something the reader should be aware of.
:::

::: warning
Something that can go wrong.
:::

::: tip
A helpful aside.
:::

::: danger
Critical — don't ignore.
:::
```

Each renders as a block with a subtle left rule. Override the `.note`, `.tip`, `.warning`, `.danger` selectors with `--css` to change the look.

## Environment

| Variable             | Default       | Effect |
|----------------------|---------------|--------|
| `CHUTE_PDF_ENGINE`   | `weasyprint`  | Pandoc `--pdf-engine` value for PDF output. |

## Development

```sh
git clone https://github.com/davidson-engineering/chute.git
cd chute
uv sync --group dev
uv run pytest
```

The test suite stubs pandoc/pymupdf4llm by default and runs in well under a second. Integration tests that exercise the real toolchain run automatically if `pandoc` and `weasyprint` are on `PATH`; otherwise they're skipped.

## License

chute itself is MIT — see [LICENSE](LICENSE).

The bundled fonts are distributed under the [SIL Open Font License 1.1](https://openfontlicense.org/) — see [`src/chute/styles/fonts/`](src/chute/styles/fonts/) for the original copyright notices and license texts.
