# Multi-Parent Inheritance & Explicit Python API

## 1. Problem: Single Parent is Too Restrictive

The old `Metadata.parent_id: str | None` assumed an experiment inherits from at most one ancestor. In practice, a new experiment often combines artifacts or insights from **multiple** prior experiments:

- **Ensemble training**: inherits checkpoints from three independently trained models.
- **Cross-group evaluation**: inherits a model from group `train` and a dataset config from group `data`.
- **Ablation study**: creates a child that merges the best hyperparameters from two finished experiments.

A single `parent_id` cannot express these relationships.

## 2. Decision: `parent_ids` List

Replace the scalar `parent_id` with a list `parent_ids`. Both the Python API and the CLI support **multiple inheritance**.

### Metadata Schema Change

```python
class Metadata:
    # ... existing fields ...
    parent_ids: list[str] = Field(default_factory=list)
    # parent_id removed
```

- **Empty list** → root experiment (no parents).
- **One element** → single inheritance (backward-compatible with existing data).
- **Multiple elements** → multi-parent inheritance.

### Index Cache

`index.json` stores `"parent_ids"` per experiment. On load, a scalar `"parent_id"` in existing `metadata.json` is transparently upgraded to a single-element list for backward compatibility.

## 3. Explicit Python API

Today `ExMan.resume()` is overloaded: it auto-detects retry vs. inherit. This is convenient but violates the principle of explicit intent. We split creation and execution into two dedicated methods.

### `ExMan.init()` — Create a Draft

```python
def init(
    self,
    description: str = "",
    tags: list[str] | None = None,
    config: dict | None = None,
    data_version: str = "",
    group: str = "default",
    data_path: str = "",
    parent_ids: list[str] | None = None,
) -> Experiment:
```

- **New parameter**: `parent_ids` — list of finished experiments to inherit from.
- **Behavior**: If `parent_ids` is provided, the new experiment is created and checkpoints/configs are merged from all parents.
- **Constraint**: All parent experiments must be `finished`. Aborted or `running` parents raise `ValueError`.

### `ExMan.run()` — Execute on Existing Experiment

```python
def run(
    self,
    exp_id: str,
    command: list[str],
    data_path: str = "",
    reason: str = "",
) -> tuple[Experiment, int]:
```

- **Semantics**: Execute a command on an existing experiment.
- On a **draft** → creates attempt 1 and executes.
- On a **running** experiment → appends a new attempt (git clean required).
- On a **finished** or **aborted** experiment → raises `ValueError`.

### `ExMan.retry()` — Backward-Compatible Wrapper

```python
def retry(
    self,
    exp_id: str,
    command: list[str],
    data_path: str = "",
    reason: str = "",
) -> tuple[Experiment, int]:
```

- **Semantics**: Append a new attempt to an existing **running** experiment.
- **Validation**: Raises if the experiment is not `running` or has no attempts.
- **Note**: This is a thin wrapper around `run()`. New code should use `run()` directly.

### Deprecation of `ExMan.resume()`

`resume()` is kept with `mode="auto"` for backward compatibility, but it is **deprecated** in docstrings. New code should use `init()` + `run()` directly.

## 4. CLI Changes

### `init` Gains `--inherit`

Since `init` is the sole creation command, it supports inheritance:

```bash
# Single inheritance
kai-exman init -d "Ensemble eval" --inherit a1b2c3d4

# Multi-parent inheritance
kai-exman init -d "Cross-group fusion" \
  --inherit a1b2c3d4 \
  --inherit b2c3d4e5 \
  --group eval
```

`--inherit` is a **multi-value option** (Click `multiple=True`).

### `run` is Execution-Only

`run` never creates a new experiment. It only executes on an existing one:

```bash
# Run on draft (creates attempt 1)
kai-exman run a1b2c3d4 -- python train.py

# Run on running experiment (appends attempt N)
kai-exman run a1b2c3d4 -- python train.py
```

The `retry` CLI command has been removed; `run` handles both drafts and running experiments.

### Tree View (`list --tree`)

With multiple parents, the lineage is a **DAG**, not a tree.

- An experiment with multiple parents is rendered under **each** parent branch.
- A `[multi-parent]` marker is shown.

Example:

```text
* a1b2c3d4  FINISHED  baseline training
    └── o c3d4e5f6  FINISHED  ablation A
* b2c3d4e5  FINISHED  alternate preprocessing
    └── o c3d4e5f6  FINISHED  ablation A  [multi-parent]
```

## 5. Data Model

### Metadata

```python
class Metadata:
    exp_id: str
    group: str
    description: str
    summary: str | None
    tags: list[str]
    status: str              # "draft" | "running" | "finished" | "aborted"
    locked: bool
    parent_ids: list[str]    # ← new, replaces parent_id
    git_hash: str | None
    git_dirty: bool
    data_version: str
    data_hash: str
    timestamp: str
    finished_at: str | None
    attempts: list[Attempt]
    deletable: bool
```

### Attempt

Unchanged.

## 6. Checkpoint Name Collision

When multiple parents provide checkpoints with the same filename:

```
parent_a/artifacts/checkpoints/best.pt
parent_b/artifacts/checkpoints/best.pt
```

The child receives:

```
child/artifacts/checkpoints/a1b2c3d4_best.pt
child/artifacts/checkpoints/b2c3d4e5_best.pt
```

If a parent has only one checkpoint and there is **no collision**, the file is symlinked/copied with its original name (preserving backward compatibility for the single-parent case).

## 7. Trash / Cascade Delete

Multi-parent experiments complicate cascade deletion:

- A multi-parent experiment can be moved to trash **independently** of any single parent.
- `mark_deletable` on a parent does **not** automatically delete a multi-parent child when that parent is removed, because the child still has other parents. Cascade only triggers when **all** parents are gone.

## 8. Acceptance Criteria

1. `ExMan.init(parent_ids=["a1b2c3d4", "b2c3d4e5"], description="...")` creates a child with both parents in `parent_ids`.
2. `ExMan.run(exp_id, ["python", "train.py"])` on a draft creates attempt 1.
3. `ExMan.run(exp_id, ["python", "train.py"])` on a running experiment appends attempt N.
4. `init --inherit a1b2c3d4 --inherit b2c3d4e5` creates a draft with two parents.
5. Checkpoint name collisions are resolved with `{parent_short}_` prefix.
6. `list --tree` renders multi-parent experiments under each parent branch with a `[multi-parent]` indicator.
7. Old `parent_id` fields in existing `metadata.json` are transparently upgraded to `parent_ids` on load.
8. All changes pass `pytest`, `mypy --strict src/`, `ruff check`.
