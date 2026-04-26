# Kai-Exman Design Specifications

This document defines the architectural decisions and technical specifications of Kai-Exman. It is the authoritative reference for how the system is built and why.

For process and workflow guidelines, see [CONTRIBUTING.md](../../CONTRIBUTING.md).

---

## 1. ID System

### Rationale

Kai-Exman follows Git's dual-length identifier standard: full-length for uniqueness and precision, abbreviated for human readability.

### Storage Format

- **Internal**: Every experiment is assigned a **16-character hexadecimal ID** derived from a UUID.
- **Source**: `uuid.uuid4().hex[:16]` in `ExMan._next_id()`.

### Display Rules

- **Default**: Commands show only the first **8 characters**.
- **Full**: Pass `--full-id` to `list` or `show` to reveal the complete 16-character hash.

### Prefix Resolution

The CLI resolves partial IDs via `_resolve_exp_id()`:

- **Exact match**: A 16-character ID resolves directly.
- **Unique prefix**: Any unambiguous prefix (4, 8, or 16 chars) resolves to the single matching experiment.
- **Ambiguous prefix**: Raises a `ClickException` listing all matching IDs.
- **No match**: Raises a `ClickException` indicating no experiment starts with the given prefix.

---

## 2. Tag Format

### Rationale

Tags must be machine-parseable, filesystem-safe, and free of characters that break shell interpolation or YAML serialization.

### Validation Rules

Tags are validated by `validate_tag()` against this regex:

```python
_TAG_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
```

### Constraints

| Rule | Description |
|---|---|
| First character | Must be alphanumeric (`a-z`, `A-Z`, `0-9`) |
| Subsequent characters | Alphanumeric, dot (`.`), underscore (`_`), or hyphen (`-`) |
| Prohibited | Spaces, slashes, emoji, shell metacharacters, commas |
| Empty string | Rejected |
| Idempotency | Adding an existing tag is a no-op |
| Persistence | Tags are stored in `metadata.json` and rewritten on every change |

### Tag Filter Semantics

The `list --tag` filter uses **substring matching**: `--tag baseline` matches an experiment tagged `baseline_v2`. It is not exact-match.

---

## 3. Metadata Schema

### File Location

Each experiment directory contains `metadata.json` at its root.

### Schema (Pydantic v2)

```python
class Metadata(BaseModel):
    exp_id: str                          # 16-char hex experiment ID
    timestamp: str                       # ISO 8601 creation time
    git_hash: str = ""                   # Git commit hash (empty if unavailable)
    git_dirty: bool = False              # True if working tree had uncommitted changes
    tags: list[str] = []                 # Categorical tags
    data_version: str = ""               # Data version or hash for reproducibility
    description: str = ""                # Human-readable description
    status: str = "running"              # Current status: running, success, failed, finished
```

### Status Lifecycle

Experiments transition through the following statuses:

| Status | Meaning | How Set |
|---|---|---|
| `running` | Experiment is active. | Default at initialization. |
| `finished` | Experiment was closed via `finish()` with default status. | `kai-exman finish <exp_id>` |
| `success` | Experiment completed successfully. | `kai-exman finish <exp_id> -s success` |
| `failed` | Experiment terminated with errors. | `kai-exman finish <exp_id> -s failed` |

`finish()` accepts an arbitrary status string, but the four values above are the convention. There is no enforced state machine; callers may set any status they choose.

### On-Disk Layout

```
outputs/
└── YYYYMMDD_<exp_id>_<safe_description>/
    ├── metadata.json
    ├── config.yaml          # Optional experiment configuration
    ├── env.txt              # pip freeze snapshot
    ├── metrics.jsonl        # Append-only metrics log
    ├── summary.md           # Generated on finish
    ├── logs/
    └── artifacts/
        ├── checkpoints/
        ├── plots/
        └── bad_cases.json   # Structured bad-case records
```

---

## 4. UI & Aesthetics

### Design Philosophy

Follow Git's minimalist and industrial aesthetic. No unnecessary borders, no flashy gradients. Information density and clarity come first.

### TTY Detection

The `list` command checks `sys.stdout.isatty()` and adapts its output:

- **For Humans (TTY)**: Uses `rich` for colors, panels, and tables. Pipes long output through a pager (`less -R`).
- **For Agents / Pipes**: Outputs clean plain text without ANSI codes or decorative framing.

Other commands (`init`, `show`, `finish`, `tag`) always render through `rich` but disable color when stdout is not a TTY. Panel and table borders remain in plain text for structural clarity.

### Layout Standards

- Use 4-space indentations for log-style multi-line output.
- Use clear, color-coded headers: green for success, red for failure, blue for running.
- Maintain consistent spacing: one blank line between entries in list views.

### Color Coding

| Element | Color | Usage |
|---|---|---|
| Experiment ID | Yellow | Header line in `list` and `show` |
| Tags | Magenta | Inline tag display |
| Success | Green | Status label |
| Running | Blue | Status label |
| Failed | Red | Status label |
| Finished | Green | Status label |
| Parameters | Blue | Config summary |
| Metric score | Yellow | Sort-by metric display |

---

## 5. Filesystem-as-Database

### Rationale

Kai-Exman uses the filesystem as its primary persistence layer. This eliminates external database dependencies, makes experiments trivially inspectable with standard tools (`ls`, `cat`, `grep`), and ensures that experiment data survives as long as the filesystem does.

### Directory Naming Convention

