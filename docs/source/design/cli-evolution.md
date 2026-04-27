# CLI Evolution: Explicit Retry/Inherit + Default Experiment

## 1. Explicit Retry vs. Inherit

### Problem

The current `--resume` flag auto-detects Case A (retry) vs. Case B (inherit). This is convenient but opaque: the user does not declare their intent, and the system silently switches modes based on git state.

### Decision

Replace `--resume` with two mutually exclusive flags:

| Flag | Semantics | Required Parent State |
|------|-----------|----------------------|
| `--retry <id>` | Explicit Case A: append attempt to same experiment. | `running` |
| `--inherit <pid>` | Explicit Case B: create child from finished parent. | `finished` |

A standalone `retry <id>` command remains as a shorthand for `run --retry`.

Auto-detection is removed. The user must state their intent. This prevents surprises where a dirty workspace silently creates a new experiment chain when the user meant to retry.

### Manager API

```python
def resume(
    self,
    exp_id: str,
    ...,
    mode: str = "auto",  # "auto" | "retry" | "inherit"
) -> Tuple[Experiment, bool, int]:
```

- `mode="retry"`: Forces Case A. Raises if parent is not `running`.
- `mode="inherit"`: Forces Case B. Raises if parent is not `finished` or is `aborted`.
- `mode="auto"`: Preserved for backward compatibility of the Python API.

### Error Messages

| User Action | Error |
|-------------|-------|
| `run --retry <finished_id>` | "Experiment is finished. Use `run --inherit` to create a child." |
| `run --inherit <running_id>` | "Experiment is still running. Use `run --retry` to append an attempt." |
| `run --inherit <aborted_id>` | "Aborted experiments cannot be inherited." |

---

## 2. Default Experiment

### Problem

Every command that targets a specific experiment requires an ID argument. During active work, the user typically focuses on one experiment for many consecutive operations (run, finish, show, tag, move, rm). Typing the ID every time is friction.

### Decision

Introduce a **default experiment** concept, persisted per experiments root.

```bash
kai-exman use <exp_id>     # Set the default experiment for this root
kai-exman finish -s "..."  # Operates on the default experiment
kai-exman abort            # Operates on the default experiment
kai-exman show             # Displays the default experiment
kai-exman tag baseline     # Tags the default experiment
kai-exman move --group eval # Moves the default experiment
kai-exman rm               # Moves the default experiment to trash
```

### Storage

A `.current` file in the experiments root:

```
outputs/
├── .current          # Contains the default experiment ID
├── index.json
└── ...
```

The file stores the **full 16-character ID**, not a prefix. This eliminates ambiguity.

### Resolution Order

When a command accepts an `EXP_ID` argument:

1. If provided on the CLI → resolve that ID.
2. If omitted → read `.current`.
   - If `.current` exists and the ID is valid → use it.
   - If `.current` missing or the ID is invalid → raise: "No default experiment set. Use 'kai-exman use <id>' or provide an EXP_ID."

### Scope

The default experiment is scoped to the experiments root (`--path` / `EXMAN_PATH`). Changing `--path` changes which `.current` file is consulted. There is no global default across different roots.

### Commands Affected

| Command | EXP_ID becomes optional? | Notes |
|---------|--------------------------|-------|
| `finish` | Yes | — |
| `abort` | Yes | — |
| `show` | Yes | — |
| `tag` | Yes | Accepts `TAG_NAME` (default exp) or `EXP_ID TAG_NAME`. |
| `move` | Yes | `--group` is always required. |
| `rm` | Yes | `--clear-trash` still takes precedence. |
| `run --retry` | No | Click option values cannot be omitted. |
| `run --inherit` | No | Click option values cannot be omitted. |
| `retry` | No | Positional `EXP_ID` is required before `nargs=-1` command. |

### New Command: `use`

```bash
kai-exman use <exp_id>
```

Writes the resolved experiment ID to `.current`. Validates that the experiment exists before setting.

```
$ kai-exman use a1b2c3d4
Default experiment set to a1b2c3d4.
```

---

## 3. Acceptance Criteria

1. `run --retry <id> -- cmd` succeeds only if the experiment is `running`.
2. `run --inherit <pid> -d "..." -- cmd` succeeds only if the parent is `finished`.
3. `retry <id> -- cmd` is equivalent to `run --retry <id> -- cmd`.
4. `kai-exman use <id>` writes `.current` and validates the ID.
5. `kai-exman finish -s "..."` (no ID) uses the default experiment.
6. Commands with an invalid/missing default raise a clear error.
7. All changes pass `pytest`, `mypy --strict src/`, `ruff check`.
