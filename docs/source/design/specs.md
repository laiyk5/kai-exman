# Kai-Exman Design Specifications

This document defines the architectural decisions and technical specifications of Kai-Exman. It is the authoritative reference for how the system is built and why.

For process and workflow guidelines, see `CONTRIBUTING.md` in the repository root.

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
| --- | --- |
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
    data_version: str = ""               # Manual data version string (legacy)
    data_hash: str = ""                  # BLAKE2b hash of --data-path (auto-computed)
    description: str = ""                # Human-readable description
    status: str = "draft"                # Current status: draft, running, finished, aborted
    finished_at: str = ""               # ISO timestamp when the lab record was sealed
    locked: bool = False                 # True once finish() or abort() seals the record
    summary: str = ""                    # Conclusion written by finish()
    parent_ids: list[str] = []           # Set for inherited experiments (multi-parent support)
    attempts: list[Attempt] = []         # Execution attempts for resumption tracking
    group: str = "default"               # Physical group name (filesystem subdirectory)
    deletable: bool = False              # Marked for cascade removal when childless
```

### Status Lifecycle

Experiments transition through the following statuses:

| Status | Meaning | How Set |
| --- | --- | --- |
| `draft` | Experiment created but not yet executed. | `init()` creates experiments as drafts. |
| `running` | Experiment is active (has at least one attempt). | After the first `run()` creates attempt 1. |
| `success` | Experiment completed successfully (exit code 0). | `finish()` when last attempt has `exit_code == 0`. |
| `failed` | Experiment terminated with errors (non-zero exit). | `finish()` when last attempt has non-zero `exit_code`. |
| `aborted` | Experiment was stopped or did not complete (no exit code). | `abort()` or `finish()` when last attempt has `exit_code is None`. |

`finish()` **auto-determines** status from the last attempt's `exit_code`. It does **not** accept an arbitrary status string. The state machine is enforced:

- `finish()` raises `RuntimeError` if the experiment has **no attempts**.
- `finish()` raises `LockedExperimentError` if the experiment has already been **sealed**.
- `resume()` raises `LockedExperimentError` if the experiment is already in a **terminal state** (`success`, `failed`, or `aborted`).
- Terminal experiments are immutable; create a new iteration (Case B) to evolve them.

### Lab Scribe Protocol

When an experiment reaches a terminal state, it is **sealed** by the Lab Scribe protocol:

1. `finished_at` is set to the current ISO 8601 timestamp.
2. `locked` is set to `True`.
3. `metadata.json` is written with `force=True` (bypassing the lock check).
4. All subsequent calls to `write_metadata()`, `add_tag()`, `remove_tag()`, or `update_status()` on this experiment raise `LockedExperimentError`.

This ensures the lab record is immutable once sealed, guaranteeing audit trail integrity.

### Git Dirty Semantics

`git_dirty` does **not** mean "any uncommitted change." It means
"uncommitted changes in logic-critical files."

| Classification | Paths | Impact on `git_dirty` |
| --- | --- | --- |
| Critical | `src/`, `pyproject.toml`, `uv.lock`, build files | Changes here set `git_dirty = True` |
| Non-Critical | `docs/`, `tests/`, `README.md`, `.gitignore` | Changes here leave `git_dirty = False` |

This distinction prevents documentation edits from producing false
reproducibility warnings while preserving strictness for code changes.

### On-Disk Layout

```
outputs/
├── index.json                 # Lookup cache
├── .current                   # Default experiment ID
├── .trash/                    # Deleted experiments
├── default/
│   └── YYYYMMDD_<exp_id>_<safe_description>/
│       ├── metadata.json
│       ├── config.yaml        # Optional experiment configuration
│       ├── env.txt            # pip freeze snapshot
│       ├── code.patch         # Present if git_dirty at init time
│       ├── metrics.jsonl      # Append-only metrics log
│       ├── summary.md         # Generated on finish / abort
│       ├── logs/
│       └── artifacts/
│           ├── checkpoints/
│           ├── plots/
│           └── bad_cases.json # Structured bad-case records
├── train/
│   └── ...
└── eval/
    └── ...
