# chute — document pipeline

A small CLI that converts between document formats with a curated tool stack — Pandoc for the structural conversions, `pymupdf4llm` for reading PDFs, WeasyPrint for clean PDF output. Bundles a default stylesheet so PDF/HTML output looks reasonable without any configuration.

## Supported routes

| From \ To | `md` | `pdf` | `docx` | `html` |
|-----------|:---:|:---:|:---:|:---:|
| `docx`    | ✓   | ✓ +css | — | ✓ +css |
| `pdf`     | ✓   | —      | — | —      |
| `md`      | —   | ✓ +css | ✓ | ✓ +css |

`+css` means the conversion respects the default stylesheet and any `--css` overrides.

## Install

### Recommended: `uv tool install`

```sh
uv tool install git+https://github.com/davidson-engineering/chute.git
```

To pin a specific release:

```sh
uv tool install git+https://github.com/davidson-engineering/chute.git@v0.1.0
```

You'll also need `pandoc` and `weasyprint` on `PATH`:

```sh
brew install pandoc weasyprint
```

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

By default, every `pdf` or `html` output is rendered with the bundled stylesheet (`src/chute/styles/default.css`) — clean serif body, GitHub-ish code blocks, sensible page margins.

- `--css <file>` — replaces the default stylesheet. Pass multiple times to concatenate.
- `--no-style` — disable the default (and any `--css`).

CSS is plumbed through pandoc to weasyprint, so anything WeasyPrint supports (including `@page` rules for margins, page size, headers/footers) works.

## Environment

| Variable             | Default       | Effect |
|----------------------|---------------|--------|
| `CHUTE_PDF_ENGINE`   | `weasyprint`  | Pandoc `--pdf-engine` value for PDF output. |

## License

MIT — see [LICENSE](LICENSE).
