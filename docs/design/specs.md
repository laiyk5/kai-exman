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

Always check `sys.stdout.isatty()`:

- **For Humans (TTY)**: Use `rich` for colors, panels, and tables. Pipe long output through a pager (`less -R`).
- **For Agents / Pipes**: Provide clean, plain text without ANSI codes or decorative framing.

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

Where `<safe_tags_or_description>` is sanitized to alphanumeric, underscore, and hyphen characters only.

### Discovery

`ExMan.list()` scans the root directory for subdirectories containing `metadata.json`. Each valid directory is loaded into an `Experiment` instance.
