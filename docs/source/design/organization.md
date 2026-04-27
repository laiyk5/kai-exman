# Three-Dimensional Experiment Organization System

## Technical Design Document

**Status**: Draft (Pending Approval)
**Author**: Senior Software Architect
**Date**: 2026-04-27
**Scope**: Kai-Exman v0.2.0

---

## 1. Data Model & Schema

### 1.1 Design Rationale

Experiment management tools face a fundamental tension between three orthogonal needs:

1. **Group (Physical / Structural)** — The primary container. Maps to a subdirectory under `.exman/`. Used for physical isolation and task-level classification (e.g., `train`, `eval`, `ablation`).

2. **Lineage (Evolutionary / Automatic)** — Woven automatically via `parent_id`. Represents causal ancestry: which experiment's artifacts and state directly informed this one. Supports cross-Group tracing (a child in `eval` can descend from a parent in `train`).

3. **Tag (Logical / Metadata)** — A multi-valued attribute set. Enables cross-Group horizontal retrieval. Tags are arbitrary categorical strings (e.g., `#Paper_V1`, `resnet50`, `baseline`) attached to metadata and indexed for fast filtering.

Kai-Exman v0.1.0 supported Lineage (`parent_id`) and Tag (`tags`). This document introduces **Group** as the third dimension, completing a system where any experiment can be located by answering three independent questions: "In what group?", "From what ancestor?", and "With what tags?"

### 1.2 Updated Metadata Schema

The `Metadata` Pydantic model gains a single new field:

```python
class Metadata(BaseModel):
    exp_id: str
    timestamp: str
    git_hash: str = ""
    git_dirty: bool = False
    tags: list[str] = Field(default_factory=list)
    data_version: str = ""
    data_hash: str = ""            # BLAKE2b hash of --data-path
    description: str = ""
    status: str = "running"
    parent_id: str = ""
    attempts: list[Attempt] = Field(default_factory=list)
    group: str = "default"          # NEW in v0.2.0
    deletable: bool = False
```

| Field | Type | Default | Semantics |
| --- | --- | --- | --- |
| `group` | `str` | `"default"` | Physical group name. Lowercase, alphanumeric, hyphens, underscores. |

### 1.3 Group Naming Rules

Groups are validated by `validate_group()` against this regex:

```python
_GROUP_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
```

| Rule | Constraint |
| --- | --- |
| First character | Lowercase alphanumeric (`a-z`, `0-9`) |
| Subsequent | Lowercase alphanumeric, underscore (`_`), or hyphen (`-`) |
| Maximum length | 32 characters |
| Prohibited | Uppercase, spaces, slashes, dots, shell metacharacters |
| Empty string | Rejected; falls back to `"default"` |
| Idempotency | Moving an experiment to its current group is a no-op |

Rationale for lowercase restriction: group names appear in filesystem paths. Mixed-case paths are a portability hazard on case-insensitive filesystems (macOS, Windows). Lowercase eliminates ambiguity.

### 1.4 Index Cache Schema

A new `.exman/index.json` file is maintained at the experiments root for O(1) ID resolution and tag-indexed lookup. It is a **derived cache**, not a source of truth. If corrupted or missing, it is rebuilt by scanning all groups.

```json
{
  "version": 1,
  "last_rebuilt": "2026-04-27T14:32:01",
  "experiments": {
    "a1b2c3d4e5f67890": {
      "path": "/abs/path/to/.exman/train/20260427_a1b2c3d4_baseline",
      "group": "train",
      "parent_id": "",
      "tags": ["baseline", "Candidate"]
    }
  },
  "tag_index": {
    "Candidate": ["a1b2c3d4e5f67890", "b2c3d4e5f6a78901"],
    "baseline": ["a1b2c3d4e5f67890"]
  },
  "group_index": {
    "train": ["a1b2c3d4e5f67890", "b2c3d4e5f6a78901"],
    "eval": ["c3d4e5f6a7b89012"]
  }
}
```

