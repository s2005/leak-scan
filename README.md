# leak-scan

Scan a git-tracked tree for content that must not be published.

`leak-scan` walks every file `git ls-files` reports for a repository (or an
exported tree) and applies a configurable set of regular-expression rules,
grouped into categories, to flag lines that must never reach a public
audience: author identity, employer affiliation, machine-specific paths,
dangling references to private task records, credentials, and anything else
you configure. It is designed to be the last gate before a repository is
published.

The tool itself never hardcodes what it searches for. Every pattern, label,
category and allowlist comes from a configuration file (see
[Configuration](#configuration)) - the scanner's source code contains no
site-specific literal at all.

## Requirements

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/)
- `git` on `PATH` (the scanner only reads files `git ls-files` reports)

## Install

Development setup:

```bash
uv sync
```

Install as a global executable:

```bash
uv tool install --from . leak-scan
uv tool update-shell
```

`uv tool install` installs the `leak-scan` command from this checkout into
uv's tool directory. `uv tool update-shell` adds that directory to your user
`PATH`. Open a new terminal after the PATH update, then verify the executable:

```bash
leak-scan --version
leak-scan --help
```

The version command prints exactly `leak-scan 0.0.1`. Help includes the same
`leak-scan 0.0.1` version banner. Neither discovery command requires `--repo`
or any other scan input.

If you change the source code, reinstall the command so the executable uses the
latest checkout:

```bash
uv tool install --from . --force leak-scan
```

## Quick start

```bash
uv run leak-scan --repo . --config leak-scan.yaml
```

## Configuration

**The working configuration is never committed.** It necessarily contains
the real personal, employer, host and path literals you are hunting for -
committing it would republish exactly what it exists to catch. Keep it in an
untracked `leak-scan.yaml` (or `.yml` / `.json`) at the repository root; the
project's own `.gitignore` refuses to track those three filenames. Only the
sanitised `leak-scan.example.yaml` and `leak-scan.example.json` files - built
entirely from placeholder values - are committed, as a documented starting
point to copy from.

If `--config` is omitted, `leak-scan` searches the current working directory
and then `--repo` for the first of `leak-scan.yaml`, `leak-scan.yml`,
`leak-scan.json`.

### Schema (version 1)

| Key | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `version` | int | yes | - | Must equal `1`. |
| `categories` | list | yes | - | Non-empty list of category mappings. |
| `path_allow` | list of regex strings | no | `[]` | A tracked file whose relative path matches any of these is skipped entirely. |
| `binary_suffixes` | list of strings | no | built-in set | File suffixes (e.g. `.png`) that are never read. |

Each **category**:

| Key | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `name` | str | yes | - | Unique category identifier. |
| `description` | str | no | `""` | Free-text note. |
| `rules` | list | yes | - | Non-empty list of rule mappings. |
| `allow` | mapping | no | none | Suppression rules for this category's hits. |

Each **rule**:

| Key | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `label` | str | yes | - | Human text printed alongside a hit. |
| `pattern` | str | yes | - | A regular expression. |
| `ignore_case` | bool | no | `true` | Compile the pattern case-insensitively. |

Each **allow** mapping (all keys optional):

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `context` | list of regex strings | `[]` | A hit is suppressed when its match span falls inside a match of one of these regexes on the same line. |
| `values` | list of strings | `[]` | Compared case-insensitively against the rule match's named group `value`, after stripping surrounding whitespace and `"` `'` `` ` `` characters. |
| `value_patterns` | list of regex strings | `[]` | `re.match` against that same stripped value. |
| `min_value_length` | int | `0` | A stripped value shorter than this is suppressed. |
| `require_letter_and_digit` | bool | `false` | When true, a stripped value that lacks either a letter or a digit is suppressed. |

The four value-based `allow` keys only apply to rules whose `pattern`
defines a named group `(?P<value>...)`; for rules without one, they are
inert.

### Commented sample

See the committed [`leak-scan.example.yaml`](leak-scan.example.yaml) for the
full, heavily-commented reference (also available as
[`leak-scan.example.json`](leak-scan.example.json)). An abridged excerpt:

The example YAML and JSON configurations also contain useful, ready-to-adapt
API-key prefix patterns in the `api_key_prefix` category. They cover common
GitHub, GitLab, AWS, Stripe secret, Slack, OpenAI, Anthropic, Groq, Hugging
Face, Perplexity, DigitalOcean, Databricks, npm and PyPI credential formats.
The YAML file explains the rules inline; the JSON file contains the equivalent
machine-readable configuration.

These are pattern examples rather than a complete provider catalogue. Keep
the real working configuration untracked, copy the relevant rules into it,
and adjust the prefixes and length checks when a provider changes its token
format. Stripe publishable `pk_` keys are intentionally not included because
they are designed to be exposed to client-side code.

```yaml
version: 1

categories:
  # Replace every placeholder pattern below with your real handle, given
  # name, surname and personal email address in your untracked leak-scan.yaml.
  - name: identity
    description: "Author identity markers: handle, name, personal address."
    rules:
      - label: "author handle"
        pattern: "example-handle"

  # Generic path forms that name no real machine - safe to keep as-is.
  - name: machine
    description: "Drive-rooted local paths and unix home directories."
    rules:
      - label: "unix home directory path"
        pattern: "/home/[A-Za-z0-9_.-]+/"
    allow:
      context:
        - "/home/(?:user|youruser|runner|me|<[^>]+>)/"

  - name: credential
    description: "password / token / secret / api_key assignments that are not placeholders."
    rules:
      - label: "credential assignment"
        pattern: "(?:password|passwd|pwd|token|secret|api[_-]?key)\\s*[:=]\\s*(?P<value>[\"'`]?[^\\s\"'`,;()]+[\"'`]?)"
    allow:
      values: ["change_me", "changeme", "password", "secret", "token"]
      value_patterns: ["^\\$\\{.*\\}$", "^<.*>$"]
      min_value_length: 6
      require_letter_and_digit: true

path_allow: []

binary_suffixes: [".png", ".jpg", ".pdf", ".zip"]
```

## CLI reference

| Option | Required | Default | Description |
| --- | --- | --- | --- |
| `--repo` | yes | - | Path to the git repository or exported tree to scan. |
| `--config` | no | search cwd then `--repo` | Path to the scanner configuration file. |
| `--category` | no | all categories | Limit output to a single configured category. |
| `--quiet` | no | `False` | Print only the per-category summary, not each hit. |
| `--show-matches` | no | `False` | Print raw matching source lines; use only for intentional local investigation. |
| `--format` | no | `text` | Output format: `text` or `json`. |
| `--log-level` | no | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `--version` | no | - | Print `leak-scan 0.0.1` and exit without scan inputs. |
| `--help` | no | - | Print usage with the `leak-scan 0.0.1` banner and exit without scan inputs. |

## Examples

```bash
# Scan the current tree with an explicit config file
uv run leak-scan --repo . --config leak-scan.yaml

# Summary only
uv run leak-scan --repo . --quiet

# Limit to one category
uv run leak-scan --repo . --category credential

# Machine-readable output
uv run leak-scan --repo . --format json

# Intentionally reveal raw matching lines during a local investigation
uv run leak-scan --repo . --show-matches
```

## Output

Text output is one line per hit, followed by exact file accounting and a
per-category summary. Matching source text is redacted by default:

```text
path/to/file.py:42: [identity] author handle: <redacted>

Scanned 126 of 128 tracked files in /path/to/repo; skipped 2
------------------------------------------------------------
identity         1 hit(s) in    1 file(s)
machine          0 hit(s) in    0 file(s)
credential       0 hit(s) in    0 file(s)
------------------------------------------------------------
TOTAL            1 hit(s)
```

JSON output (`--format json`) is a single document:

```json
{
  "repo": "/path/to/repo",
  "tracked_files": 128,
  "scanned_files": 126,
  "skipped_files": 2,
  "skips": [
    { "path": "path/to/logo.png", "reason": "binary_suffix" },
    { "path": "path/to/vendor.txt", "reason": "path_allow" }
  ],
  "total": 1,
  "counts": { "identity": 1 },
  "hits": [
    { "path": "path/to/file.py", "line": 42, "category": "identity", "label": "author handle", "text": "<redacted>" }
  ]
}
```

The `text` key remains present in JSON for schema stability. Supply
`--show-matches` only when raw source lines are required for a local
investigation; raw output can copy a detected credential into terminal logs
or saved reports. `--quiet` omits per-hit rows even when `--show-matches` is
also supplied. Skip reasons are `path_allow`, `binary_suffix`, and `null_byte`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | No hits. |
| 1 | At least one hit survived. This is the tool's normal "found something" signal, not a crash. |
| 2 | Usage or environment error: unreadable, missing, or invalid config; `--repo` is not a directory; unknown `--category`; or a git failure. |

## Scan boundaries

`leak-scan` scans the current working-tree bytes of paths reported by
`git ls-files`. It does not inspect earlier Git commits, reflogs, unreachable
Git objects, or content that exists only in another ref. A clean current-tree
scan therefore says nothing about values removed from an existing repository's
history.

The scanner also does not download Git LFS payloads or unpack archives,
documents, images, or other containers. If the working tree contains a Git LFS
pointer, only that pointer is scanned. Files with configured binary suffixes
and files detected by a null byte are intentionally skipped and reported in
the accounting output; their embedded content is outside this tool's scope.

Before publishing an existing repository with its history, run an independent
history scanner against every reachable ref. For example, with Gitleaks
installed:

```bash
gitleaks git --redact=100 --log-opts=--all .
```

Review the independent scanner's installation and trust policy separately.
Neither tool proves that unreachable local objects or external Git LFS storage
are clean.

## Using it as a publication gate

Run the scan against the tree that will actually be published, not just the
working repository. `git archive` serialises exactly the tracked set, so
private local files cannot ride along even by accident:

```bash
mkdir -p <fresh-dir>
git archive HEAD | tar -x -C <fresh-dir>

cd <fresh-dir>
git init -b main
git add .

leak-scan --repo . --config <path-to-your-untracked-config>
```

This is a history-free publication path only when the exported files are
committed to a new repository and that new repository is published. Pushing
the existing repository instead publishes the reachable history of the refs
you push, so the independent history scan remains required.

Two caveats:

1. The scan reads what `git ls-files` reports, so in a fresh directory it
   must run **after** `git init` and `git add .`, or it will find no files
   and report a misleading clean result.
2. Any pattern hit found there blocks publication. Fix the source, not the
   allowlist.

## Maintaining the pattern set

Add a pattern to your config when a new class of leak appears; do not add a
`path_allow` exemption. `path_allow` is empty by design in the committed
example - every path exemption is a hole, so a hit is fixed at the source
instead.

After any config edit, re-run against a known-dirty tree and confirm the
scanner still reports the expected inventory. A scanner that reports nothing
has two possible causes - a clean tree, or a broken pattern - and they are
indistinguishable from the output alone.

## Development

```bash
uv sync                      # install dependencies
uv run leak-scan --help
uv run pytest                # all tests
uv run pytest -m unit        # unit tests only
uv run pytest --cov          # tests with coverage
uv run ruff check --fix .    # lint and autofix
uv run ruff format .         # format
uv run mypy                  # type check
```

## Testing

Tests never embed real site-specific literals; they use invented ones
(`acme-corp`, `jdoe`, and similar) so the test suite itself never becomes the
kind of tracked file the tool is built to flag. `tests/conftest.py` provides
a small config fixture and a scratch git repository fixture seeded with a
clean file and a file containing planted hits; tests requiring `git` skip
cleanly when it is not on `PATH`.

## CI

GitHub Actions runs the test suite and lint/type checks on every push and
pull request against `main` (see `.github/workflows/ci.yml`).

## License

MIT