Experiment folders are named:

```
YYYYMMDD_<exp_id>_<safe_tags_or_description>
```

Where `<safe_tags_or_description>` is sanitized to ASCII alphanumeric, underscore, and hyphen characters only.

### Discovery

`ExMan.list()` scans the root directory for subdirectories containing `metadata.json`. Each valid directory is loaded into an `Experiment` instance.

### Thread Safety

`Experiment` uses a `threading.Lock` to protect concurrent writes to `metrics.jsonl` and `bad_cases.json`. Multiple threads may safely call `log_metrics()` or `log_bad_case()` on the same experiment instance simultaneously.

---

## 6. CLI Commands

### Global Options

All commands accept:

| Option | Description |
|---|---|
| `--path` | Root path for experiments. Defaults to `EXMAN_PATH` env or `./outputs`. |
| `--no-pager` | Disable pager (auto-detected when not a TTY). |
| `--no-color` | Disable colored output (auto-detected when not a TTY). |

### Commands

#### `init`

Initialize a new experiment.

```bash
kai-exman init [--description TEXT] [--tags TAGS] [--config PATH]
```

| Option | Description |
|---|---|
| `-d, --description` | Human-readable experiment description. |
| `-t, --tags` | Comma-separated tags. Empty entries are rejected. |
| `-c, --config` | Path to a YAML configuration file to copy into the experiment. |

#### `list` (alias: `log`)

List experiments in git-log-style format.

```bash
kai-exman list [--sort-by METRIC] [--order {asc,desc}] [--top N] [--oneline] [--tag TAG] [--full-id]
```

| Option | Description |
|---|---|
| `--sort-by` | Metric name to sort by (e.g. `acc`, `loss`). |
| `--order` | `asc` (min first) or `desc` (max first, default). |
| `--top` | Show only the top N experiments. |
| `--oneline` | Use compact one-line format per experiment. |
| `--tag` | Filter experiments by tag name (substring match). |
| `--full-id` | Display full 16-character experiment IDs. |

#### `show`

Display a detailed summary of a specific experiment.

```bash
kai-exman show [--full-id] EXP_ID
```

| Option | Description |
|---|---|
| `--full-id` | Display the full 16-character experiment ID in the metadata panel. |
| `EXP_ID` | Full ID or unambiguous prefix of the experiment to show. |

#### `finish`

Close an experiment and generate `summary.md`.

```bash
kai-exman finish [--status STATUS] [--notes NOTES] EXP_ID
```

| Option | Description |
|---|---|
| `-s, --status` | Final status (default: `finished`). |
| `-n, --notes` | Post-mortem notes included in the summary. |
| `EXP_ID` | Full ID or unambiguous prefix of the experiment to finish. |

#### `tag`

Add or remove a tag on an experiment.

```bash
kai-exman tag [--delete] EXP_ID TAG_NAME
```

| Option | Description |
|---|---|
| `-d, --delete` | Remove the tag instead of adding it. |
| `EXP_ID` | Full ID or unambiguous prefix of the experiment. |
| `TAG_NAME` | Tag to add or remove. Must pass `validate_tag()`. |

---

## 7. Experiment API

The `Experiment` class is the primary interface for recording data during an experiment run.

### Logging Metrics

```python
exp.log_metrics(step=0, values={"loss": 1.5, "acc": 0.3})
```

Appends a JSON line to `metrics.jsonl`. NaN and infinite values are serialized as `null` by Pydantic v2 and skipped when computing best metrics.

### Saving Artifacts

```python
dest = exp.save_artifact("/path/to/model.ckpt", name="best_model.pt")
```

Copies a file or directory into `artifacts/`. Raises `FileNotFoundError` if the source does not exist.

### Logging Bad Cases

```python
exp.log_bad_case(
    case_id="img_42",
    input_data={"features": [1.0, 2.0]},
    prediction="cat",
    ground_truth="dog",
    extra={"confidence": 0.99},
)
```

Appends a structured record to `artifacts/bad_cases.json`. Raises `TypeError` if the data contains non-JSON-serializable values (e.g., `set`).

### Computing Best Metrics

```python
best = exp.compute_best_metrics()
# {"loss": {"max": 1.5, "min": 0.3}, "acc": {"max": 0.95, "min": 0.3}}
```

Scans `metrics.jsonl` and returns the max and min value for each metric. Skips corrupted lines, blank lines, and non-numeric values gracefully.

### Snapshotting the Environment

```python
exp.snapshot_env()
```

Runs `pip list --format=freeze` and writes the output to `env.txt`. If pip is unavailable, writes a placeholder comment.

---

## 8. Error Handling

| Error Condition | Exception Type | Message Pattern |
| --- | --- | --- |
| Invalid tag format | `ValueError` (API) / `ClickException` (CLI) | `Invalid tag format. Use only alphanumeric...` |
| Empty tag string | `ValueError` (API) / `ClickException` (CLI) | Same as above (regex does not match empty string). |
| Ambiguous ID prefix | `ClickException` | `Ambiguous prefix 'abc' matches multiple experiments: ...` |
| No matching ID prefix | `ClickException` | `No experiment found starting with 'xyz'` |
| Missing artifact source | `FileNotFoundError` | Standard Python exception. |
| Non-serializable bad case | `TypeError` | Standard `json.dumps` failure. |
| Missing experiment for `finish` | Returns `None` | `ExMan.finish()` returns `None` instead of raising. |