| Section | Purpose |
| --- | --- |
| `experiments` | ID -> full metadata path lookup. Eliminates filesystem walk for `get()`. |
| `tag_index` | Tag -> list of experiment IDs. Enables fast `--tag` filtering. |
| `group_index` | Group -> list of experiment IDs. Enables fast `--group` filtering. |

**Consistency Guarantee**: The index is lazily updated on every `init()`, `resume()` (Case B), `remove()`, and `move()`. A `rebuild_index()` utility is exposed for recovery. The filesystem remains the source of truth; the index is advisory.

---

## 2. Physical vs. Logical Mapping

### 2.1 Directory Structure

The flat `outputs/YYYYMMDD_<id>_<desc>/` layout is replaced by a grouped hierarchy:

```text
.exman/                                    # Root directory
├── index.json                             # Lookup cache
├── .trash/                                # Global trash (cross-group)
│   └── ...
├── default/                               # Default group for ungrouped experiments
│   └── 20260427_a1b2c3d4_test_run/
│       ├── metadata.json
│       ├── config.yaml
│       ├── metrics.jsonl
│       ├── env.txt
│       ├── summary.md
│       ├── logs/
│       └── artifacts/
│           ├── checkpoints/
│           ├── plots/
│           └── bad_cases.json
├── train/                                 # Training experiments group
│   ├── 20260427_b2c3d4e5_baseline/
│   └── 20260428_c3d4e5f6_finetune/
├── eval/                                  # Evaluation experiments group
│   └── 20260428_d4e5f6a7_benchmark/
└── ablation/                              # Ablation study group
    └── 20260429_e5f6a7b8_dropout_02/
```

### 2.2 Path Resolution Rules

| Operation | Old Path (v0.1.0) | New Path (v0.2.0) |
| --- | --- | --- |
| `init()` | `root/date_id_desc/` | `root/group/date_id_desc/` |
| `list()` | Scans `root/*/` | Scans `root/*/*/` |
| `get(id)` | Scans `root/*/` | Uses `index.json` or scans `root/*/*/` |
| `trash` | `root/.trash/` | `root/.trash/` (global) |

**Backwards Compatibility**: The root directory name remains configurable via `--path` / `EXMAN_PATH`. The internal structure changes, but the CLI surface is unchanged except for new flags.

### 2.3 Index Lifecycle

```python
def _update_index(exp: Experiment, operation: str) -> None:
    """Update the index cache after a mutating operation.

    Args:
        exp: The experiment that was created, moved, or removed.
        operation: One of "add", "move", "remove".
    """
```

The index file is protected by an atomic write pattern: write to `index.json.tmp`, then `os.rename()` to `index.json`. This prevents corruption from concurrent writes.

### 2.4 Auto-Rebuild Trigger

If `index.json` is missing, corrupt, or has a mismatched `version`, any operation that needs it triggers a full rebuild by scanning all group directories. This is a one-time cost paid on first access after a manual deletion or corruption event.

---

## 3. Command Logic & Edge Cases

### 3.1 New and Modified CLI Commands

#### `init --group GROUP`

```bash
kai-exman init -d "baseline training" -t "v1,resnet" --group train
```

- Creates the experiment in `root/train/`, not `root/default/`.
- Validates group name via `validate_group()`.
- Updates `index.json` with new group mapping.

#### `init --group GROUP`

```bash
kai-exman init -d "..." --group train
```

- Creates the experiment in `root/train/`, not `root/default/`.
- Validates group name via `validate_group()`.
- Updates `index.json` with new group mapping.

#### `list --tree`

```bash
kai-exman list --tree
kai-exman list --tree --group train
```

- Displays experiments in a tree view: groups as top-level nodes, experiments as children.
- `--group` filters to a single group; without it, all groups are shown.

#### `list --group GROUP`

```bash
kai-exman list --group train --tag Candidate
```

