# Multi-Parent Inheritance & Explicit Python API

## 1. Problem: Single Parent is Too Restrictive

The current `Metadata.parent_id: str | None` assumes an experiment inherits from at most one ancestor. In practice, a new experiment often combines artifacts or insights from **multiple** prior experiments:

- **Ensemble training**: inherits checkpoints from three independently trained models.
- **Cross-group evaluation**: inherits a model from group `train` and a dataset config from group `data`.
- **Ablation study**: creates a child that merges the best hyperparameters from two finished experiments.

A single `parent_id` cannot express these relationships.

## 2. Decision: `parent_ids` List

Replace the scalar `parent_id` with a list `parent_ids`. Both the Python API and the CLI must support **multiple inheritance**.

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

`index.json` already stores `"parent_id"` per experiment. Migrate to `"parent_ids"` (list). On load, a scalar `"parent_id"` is transparently upgraded to a single-element list for backward compatibility.

## 3. Explicit Python API

Today `ExMan.resume()` is overloaded: it auto-detects retry vs. inherit. This is convenient but violates the principle of explicit intent. We split it into three dedicated methods.

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

### `ExMan.retry()` — Explicit Retry (Case A)

```python
def retry(
    self,
    exp_id: str,
    data_path: str = "",
) -> tuple[Experiment, int]:
```

- **Semantics**: Append a new attempt to an existing **running** experiment.
- **Validation**: Parent must be `running`, workspace must be clean.
- **Returns**: `(experiment, attempt_number)`.

### `ExMan.inherit()` — Explicit Inherit (Case B)

```python
def inherit(
    self,
    parent_ids: list[str],
    description: str,
    tags: list[str] | None = None,
    config: dict | None = None,
    data_version: str = "",
    group: str = "default",
    data_path: str = "",
) -> Experiment:
```

- **Semantics**: Create a new experiment that inherits from one or more finished parents.
- **Validation**:
  - Every parent must exist.
  - Every parent must be `finished` (not `running` or `aborted`).
  - `description` is **required** (a child is a new exploration).
- **Merging rules**:
  - `tags`: union of all parent tags (deduplicated), overridable via `tags` parameter.
  - `config`: deep-merge of all parent configs (last parent wins on key collision), overridable via `config` parameter.
  - `checkpoints`: symlink/copy from **all** parents into `artifacts/checkpoints/`. Name collisions are resolved by prefixing with the parent's short ID: `{parent_short}_{original_name}`.

### Deprecation of `ExMan.resume()`

`resume()` is kept with `mode="auto"` for backward compatibility, but it is **deprecated** in docstrings. New code should use `init()`, `retry()`, or `inherit()` explicitly.

## 4. CLI Changes

### `init` Gains `--inherit`

Since `init` already exists as a standalone command (creating a draft without running), it should support inheritance:

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

### `run` Keeps `--inherit` (Single or Multiple)

```bash
# Single
kai-exman run --inherit a1b2c3d4 -d "Tune LR" -- python train.py

# Multiple
kai-exman run --inherit a1b2c3d4 --inherit b2c3d4e5 -d "Ensemble" -- python train.py
```

### `retry` Remains Explicit

```bash
kai-exman retry a1b2c3d4 -- python train.py
```

`retry` does **not** support multiple experiments; it appends an attempt to exactly one running experiment.

### Tree View (`list --tree`)

With multiple parents, the lineage is a **DAG**, not a tree.

- An experiment with multiple parents is rendered under **each** parent branch.
- A `[*]` marker indicates multi-parent experiments.

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

1. `ExMan.inherit(["a1b2c3d4", "b2c3d4e5"], description="...")` creates a child with both parents in `parent_ids`.
2. `ExMan.retry("a1b2c3d4")` appends an attempt only if the experiment is `running`.
3. `init --inherit a1b2c3d4 --inherit b2c3d4e5` creates a draft with two parents.
4. `run --inherit a1b2c3d4 --inherit b2c3d4e5` creates a child and copies checkpoints from both.
5. Checkpoint name collisions are resolved with `{parent_short}_` prefix.
6. `list --tree` renders multi-parent experiments under each parent branch with a `[multi-parent]` indicator.
7. Old `parent_id` fields in existing `metadata.json` are transparently upgraded to `parent_ids` on load.
8. All changes pass `pytest`, `mypy --strict src/`, `ruff check`.