```

---

## 4. UI & Aesthetics

### Design Philosophy

Follow Git's minimalist and industrial aesthetic. No unnecessary borders, no flashy gradients. Information density and clarity come first.

### TTY Detection

All commands check `sys.stdout.isatty()` and adapt their output:

- **For Humans (TTY)**: Rich markup is rendered as ANSI color codes.
- **For Agents / Pipes**: Rich markup tags are stripped, producing clean plain text without ANSI codes.

The output structure is **identical** in both modes. Only colors differ. Rich `Table` and `Panel` are intentionally avoided because they reorganize information between interactive and non-interactive shells, increasing maintenance burden and confusion. All commands render via a single code path (`_echo_lines()`) that leverages Rich's built-in markup stripping when `force_terminal=False`.

### Pager Policy

Any command that produces output which may exceed one terminal screen **must** pipe through a pager when `stdout.isatty()` is `True`. The pager is configured with `LESS=-R` to preserve ANSI color codes.

This applies to all list-style commands (`list`, `list --oneline`, `list --tree`) and any future command that renders tabular or multi-line experiment data. Plain-text (non-TTY) output never uses a pager; it streams directly to `stdout` for agent consumption.

### Layout Standards

- Use 4-space indentations for log-style multi-line output.
- Use clear, color-coded headers: green for success, red for failure, blue for running.
- Maintain consistent spacing: one blank line between entries in list views.

### Color Coding

| Element | Color | Usage |
| --- | --- | --- |
| Experiment ID | Yellow | Header line in `list` and `show` |
| Tags | Magenta | Inline tag display |
| Success | Green | Status label |
| Running | Blue | Status label |
| Failed | Red | Status label |
| Aborted | Dim | Status label |
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

## 6. Configuration & Precedence

Kai-Exman uses a three-layer configuration system similar to Git:
**Defaults < pyproject.toml < CLI Flags**.

### Default Values

| Key | Default | Description |
| --- | --- | --- |
| `critical_paths` | `["src/", "pyproject.toml"]` | Paths checked for dirty-state detection. |
| `ignore_paths` | `["docs/", "tests/", "README.md", "*.md", ".gitignore"]` | Paths considered non-critical (reserved for future filtering). |
| `short_id_length` | `8` | Number of characters displayed for abbreviated experiment IDs. |
| `strict_mode` | `false` | When true, enables stricter validation behavior. |

### pyproject.toml Override

Add a `[tool.kaiexman]` section to your project's ``pyproject.toml``:

```toml
[tool.kaiexman]
critical_paths = ["src/", "pyproject.toml", "configs/"]
strict_mode = true
short_id_length = 12
```

Missing keys fall back to defaults. If ``pyproject.toml`` does not exist,
the system runs entirely on defaults without error.

### CLI Flag Override

Any CLI flag takes highest precedence and replaces the value from
``pyproject.toml`` or defaults:

| Flag | Effect |
| --- | --- |
| `--strict` | Enable strict mode. |
| `--critical-path` | Comma-separated list that **replaces** the default critical paths. |
| `--short-id-length` | Override the abbreviated ID length. |

Example:

```bash
kai-exman --critical-path "lib/,pyproject.toml" --strict init -d "safe run"
```

---

## 7. CLI Commands

### Global Options

All commands accept:

| Option | Description |
| --- | --- |
| `--path` | Root path for experiments. Defaults to `EXMAN_PATH` env or `./outputs`. |
| `--no-pager` | Disable pager (auto-detected when not a TTY). |
| `--no-color` | Disable colored output (auto-detected when not a TTY). |
| `--strict` | Enable strict mode (overrides pyproject.toml). |
| `--critical-path` | Override critical paths (comma-separated). |
| `--short-id-length` | Override short ID display length. |

### Commands

#### `init`

Create a draft experiment. This is the only command that creates experiments.

```bash
kai-exman init -d "..." [-t TAGS] [-c CONFIG] [--data-path PATH] [-g GROUP] [--inherit PID ...]
```

| Option | Description |
| --- | --- |
| `-d, --description` | Human-readable experiment description. **Required** in non-TTY mode. |
| `-t, --tags` | Comma-separated tags. Empty entries are rejected. |
| `-c, --config` | Path to a YAML configuration file to copy into the experiment. |
| `--data-path` | Path to a dataset file or directory. A BLAKE2b hash is computed automatically and stored in `data_hash`. |
| `-g, --group` | Target group (default: `default`). |
| `--inherit` | Parent experiment ID to inherit from. Can be repeated for multi-parent. |

#### `run`

Execute a command on an existing experiment. Never creates a new experiment.

```bash
kai-exman run [EXP_ID] [--data-path PATH] [--reason TEXT] -- COMMAND
```

| Option | Description |
| --- | --- |
| `EXP_ID` | Optional experiment ID. Uses default experiment if omitted. |
| `--data-path` | Dataset path for automatic BLAKE2b hash. |
| `--reason` | Reason for this attempt (e.g. `retry after OOM`). Defaults to `run_N`. |
| `COMMAND` | Command and arguments to execute, after `--`. |

- On a **draft** experiment → creates attempt 1 and executes.
- On a **running** experiment → appends attempt N (requires clean git state).
- On a **finished** or **aborted** experiment → raises an error.

The command is recorded in the attempt's `command` field for full reproducibility.

#### `list` (alias: `log`)

List experiments in git-log-style format.

```bash
kai-exman list [--sort-by METRIC] [--order {asc,desc}] [--top N] [--oneline] [--tree] [--tag TAG] [--group GROUP] [--full-id]
```

| Option | Description |
| --- | --- |
| `--sort-by` | Metric name to sort by (e.g. `acc`, `loss`). |
| `--order` | `asc` (min first) or `desc` (max first, default). |
| `--top` | Show only the top N experiments. |
| `--oneline` | Use compact one-line format per experiment. |
| `--tree` | Display experiments in lineage tree view. |
| `--tag` | Filter experiments by tag name (substring match). |
| `--group` | Filter experiments by group name. |
| `--full-id` | Display full 16-character experiment IDs. |

#### `status` (alias: `show`)

Display a detailed summary of a specific experiment.

```bash
kai-exman status [EXP_ID] [--full-id]
```

| Option | Description |
| --- | --- |
| `--full-id` | Display the full 16-character experiment ID in the metadata panel. |
| `EXP_ID` | Full ID or unambiguous prefix. Uses default experiment if omitted. |

#### `finish`

Close an experiment and generate `summary.md`.

```bash
kai-exman finish [EXP_ID] -s "..." [-n NOTES]
```

| Option | Description |
| --- | --- |
| `-s, --summary` | **Mandatory** conclusion reflecting on the experiment. |
| `-n, --notes` | Optional post-mortem notes included in the summary. |
| `EXP_ID` | Full ID or unambiguous prefix. Uses default experiment if omitted. |

Status is auto-determined from the last attempt's `exit_code`: `0` → `success`, non-zero → `failed`, `None` → `aborted`. Raises an error if the experiment has no attempts or if already sealed.

#### `abort`

Permanently seal an experiment as having no value. No summary is required.

```bash
kai-exman abort [EXP_ID] [-n NOTES]
```

| Option | Description |
| --- | --- |
| `-n, --notes` | Optional notes for the generated `summary.md`. |
| `EXP_ID` | Full ID or unambiguous prefix. Uses default experiment if omitted. |

The act of aborting is the complete statement. The summary is set to `"Aborted by user."` automatically. Aborted experiments cannot be inherited from.

#### `tag`

Add or remove a tag on an experiment.

```bash
kai-exman tag [EXP_ID] TAG_NAME [--delete]
```

| Option | Description |
| --- | --- |
| `-d, --delete` | Remove the tag instead of adding it. |
| `-l, --list` | List all tags across experiments. |
| `EXP_ID` | Full ID or unambiguous prefix. Uses default experiment if omitted. |
| `TAG_NAME` | Tag to add or remove. Must pass `validate_tag()`. |

#### `group` (alias: `suggest-groups`)

Suggest group assignments or list all groups.

```bash
kai-exman group [-l] [--threshold FLOAT] [--apply]
```

| Option | Description |
| --- | --- |
| `-l, --list` | List all existing groups with experiment counts. |
| `--threshold` | Jaccard similarity threshold for suggestions (default: from config). |
| `--apply` | Apply suggested group moves (interactive TTY only). |

#### `move`

Move an experiment to another group.

```bash
kai-exman move [EXP_ID] -g GROUP
```

| Option | Description |
| --- | --- |
| `-g, --group` | **Required.** Target group name. |
| `EXP_ID` | Full ID or unambiguous prefix. Uses default experiment if omitted. |

#### `use`

Set the default experiment for the current root.

```bash
kai-exman use EXP_ID
```

#### `rm`

Move an experiment to trash, or purge trash entirely.

```bash
kai-exman rm [EXP_ID] [--yes] [--dry-run] [--mark-deletable] [--clear-trash]
```

| Option | Description |
| --- | --- |
| `-y, --yes` | Skip confirmation prompt. Required for non-TTY use. |
| `--dry-run` | Preview what would be moved or purged without acting. |
| `--mark-deletable` | Schedule for cascade removal when childless. |
| `--clear-trash` | Permanently delete all items in trash (`EXP_ID` not required). |

---

## 8. Experiment API

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

### Lifecycle Convenience Methods

When an experiment is created through `ExMan`, it stores a weak back-reference to its manager. This enables lifecycle convenience methods without passing IDs:

```python
exp = exman.init(description="Baseline training", tags=["v1"])