- Filters experiments by group and/or tag.
- Uses `index.json` for O(1) filtering when available.

#### `tags`

```bash
kai-exman tags              # List all tags across all experiments
kai-exman tags --group train # Tags only in the train group
```

- Computes the union of all tags from `index.json` or by scanning metadata.
- Optionally shows per-tag experiment counts.

#### `move EXP_ID --group NEW_GROUP`

```bash
kai-exman move a1b2c3d4 --group eval
```

- Physically moves the experiment directory to the new group.
- Updates `metadata.group` and rewrites `metadata.json`.
- Updates `index.json`.
- Validates that the target group exists or creates it if `--create-group` is passed.

#### `group`

```bash
kai-exman group --threshold 0.6
```

- Runs auto-clustering (Section 3.4) and prints suggested groupings.
- `--threshold` controls the Jaccard similarity cutoff (default: 0.5).
- Dry-run by default; use `--apply` to actually move experiments.
- `group -l` lists all groups with experiment counts.

### 3.2 Edge Case: Resume with Different Group

**Scenario**: User runs `kai-exman run --inherit <pid> --group eval` where `<pid>` is in group `train`.

| Case | Behavior |
| --- | --- |
| **Case A** (Logic-Clean, same hash) | Ignores `--group`. The existing experiment is reopened in its original group. A warning is emitted: `"Warning: --group ignored for Case A resume; experiment remains in 'train'."` |
| **Case B** (Logic-Dirty, new experiment) | Honors `--group`. The child experiment is created in `eval/`. The `parent_id` still points to the original `train/` experiment. No physical move of the parent occurs. |

Rationale: Case A is an identity-preserving operation. Moving the experiment would break its directory path and invalidate any external references (e.g., symlinks, notebook paths). Case B creates a new identity, so the new experiment can live anywhere.

### 3.3 Edge Case: Lineage Integrity (Deleted Parent)

**Scenario**: Experiment `child` has `parent_id = "parent_123"`, but `parent_123` has been moved to trash.

| Command | Behavior |
| --- | --- |
| `status child` | Displays `Parent: parent_123` with a `(trashed)` indicator. No error. |
| `list --tree` | Shows `child` under its group. The parent is omitted from the tree (it is in trash). |
| `resume child` | Case A/B detection uses the child's recorded `git_hash`, not the parent's. The parent is not consulted for git state. Resumption proceeds normally. |

The `parent_id` field is a **reference**, not a **foreign key**. Kai-Exman does not enforce referential integrity. A dangling `parent_id` is valid state; it simply means the ancestor is no longer discoverable through normal listing.

**Recovery**: If a trashed parent is restored (manual move from `.trash/`), lineage is automatically valid again because `parent_id` was never cleared.

### 3.4 Auto-Clustering Algorithm

**Goal**: Suggest groups for experiments based on the similarity of their configuration keys.

**Rationale**: Experiments that share many hyperparameter or configuration keys are likely part of the same study. Tag overlap can be coincidental; config key overlap is structural evidence of intent.

**Algorithm**: Jaccard Similarity over Config Key Sets.

```python
def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def suggest_group(experiment: Experiment, all_experiments: list[Experiment]) -> str | None:
    """Suggest a group for an experiment based on config key similarity.

    Returns the group of the most similar experiment if similarity >= threshold.
    Returns None if no experiment exceeds the threshold.
    """
    threshold = 0.5  # Configurable via [tool.kaiexman].cluster_threshold
    best_group = None
    best_score = 0.0
    target_keys = set(experiment.config.keys())

    for other in all_experiments:
        if other.metadata.exp_id == experiment.metadata.exp_id:
            continue
        other_keys = set(other.config.keys())
        score = jaccard_similarity(target_keys, other_keys)
        if score > best_score:
            best_score = score
            best_group = other.metadata.group

    return best_group if best_score >= threshold else None
```

| Parameter | Default | Description |
| --- | --- | --- |
| `cluster_threshold` | 0.5 | Minimum Jaccard similarity to recommend a group. |

