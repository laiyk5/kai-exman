# CLI Redesign: Explicit Creation + Multi-Parent Inheritance

## 1. Discarding "If No Run, No Experiment"

### Old Principle

Every experiment record was created by executing a command. There was no standalone creation step. `init` existed as a command but was conceptually a "draft run" of a no-op.

### New Principle

**`init` is the only way to create an experiment.** It produces a draft with empty attempts. `run` is execution-only: it never creates a new experiment record.

This gives the user explicit control over creation vs. execution. An experiment exists because the user explicitly decided it should exist, not because a command happened to run.

```bash
# 1. Explicitly create
kai-exman init -d "Baseline training"

# 2. Explicitly run
kai-exman run <exp_id> -- python train.py

# 3. Explicitly finish
kai-exman finish -s "Converged to 95% acc."
```

---

## 2. `init` is the Sole Creation Command

### Fresh Experiment

```bash
kai-exman init -d "Baseline training" --tags "baseline,llama3" --config config.yaml
```

- Creates a draft experiment.
- `attempts` is empty.
- Status is `draft`.

### Inherited Experiment (Multi-Parent)

```bash
kai-exman init -d "Ensemble eval" \
  --inherit a1b2c3d4 \
  --inherit b2c3d4e5 \
  --group eval
```

- `--inherit` is a **multi-value option** (can appear multiple times).
- Every parent must be `finished`. Aborted or `running` parents raise an error.
- The child copies checkpoints from all parents.
- `attempts` is empty (it is a draft, not a run).

### Merging Rules for Inheritance

| Field | Rule |
|-------|------|
| `tags` | Union of all parent tags (deduplicated), overridable via `--tags`. |
| `config` | Deep-merge of all parent configs (last parent wins on collision), overridable via `--config`. |
| `checkpoints` | Symlinked / copied from all parents. Name collisions resolved by prefixing with parent short ID: `{parent_short}_{original_name}`. |
| `group` | Defaults to `"default"`, overridable via `--group`. |

---

## 3. `run` is Execution-Only

`run` never creates a new experiment. It only executes a command on an **existing** experiment.

```bash
kai-exman run [<exp_id>] -- python train.py
```

- If `exp_id` omitted → uses the default experiment.
- If the experiment is `draft` → creates attempt 1, executes.
- If the experiment is `running` → checks git clean, creates attempt N, executes (this is retry).
- If the experiment is `finished` or `aborted` → error. The user must `init --inherit` to create a child.

### Why Remove `--retry` and `--inherit` from `run`?

- **No silent creation**: `run` no longer has any mode that creates a new experiment. The user must explicitly `init` first.
- **No ambiguous flags**: `--retry` and `--inherit` on `run` were workarounds for the old "run creates experiments" model. With `init` as the creation gate, they are unnecessary.
- **Default experiment + `run`**: Since `run` targets an existing experiment, omitting the ID naturally falls back to the default. This is simpler than option-value defaults.

### Error Messages

| User Action | Error |
|-------------|-------|
| `run <finished_id> -- cmd` | "Experiment is finished. Use `init --inherit <id>` to create a child." |
| `run <aborted_id> -- cmd` | "Aborted experiments cannot be run." |
| `run <running_id> -- cmd` (git dirty) | "Workspace has diverged. Finish or abort this experiment first, then `init --inherit` to create a child." |

---

## 4. Updated Lifecycle

```text

   init -d "..."
      |
      v
  +--------+
  | draft  |  ← attempts: []
  +---+----+
      |
      | run -- python train.py
      | (creates attempt 1)
      v
  +---------+
  | running |  ← attempts: [1: running]
  +----+----+
       |
       | run -- python train.py   (git clean)
       | (appends attempt 2)
       v
   +---------+
   | running |  ← attempts: [1: success, 2: running]
   +----+----+
        |
   +----+----+
   | finish  |  ← locks experiment
   | abort   |
   v         v
+--------+ +--------+
|finished| |aborted |
|(locked)| |(locked)|
+--------+ +--------+
    |
    | init --inherit <id> -d "..."
    v
+--------+
| draft  |  ← new experiment, parent_ids = [id]
+--------+
```

---