# Execute on this experiment
exp.run(["python", "train.py", "--epochs", "10"])

# Retry with a reason
exp.run(["python", "train.py"], reason="retry after OOM")

# Finish
exp.finish(summary="Converged to 92%.")
```

| Method | Delegates To | Raises |
| --- | --- | --- |
| `exp.run(command, data_path="", reason="")` | `ExMan.run()` | `RuntimeError` if no manager reference. |
| `exp.finish(notes="", summary="")` | `ExMan.finish()` | `RuntimeError` if no manager reference. |
| `exp.abort(notes="")` | `ExMan.abort()` | `RuntimeError` if no manager reference. |

---

## 9. Error Handling

| Error Condition | Exception Type | Message Pattern |
| --- | --- | --- |
| Invalid tag format | `ValueError` (API) / `ClickException` (CLI) | `Invalid tag format. Use only alphanumeric...` |
| Empty tag string | `ValueError` (API) / `ClickException` (CLI) | Same as above (regex does not match empty string). |
| Ambiguous ID prefix | `ClickException` | `Ambiguous prefix 'abc' matches multiple experiments: ...` |
| No matching ID prefix | `ClickException` | `No experiment found starting with 'xyz'` |
| Missing artifact source | `FileNotFoundError` | Standard Python exception. |
| Non-serializable bad case | `TypeError` | Standard `json.dumps` failure. |
| Missing experiment for `finish` | `ValueError` | `Experiment '<id>' not found` |
| Finish with no attempts | `RuntimeError` | `Experiment '<id>' has no attempts...` |
| Finish already sealed | `LockedExperimentError` | `Experiment <id> is already sealed...` |
| Resume locked experiment | `LockedExperimentError` | `Experiment <id> is already sealed...` |
| Modify locked metadata | `LockedExperimentError` | `Experiment <id> is locked...` |

---

## 10. Deletion & Trash Policy

### Rationale

Permanent deletion is dangerous. Kai-Exman moves experiments to a hidden ``.trash/`` directory instead of destroying them immediately. This provides a recovery window and prevents accidental data loss.

### Trash Location

A ``.trash/`` subdirectory inside the experiment root (e.g., ``outputs/.trash/``). It is excluded from experiment discovery.

### Moving to Trash

When ``ExMan.remove()`` or ``kai-exman rm`` is called:

1. Capacity check: oldest trashed items are purged if limits would be exceeded.
2. A ``.deletion_info`` JSON file is written inside the experiment folder with:
   - ``deleted_at``: ISO 8601 timestamp
   - ``original_path``: absolute path before moving
3. The folder is moved via ``shutil.move()`` for cross-filesystem safety.

### Capacity Management

Two limits govern the trash:

| Limit | Default | Description |
| --- | --- | --- |
| ``trash_max_count`` | 50 | Maximum number of trashed experiment folders. |
| ``trash_max_size_gb`` | 5.0 | Maximum total size of trash in gigabytes. |

Before adding a new item, the system purges the oldest (by ``deleted_at``) until both limits are satisfied. Oldest-first eviction uses LRU semantics.

### CLI: `rm`

```bash
kai-exman rm [--yes] [--dry-run] [--clear-trash] [EXP_ID]
```

| Option | Description |
| --- | --- |
| ``-y, --yes`` | Skip confirmation prompt. Required for non-TTY use. |
| ``--dry-run`` | Preview what would be moved or purged without acting. |
| ``--clear-trash`` | Permanently delete all items in trash (``EXP_ID`` not required). |

### TTY Confirmation Rules

| Context | Behavior |
| --- | --- |
| TTY + no ``--yes`` | Interactive ``Proceed? [y/N]`` prompt. |
| Non-TTY + no ``--yes`` | Raises ``ClickException`` requiring ``--yes`` or ``--dry-run``. |
| ``--dry-run`` | No confirmation required; only previews actions. |
| ``--yes`` | Skips confirmation and proceeds. |

### API Reference

```python
# Move experiment to trash (auto-purges oldest if over capacity)
exp, purged = exman.remove(exp_id="abc123...", dry_run=False)

