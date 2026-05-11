# mpp — markdown pipeline

A small bash CLI that converts documents to Markdown by routing each file to the right tool:

| Extension | Tool          | Why |
|-----------|---------------|-----|
| `.docx`   | `pandoc`      | Fast, structural — preserves headings, lists, tables. |
| `.pdf`    | `marker_single` | ML-based — handles complex layouts, tables, equations, scanned pages. |

It works on a single file or a whole directory tree, and mirrors the input layout under the output directory.

## Why

`pandoc` is excellent for native formats but treats PDFs as flat text. `marker` handles messy PDFs well but is slow and brittle on `.docx` (its docx pipeline goes via weasyprint, which often produces malformed PDFs). `mpp` picks the right tool per file so you don't have to.

## Install

Requires:
- [pandoc](https://pandoc.org/) (`brew install pandoc`)
- [marker](https://github.com/datalab-to/marker) (`uv tool install marker-pdf`)
- bash 4+ (`brew install bash` on macOS)

Then:

```sh
git clone https://github.com/davidson-engineering/mpp.git
cd mpp
make install
```

This symlinks `bin/mpp` into `~/.local/bin/mpp`. Make sure `~/.local/bin` is on your `PATH`.

To install elsewhere:

```sh
make install PREFIX=/usr/local
```

## Usage

```text
mpp <input> [-o <output>] [-r|--recursive]
```

### Single file

```sh
mpp resume.docx                   # → ./markdown_out/resume.md
mpp resume.docx -o ./out/         # → ./out/resume.md
mpp resume.docx -o resume.md      # exact file path
mpp paper.pdf  -o ./out/          # → ./out/paper.md
```

### Directory

```sh
mpp ./docs                        # converts *.docx and *.pdf in ./docs
mpp ./docs -o ./md                # writes results to ./md/
mpp ./docs -o ./md --recursive    # recurses, mirroring tree under ./md/
```

## Behaviour

- **Default output:** `./markdown_out/`.
- **Single file + `-o file.md`:** writes to that exact path.
- **Single file + `-o dir/`:** writes `dir/<stem>.md`.
- **Directory:** mirrors the input tree under the output directory (full tree if `--recursive`, top-level only otherwise).
- **Unsupported extensions:** skipped with a warning to stderr.
- **Marker output flattening:** `marker_single` writes to a nested `<stem>/<stem>.md` directory by default; `mpp` flattens this so you get a single `.md` per input.

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | Success |
| 1    | Input not found, or no compatible files in directory |
| 2    | Bad arguments |
| 127  | `pandoc` or `marker_single` not on `PATH` |

## License

MIT — see [LICENSE](LICENSE).