**Weighted Variant** (optional enhancement):

Config key frequency in the corpus can be used to downweight common keys (e.g., `learning_rate`, `batch_size`) and upweight rare, discriminative ones:

```python
def weighted_jaccard(set_a: set[str], set_b: set[str], idf: dict[str, float]) -> float:
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    num = sum(idf.get(k, 1.0) for k in intersection)
    den = sum(idf.get(k, 1.0) for k in union)
    return num / den
```

Where `idf[k] = log(N / (1 + count(k)))`, N = total experiments.

**Scope**: Auto-clustering is a **suggestion engine**, not an automatic reorganization tool. It only runs when explicitly invoked via `group`.

---

## 4. User Workflow (Project-Z Example)

### 4.1 Scenario

A researcher is working on "Project-Z", a paper submission pipeline. The project has two phases: model training and model evaluation. The researcher wants:

1. Training experiments organized under group `train`.
2. Evaluation experiments organized under group `eval`.
3. Both phases tagged with `Candidate` for cross-phase comparison.
4. A tree view showing the full project structure.

### 4.2 Step-by-Step Workflow

#### Step 1: Initialize training baseline**

```bash
kai-exman init \
  --group train \
  --description "ResNet-50 baseline on ImageNet" \
  --tags "Candidate,baseline,resnet50"
```

Result: `/.exman/train/20260427_a1b2c3d4_baseline/`

#### Step 2: Run training (attempt 1)**

```bash
kai-exman run a1b2c3d4 -- python train.py --epochs 100
```

Status: Attempt 1 running. Global status: `running`.

#### Step 3: Resume after failure (Case A)**

Git hash unchanged, workspace clean.

```bash
kai-exman run a1b2c3d4 -- python train.py --epochs 100
```

Result: Attempt 2 appended. Status reset to `running`. Env var `KAI_EXMAN_ATTEMPT_COUNT=2`.

#### Step 4: Finish training**

```bash
kai-exman finish a1b2c3d4 -s "Training complete."
```

#### Step 5: Initialize evaluation (inherit from finished parent)**

Code changed (new eval script). Logic-Dirty.

```bash
kai-exman init -d "Evaluate baseline" --inherit a1b2c3d4 --group eval
kai-exman run b2c3d4e5 -- python eval.py --model best.pt
```

Result: New experiment `b2c3d4e5` in `/.exman/eval/`. `parent_ids = [a1b2c3d4]`. Checkpoints symlinked.

Tags inherited: `Candidate, baseline, resnet50`.

#### Step 6: Tag the eval experiment**

```bash
kai-exman tag b2c3d4e5 Candidate
```

(Idempotent; already inherited.)

#### Step 7: View tree**

```bash
kai-exman list --tree
```

Expected output:

```text
train/
  a1b2c3d4  ResNet-50 baseline on ImageNet  [success]  Candidate, baseline, resnet50
    Attempts: 1 (failed), 2 (success)
eval/
  -> b2c3d4e5  inherited from a1b2c3d4  [running]  Candidate, baseline, resnet50
```

#### Step 8: List by tag across groups**

```bash
kai-exman list --tag Candidate
```

Shows both `train/a1b2c3d4` and `eval/b2c3d4e5`.

#### Step 9: View all tags**

```bash
kai-exman tags
```

Expected output:

```text
Candidate     (2 experiments)
baseline      (2 experiments)
resnet50      (2 experiments)
```

#### Step 10: Cross-group comparison**

```bash
kai-exman list --tag Candidate --sort-by acc --order desc
```

Shows all `Candidate`-tagged experiments (both `train` and `eval`) sorted by accuracy, enabling direct comparison across phases.

### 4.3 Lineage Integrity Check

If `train/a1b2c3d4` is later moved to trash, `eval/b2c3d4e5` still displays:

```text
Parent: a1b2c3d4 (trashed)
```

