# Reproducibility Enhancements

This document specifies four enhancements to Kai-Exman's reproducibility guarantees. Together they address the core gap between "we record a git hash" and "we can actually reproduce this experiment."

---

## 1. Attempt-Level Command Recording

### Problem

The exact command executed for each attempt is never persisted. If a user runs:

```bash
kai-exman run -d "baseline" -- python train.py --lr 0.01 --epochs 100
```

…the metadata knows the experiment exists, but not what was actually invoked. After months, or after a coding agent varies flags across retries, the original invocation is lost.

### Decision

Add a `command: list[str]` field to the `Attempt` model. The CLI populates it before execution.

```python
class Attempt(BaseModel):
    sequence: int
    start_time: str
    end_time: str = ""
    status: str = "running"
    exit_code: int | None = None
    reason: str = ""
    command: list[str] = []   # NEW
```

### Recording Rules

- `command` is captured at the moment `_execute_in_context()` begins.
- It is written into the attempt record **before** the subprocess starts, so even if the process is killed the command is preserved.
- For Case A (retry), the new attempt records the command used for that retry.
- For Case B (inherit), the child experiment's first attempt records the child's command.
- No sanitisation beyond Pydantic's JSON serialisation. The raw argv is preserved.

### On-Disk Impact

`metadata.json` grows by one array per attempt. For typical experiments this is negligible.

---

## 2. Automatic Git Diff Patch

### Problem

`git_dirty` is a boolean. When it is `True`, the experiment is formally un-reproducible — we know code changed, but not what changed. A coding agent that edits files between runs leaves no trail.

### Decision

When `Experiment.write_metadata()` detects a dirty workspace, it also writes a `code.patch` file containing the full diff against HEAD for all critical paths.

```python
def _save_diff_patch(self) -> None:
    """If dirty, write git diff to code.patch."""
```

### Rules

- The patch is generated with `git diff HEAD -- <critical_paths>`.
- It is written to `<exp_root>/code.patch`.
- If the workspace is clean, `code.patch` is not created (absence implies cleanliness).
- If Git is unavailable or the directory is not a repository, the operation is silently skipped.
- The patch is written **once** at `write_metadata()` time (typically init or attempt creation). It captures the state at the start of the attempt, not any later edits.

### Edge Cases

| Scenario | Behaviour |
|----------|-----------|
| Untracked files in critical paths | Included in patch via `git diff --cached` + `git diff` combined approach |
| Binary files | Git emits "Binary files differ"; we keep that line |
| Very large diffs (>1 MB) | Still written; disk is cheaper than lost reproducibility |
| No git repo | Silent no-op |

---

## 3. Abort: Remove Summary Requirement

### Problem

The `abort` CLI command currently requires a `summary`, contradicting design decision D4 in `lifecycle.rst`:

> "An aborted experiment is explicitly marked as having no value. Requiring a summary would create the false impression that the experiment contributes something worth documenting."

### Decision

- `abort` no longer accepts or requires `--summary`.
- `abort` directly seals the experiment with `status="aborted"`, `locked=True`, and a minimal summary.md stating "Aborted by user."
- The CLI option `--summary` is removed from the `abort` command.

### Migration

Existing scripts that pass `--summary` to `abort` will fail with Click's "no such option" error. This is intentional — the old behaviour was a design violation.

---

## 4. Automatic Dataset Hash

### Problem

`data_version` is a free-form string. Users must manually compute and pass it. In practice, it is often omitted or contains ad-hoc labels like `"v2"` that carry no cryptographic guarantee of data identity.

### Decision

Add an automatic dataset hash mechanism:

1. **New CLI option**: `--data-path PATH` on `run`, `retry`, and `init`.
2. **New metadata field**: `data_hash: str` on `Metadata`.
3. **Hash algorithm**: BLAKE2b (32-byte digest). Faster than SHA-256 and collision-resistant enough for this domain.
4. **Semantics**:
   - If `--data-path` points to a file → hash the file contents.
   - If `--data-path` points to a directory → recursively hash all files, sorted deterministically.
   - If omitted → `data_hash` remains empty (backward compatible).

### Directory Hash Algorithm

```
for each file in directory, sorted by relative path:
    compute file_blake2b
    feed "{rel_path}:{file_hash}\n" into directory hasher
directory_hash = directory_hasher.hexdigest()
```

This is deterministic, order-independent (because we sort), and transparent (a human can reconstruct it).

### Performance

- Files are read in 8 KiB chunks.
- For a 1 GB dataset, this is a single sequential scan — acceptable for experiment initialisation.
- If the dataset is on network storage, the cost is borne once at init time.

### On-Disk Layout

```
outputs/
└── YYYYMMDD_<exp_id>_desc/
    ├── metadata.json          # now contains data_hash
    ├── config.yaml
    ├── env.txt
    ├── code.patch             # NEW: present if git_dirty
    ├── metrics.jsonl
    ├── summary.md
    ├── logs/
    └── artifacts/
```

---

## Schema Changes

### Metadata

```python
class Metadata(BaseModel):
    # ... existing fields ...
    data_hash: str = ""        # NEW: blake2b hash of --data-path
```

### Attempt

```python
class Attempt(BaseModel):
    # ... existing fields ...
    command: list[str] = []    # NEW: argv for this attempt
```

---

## CLI Changes

### `run`

Add `--data-path` option:

```bash
kai-exman run -d "train" --data-path ./data/train -- python train.py
```

### `init`

Add `--data-path` option:

```bash
kai-exman init -d "setup" --data-path ./data/train
```

### `retry`

Add `--data-path` option (allows data change on retry, though typically unused):

```bash
kai-exman retry <id> --data-path ./data/train -- python train.py
```

### `abort`

Remove `--summary` option. Signature becomes:

```bash
kai-exman abort [--notes NOTES] EXP_ID
```

---

## Acceptance Criteria

1. `run -- echo hello` produces metadata where `attempts[0].command == ["echo", "hello"]`.
2. Running in a dirty repo produces `code.patch` containing the diff.
3. `abort <id>` succeeds without `--summary` and produces `status="aborted"`.
4. `run --data-path ./data -- ...` produces a non-empty `data_hash`.
5. All changes pass `pytest`, `mypy --strict src/`, `ruff check`, and `ruff format --check`.