# Empty trash entirely
 deleted = exman.clear_trash(dry_run=False)
```

---

## 11. Lifecycle: Resumption & Lineage

### Rationale

Experiments fail. Networks drop, disks fill, and hyperparameters need tuning. A rigorous system must distinguish between two recovery modes:

| Mode | Code State | Behavior | Identity |
| --- | --- | --- | --- |
| **Retry** (Case A) | Unchanged (Logic-Clean) | Re-open existing experiment, append new attempt. | Same ID |
| **Evolution** (Case B) | Changed (Logic-Dirty) | Create new experiment, copy artifacts, link parent. | New ID |

This prevents "identity confusion" where a modified run overwrites results from the original commit.

### Metadata Schema

```python
class Attempt(BaseModel):
    sequence: int
    start_time: str
    end_time: str = ""
    status: str = "running"
    exit_code: int | None = None
    reason: str = ""
    command: list[str] = []  # argv recorded at attempt start

class Metadata(BaseModel):
    # ... existing fields ...
    parent_id: str = ""      # Set for evolved experiments (Case B)
    attempts: list[Attempt] = []  # Populated for retries (Case A)
    data_hash: str = ""      # BLAKE2b hash of dataset at init time
```

### Context-Aware Resume Logic

``ExMan.resume()`` with ``mode="auto"`` implements automatic case detection. The CLI uses explicit ``--retry`` and ``--inherit`` flags:

1. Capture current Git state (hash + dirty flag on critical paths).
2. Compare against the parent experiment's recorded ``git_hash``.
3. **Case A** (hash matches, workspace is clean, **and parent has at least one attempt**):
   - Append a new ``Attempt`` record with ``sequence = len(attempts) + 1`` and ``reason = "run_N"``.
   - Set environment variable ``KAI_EXMAN_ATTEMPT_COUNT`` to the new sequence number.
   - Blocked if the experiment is in a terminal state (raises ``LockedExperimentError``).
4. **Case B** (hash differs, workspace is dirty, **or parent has no attempts**):
   - Call ``ExMan.init()`` with a new UUID.
   - Set ``metadata.parent_id`` to the old experiment ID.
   - Append an initial ``Attempt(sequence=1, status="running", reason="run_1")``.
   - Symlink all files from ``parent/artifacts/checkpoints/`` into the new experiment.
     Falls back to a hard copy if symlinking fails (e.g., on Windows without Developer Mode).
   - Set ``KAI_EXMAN_PARENT_PATH`` to the parent's root directory.
   - Emits a warning if the parent has no successful attempts (only configuration is inherited, not data/state).

### Environment Variables

When ``kai-exman run`` executes a command, the following variables are injected:

| Variable | Value | When Set |
| --- | --- | --- |
| ``KAI_EXMAN_RESUME`` | ``1`` | Always when ``--retry`` or ``--inherit`` is used. |
| ``KAI_EXMAN_PARENT_PATH`` | Absolute path to parent experiment root | Case B (new inherited experiment). |
| ``KAI_EXMAN_ATTEMPT_COUNT`` | Attempt sequence number (1, 2, 3...) | Case A (retry of existing experiment). |

### Passive Logging Approach

Kai-Exman does not manage the user's log files directly. Instead, it provides ``KAI_EXMAN_ATTEMPT_COUNT`` so the user's script can name its own log files:

```python
import os
attempt = os.environ.get("KAI_EXMAN_ATTEMPT_COUNT", "1")
log_file = f"run{attempt}.log"  # run1.log, run2.log, ...
```

This avoids the fragility of automatic log rotation while giving the user full control over log naming and location.

### Status Promotion

When an experiment has multiple attempts, its global status (shown in ``list`` and ``show``) is always the status of the latest attempt. For example, if Attempt 1 was ``failed`` but Attempt 2 is ``success``, the experiment is displayed as ``success``.

```bash
# Fresh experiment
kai-exman run -- python train.py

# Resume (automatic Case A / Case B detection)
kai-exman run --retry <exp_id> -- python train.py
kai-exman run --inherit <exp_id> --description "Fork" -- python train.py
```

| Option | Description |
| --- | --- |
| ``--retry`` | Experiment ID to retry (Case A). Parent must be ``running``. |
| ``--inherit`` | Experiment ID to inherit from (Case B). Parent must be ``finished``. |
| ``-d, --description`` | Description for a new experiment (Case B). |
| ``-t, --tags`` | Tags for a new experiment (Case B). |
| ``-c, --config`` | Config YAML for a new experiment (Case B). |

After the command exits, the last attempt record (Case A) or the experiment status (Case B) is updated with the exit code.

### UI: Lineage Indicators

| Command | Indicator | Meaning |
| --- | --- | --- |
| ``list`` | ``->`` prefix before ID | Experiment has a ``parent_id``. |
| ``list --tree`` | ``○`` root marker | Draft experiment (no attempts yet). |
| ``list --tree`` | ``*`` root marker | Experiment with at least one attempt. |
| ``show`` | ``Parent: <short_id>`` row | Displays the parent experiment link. |
| ``show`` | ``Attempts`` panel | Table of all retry attempts with start/end times and status. |