The eval experiment remains fully functional. Resuming from `b2c3d4e5` uses its own `git_hash`, not the (unreachable) parent's.

---

## 5. UI/UX Design

### 5.1 Design Principles

1. **Git-like minimalism**: No borders, no gradients. Information density first.
2. **TTY-aware**: Rich colors for humans, plain text for pipes and agents.
3. **Three-dimensional cues**: Group (indentation/branching), Lineage (`->` prefix), Tag (magenta badges).

### 5.2 `list --tree` Mockup

#### TTY Mode (Rich Rendering)

```text
.exman/
├── train/
│   ├── a1b2c3d4  ResNet-50 baseline on ImageNet
│   │              Status: [32msuccess[0m    Tags: [35mCandidate[0m, [35mbaseline[0m, [35mresnet50[0m
│   │              Attempts: 2 (latest: success)
│   └── c3d4e5f6  Fine-tune with dropout 0.2
│                  Status: [34mrunning[0m    Tags: [35mCandidate[0m, [35mfine-tune[0m
├── eval/
│   └── -> b2c3d4e5  inherited from a1b2c3d4
│                  Status: [32msuccess[0m    Tags: [35mCandidate[0m
└── ablation/
    └── d4e5f6a7  Learning rate sweep
                   Status: [31mfailed[0m     Tags: [35mablation[0m, [35mlr-sweep[0m
```

#### Pipe Mode (Plain Text)

```text
train/
    a1b2c3d4  success  ResNet-50 baseline on ImageNet  [Candidate,baseline,resnet50]
    c3d4e5f6  running  Fine-tune with dropout 0.2      [Candidate,fine-tune]
eval/
    -> b2c3d4e5  success  inherited from a1b2c3d4  [Candidate]
ablation/
    d4e5f6a7  failed  Learning rate sweep  [ablation,lr-sweep]
```

**Key visual cues**:

| Cue | Meaning |
| --- | --- |
| `->` prefix | Experiment has a `parent_id` (Lineage dimension) |
| Branch indent | Physical group membership (Group dimension) |
| `[tag,tag]` | Tag badges (Tag dimension) |
| Color | Status: green=success, blue=running, red=failed |

### 5.3 `tags` Command Mockup

#### TTY Mode (tags)

```text
[1mTags across all groups[0m

  [35mCandidate[0m     12 experiments  ├── train (8)  ├── eval (4)
  [35mbaseline[0m       8 experiments  ├── train (5)  ├── eval (3)
  [35mresnet50[0m       5 experiments  └── train (5)
  [35mfine-tune[0m      3 experiments  └── train (3)
  [35mablation[0m       2 experiments  └── ablation (2)
  [35mlr-sweep[0m       2 experiments  └── ablation (2)
```

#### Pipe Mode (tags)

```text
Candidate    12  train:8,eval:4
baseline      8  train:5,eval:3
resnet50      5  train:5
fine-tune     3  train:3
ablation      2  ablation:2
lr-sweep      2  ablation:2
```

### 5.4 `status` Command (Updated)

```bash
kai-exman status b2c3d4e5
```

#### TTY Mode (status)

```text
[───────────────────────────────────────────────────────────────[│
│ Experiment: b2c3d4e5                              │
[═══════════════════════════════════════════════════════════════[│
│ Group:        eval                                 │
│ Parent:       a1b2c3d4                             │
│ Status:       [32msuccess[0m                              │
│ Git Hash:     7d3f9a2c...                          │
│ Tags:         [35mCandidate[0m, [35mbaseline[0m, [35mresnet50[0m      │
│ Description:  inherited from a1b2c3d4              │
[───────────────────────────────────────────────────────────────[│
```

New row added: **Group**.

### 5.5 Color Coding Additions

| Element | Color | Usage |
| --- | --- | --- |
| Group name | Cyan | Header in tree view |
| Tree branch | Dim white | `├──`, `└──` connectors |
| `->` indicator | Yellow | Same as experiment ID color |
| Tag count | Blue | Numeric counts in `tags` output |