## 5. Data Model Changes

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
    parent_ids: list[str]    # ← replaces parent_id, supports multi-parent
    git_hash: str | None
    git_dirty: bool
    data_version: str
    data_hash: str
    timestamp: str
    finished_at: str | None
    attempts: list[Attempt]
    deletable: bool
```

### Backward Compatibility

On load, a scalar `parent_id` in existing `metadata.json` is transparently upgraded to a single-element `parent_ids` list.

---

## 6. Python-First API

The Python API is a **first-class citizen**. Everything the CLI can do, a Python script can do with the same explicit semantics.

### `ExMan.init()` — Create Draft

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

### `ExMan.run()` — Execute on Existing Experiment

```python
def run(
    self,
    exp_id: str,
    command: list[str],
    data_path: str = "",
) -> tuple[Experiment, int]:
    """Execute a command on an existing experiment.

    Creates attempt 1 for a draft, or appends an attempt for a running
    experiment. Validates git state for retries.

    Returns:
        Tuple of (experiment, exit_code).
    """
```

### `ExMan.finish()` / `ExMan.abort()` — Seal

Unchanged signatures, but `exp_id` is **required** (no default experiment fallback in the Python API; that is a CLI convenience).

### `Experiment` Convenience Methods

```python
exp = exman.init(description="Baseline")
exp.run(["python", "train.py"])      # delegates to ExMan.run()
exp.finish(summary="Done.")          # delegates to ExMan.finish()
exp.add_tag("baseline")              # existing
exp.log_metrics(step=0, values={"loss": 1.5})  # existing
```

`Experiment` stores a weak back-reference to its `ExMan` so that lifecycle methods can delegate without the user passing IDs around.

### Deprecation of `ExMan.resume()`

`resume()` is removed from the public API. The CLI and Python scripts use `init()` + `run()` directly.

### Example Script

```python
from kaiexman import ExMan

exman = ExMan()

# Create a baseline
baseline = exman.init(description="Baseline training", tags=["v1"])
baseline.run(["python", "train.py", "--epochs", "10"])
baseline.finish(summary="Converged to 92%.")

# Create a child that inherits from baseline
child = exman.init(
    description="Tune learning rate",
    parent_ids=[baseline.metadata.exp_id],
)
child.run(["python", "train.py", "--lr", "0.01"])
child.finish(summary="Best LR is 0.01.")
```

---

## 7. Tree View (`list --tree`)

With multi-parent inheritance, lineage is a **DAG**.

- An experiment with multiple parents is rendered under **each** parent branch.
- A `[multi-parent]` marker is shown.

```text
* a1b2c3d4  FINISHED  baseline training
    └── o c3d4e5f6  RUNNING  ensemble eval  [multi-parent]
* b2c3d4e5  FINISHED  alternate preprocessing
    └── o c3d4e5f6  RUNNING  ensemble eval  [multi-parent]
```

---

## 8. Commands Reference

| Command | Purpose | Creates Experiment? |
|---------|---------|---------------------|
| `init -d "..."` | Create a fresh draft. | **Yes** (new root) |
| `init -d "..." --inherit <id>` | Create a draft child from finished parent(s). | **Yes** (child) |
| `run [<id>] -- cmd` | Execute command on existing experiment. | No |
| `finish [<id>] -s "..."` | Seal experiment. | No |
| `abort [<id>]` | Abort experiment. | No |
| `status [<id>]` | Display details. | No |
| `tag [<id>] <tag>` | Add/remove tag. | No |
| `move [<id>] -g <group>` | Move to group. | No |
| `rm [<id>]` | Move to trash. | No |
| `use <id>` | Set default experiment. | No |

---

## 9. Acceptance Criteria

1. `init -d "..."` creates a draft with empty `attempts`.
2. `init -d "..." --inherit a1b2c3d4 --inherit b2c3d4e5` creates a draft with two parents.
3. `run <draft_id> -- cmd` creates attempt 1 and executes.
4. `run <running_id> -- cmd` (git clean) appends attempt N and executes.
5. `run <finished_id> -- cmd` raises: "Experiment is finished. Use `init --inherit`."
6. `run <aborted_id> -- cmd` raises: "Aborted experiments cannot be run."
7. Old `parent_id` fields are transparently upgraded to `parent_ids` on load.
8. `list --tree` renders multi-parent experiments under each parent.
9. All changes pass `pytest`, `mypy --strict src/`, `ruff check`.