---

## 6. Implementation Boundaries

### 6.1 In Scope

- `group` field in `Metadata` model with validation.
- Hierarchical directory layout: `root/group/date_id_desc/`.
- `index.json` cache with lazy updates and atomic writes.
- CLI additions: `--group`, `--tree`, `tag -l`, `move`, `group`.
- TTY and pipe-mode renderers for all new commands.
- Edge case handling for resume-with-group and deleted-parent lineage.
- Auto-clustering suggestion engine (config-key Jaccard similarity).

### 6.2 Out of Scope (Future Work)

- **Nested groups**: Groups are flat. `train/phase1/` is not supported.
- **Remote storage**: Index does not sync to S3, GCS, etc.
- **Concurrent write locking**: Atomic `index.json` writes suffice for single-machine use. Distributed locking is not implemented.
- **Graph visualization**: Lineage is linear (parent -> child). Full DAG visualization is not supported.
- **Tag aliases**: No mapping of `r50` -> `resnet50`.
- **Weighted Jaccard IDF**: The base Jaccard algorithm is in scope; the weighted IDF variant is documented but deferred to a future enhancement.

### 6.3 Migration Path

Existing experiments in a flat `outputs/` directory are treated as group `default`. On first run of v0.2.0, the migration path is:

1. If `outputs/` exists and contains experiment directories directly, create `outputs/default/`.
2. Move all existing experiment directories into `outputs/default/`.
3. Generate `index.json` from the migrated layout.
4. Print a one-time migration notice.

This is a single, idempotent, non-destructive operation.

---

## 7. Consistency Checklist

Before implementation begins, verify that the design satisfies these invariants:

| # | Invariant | Satisfied By |
| --- | --- | --- |
| 1 | Every experiment belongs to exactly one group. | `group` field in `Metadata`, validated at `init()`. |
| 2 | Group names are filesystem-safe and portable. | Lowercase alphanumeric + `_-` regex. Max 32 chars. |
| 3 | Experiment IDs are globally unique across groups. | UUID-based generation independent of group. |
| 4 | The index is a derived cache, not a source of truth. | Rebuildable from filesystem scan. Atomic writes. |
| 5 | Case A resume never changes an experiment's group. | `--group` is ignored with a warning. |
| 6 | Case B resume honors `--group`. | Child created in target group, parent untouched. |
| 7 | A deleted parent does not orphan its children functionally. | Children use their own `git_hash` for resumption. |
| 8 | Trash is global, not per-group. | Single `.trash/` at root. |
| 9 | Tag filtering works across groups. | `tag_index` in `index.json` maps tag -> global IDs. |
| 10 | Auto-clustering never moves experiments without explicit user approval. | `group` is dry-run by default. |

---

## 8. Code Consistency Pre-Check

This section audits the current v0.1.0 implementation and identifies the specific modules and methods that must be refactored to realize the Three-Dimensional Organization System.

### 8.1 Path Generation (`ExMan._folder_name` and `ExMan.init`)

**Current State**: `init()` computes `folder = self.root / self._folder_name(...)` and creates a flat directory.

**Required Changes**:

- `_folder_name()` remains unchanged; it builds the leaf directory name.
- `init()` must accept a `group: str = "default"` parameter.
- Path construction becomes: `folder = self.root / group / self._folder_name(...)`.
- The group directory must be created with `mkdir(parents=True)`.
- `Experiment.write_metadata()` must capture the group from `metadata.group` (already present in schema).

**Files**: `src/kaiexman/manager.py`, `src/kaiexman/experiment.py`

### 8.2 Discovery and Retrieval (`ExMan.list` and `ExMan.get`)

**Current State**: `list()` iterates `self.root.iterdir()` and checks for `metadata.json`. `get()` does a linear scan over `list()`.

**Required Changes**:

- `list()` must recurse into group subdirectories: scan `self.root / group /` for each group.
- `get()` should prefer `index.json` for O(1) lookup. Fall back to a full scan only if the index is missing.
- A new `rebuild_index()` method must scan all groups and write `index.json`.
- The `.trash` directory remains at `self.root / ".trash"` and is still excluded.

**Files**: `src/kaiexman/manager.py`

### 8.3 Resume Logic (`ExMan.resume`)

**Current State**: `resume()` does not know about groups. It creates child experiments via `self.init()` which uses the flat layout.

**Required Changes**:

- `resume()` must accept an optional `group` parameter.
- **Case A**: Ignore the `group` parameter. Re-open the existing experiment in place.
- **Case B**: Pass `group` (or default) to `self.init()`. The child is created in the target group.
- Environment variables (`KAI_EXMAN_PARENT_PATH`, `KAI_EXMAN_ATTEMPT_COUNT`) remain unchanged.

**Files**: `src/kaiexman/manager.py`, `src/kaiexman/cli.py`

### 8.4 CLI Surface (`cli.py`)

**Current State**: Commands `init`, `run`, `list`, `status`, `finish`, `tag`, `rm` have no group awareness.

**Required Changes**:

- Add `--group` option to `init` and `run`.
- Add `--tree` flag to `list`.
- Add `--group` filter to `list`.
- Add new command: `tags [--group]`.
- Add new command: `move EXP_ID --group NEW_GROUP [--create-group]`.
- Add new command: `group [--threshold] [--apply]`.
- Update `status` to render the `Group` row in metadata panels.
- Update `list` renderer to support tree indentation and the `->` lineage prefix.

**Files**: `src/kaiexman/cli.py`

### 8.5 Metadata Persistence (`Experiment.write_metadata`)

**Current State**: `write_metadata()` captures Git state and writes `metadata.json`. The schema currently has no `group` field.

**Required Changes**:

- Add `group: str = "default"` to the `Metadata` Pydantic model.
- No change to `write_metadata()` logic; it already serializes the full `Metadata` model.

**Files**: `src/kaiexman/models.py`

### 8.6 Trash System (`ExMan.remove` and `ExMan.clear_trash`)

**Current State**: Trash is a single `.trash/` directory under the root. The implementation already uses `self.root / ".trash"`.

**Required Changes**:

- None. The trash system is **global by design** and already correctly scoped to the root.
- `remove()` must update `index.json` to remove the entry.

**Files**: `src/kaiexman/manager.py`

### 8.7 Configuration System (`ConfigManager`)

**Current State**: `DEFAULTS` contains `critical_paths`, `ignore_paths`, `short_id_length`, `strict_mode`, `trash_max_count`, `trash_max_size_gb`.

**Required Changes**:

- Add `cluster_threshold: float = 0.5` to `DEFAULTS`.
- Users can override via `[tool.kaiexman]` in `pyproject.toml`.

**Files**: `src/kaiexman/config.py`

### 8.8 Validation Layer

**Current State**: `validate_tag()` exists in `experiment.py`.

**Required Changes**:

- Add `validate_group()` alongside `validate_tag()`.
- Enforce lowercase, alphanumeric, `_`, `-`, max 32 chars.
- Reject empty strings.

**Files**: `src/kaiexman/experiment.py`

### 8.9 Summary of Refactor Surface

| Module | Lines to Touch | Risk |
| --- | --- | --- |
| `models.py` | Low | Add `group` field to `Metadata`. |
| `experiment.py` | Low | Add `validate_group()`. |
| `config.py` | Low | Add `cluster_threshold` default. |
| `manager.py` | High | Path logic, discovery, index cache, resume, trash sync. |
| `cli.py` | High | New flags, new commands, renderers, TTY/pipe modes. |
| `tests/` | High | New tests for groups, index, resume-with-group, tree output. |

---

*End of Document. Awaiting approval before proceeding to implementation.*
