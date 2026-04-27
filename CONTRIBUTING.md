# Contributing to Kai-Exman

Thank you for your interest in making Kai-Exman more rigorous. This document defines our engineering workflow. For technical architecture and system specifications, see [docs/source/design/specs.md](docs/source/design/specs.md).

---

## 1. Language & Identity

- **Language**: All code, docstrings, terminal outputs, comments, and Git commits must be in English.
- **Identity**: The tool is **Kai-Exman**.
  - Package name: `kaiexman`
  - CLI entry point: `kai-exman`
  - Never use abbreviations like `exman` in user-facing strings.

---

## 2. The Sandbox Workflow

- **`scratch/` Directory**: Use this folder for temporary scripts, API spikes, quick verifications, or any throwaway code.
- **Git Policy**: The `scratch/` directory is ignored by Git. Never commit files from this folder.
- **Cleanup**: Before completing any task, delete any temporary files created in the root (`/`) or `src/` directories. Only committed, intentional files should remain.

---

## 3. Environment Setup

Install dependencies with `uv`:

```bash
uv sync
```

Or with pip:

```bash
pip install -e ".[test]"
```

---

## 4. Rigorous Testing

### No Temporary Tests

Do not rely on ad-hoc scripts like `tmp_test.py` for final verification.

### Pytest Assets

Every feature or bug fix must be accompanied by a formal test case in the `tests/` directory.

### Docstrings

No PR or feature will be accepted without complete Google-style docstrings.

Every module must have a top-level description. Every class must document its purpose and attributes. Every function and method must document its `Args`, `Returns`, and potential `Raises`.

### Type Safety

All source code must pass `mypy --strict src/`.

When adding a new third-party dependency, you must also add the corresponding type stubs package (e.g., `types-PyYAML` for `pyyaml`) to `[project.optional-dependencies]` test if one exists on PyPI.

### Dependency Consistency

`deptry` guards the dependency list. It checks for:

- **Missing dependencies**: Imports used in code but not declared in `pyproject.toml`.
- **Unused dependencies**: Packages declared in `pyproject.toml` but not imported in the codebase.
- **Transitive dependencies**: Using a package that is only available because it is a dependency of another dependency.

When adding a new runtime dependency, declare it in `[project.dependencies]`. When adding a development or testing tool, declare it in the appropriate optional dependency group (`test`, `dev`, or `docs`).

### Linting and Formatting

All code must pass `ruff check` and `ruff format --check`. Ruff enforces Pyflakes (F), Pycodestyle (E, W), isort (I), Bugbear (B), and Pyupgrade (UP) rules with a line length of 88 characters.

Run `ruff check --fix .` and `ruff format .` before committing to ensure compliance.

For CLI-related logic, use `click.testing.CliRunner`. Example:

```python
from click.testing import CliRunner
from kaiexman.cli import cli

def test_list_empty():
    runner = CliRunner()
    result = runner.invoke(cli, ["--path", "/tmp/empty", "list"])
    assert result.exit_code == 0
    assert "No experiments found" in result.output
```

### Verification

A task is only considered **Done** when `pytest` passes at 100%.

---

## 5. Commit Standards

### Atomic Commits

Small, functional commits are preferred over giant "update everything" blobs. Each commit should represent a single logical change.

### Conventional Commits

Use the following format:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**

- `feat`: A new feature
- `fix`: A bug fix
- `style`: Code style changes (formatting, missing semi colons, etc.)
- `refactor`: A code change that neither fixes a bug nor adds a feature
- `test`: Adding or correcting tests
- `docs`: Documentation only changes
- `chore`: Changes to the build process or auxiliary tools

**Examples:**

```
feat: add centralized EXP_ID prefix resolver

test: add CLI tests for ambiguous prefix handling

fix: skip NaN values when computing best metrics
```

---

## 6. Governance & Decision Making

### Guiding Principles

All decisions should align with the project's core philosophies:

- **Rigor**: Correctness, reproducibility, and robust error handling are non-negotiable.
- **Aesthetics**: The UI must remain minimalist, industrial, and Git-like. Clarity trumps decoration.
- **Agent-friendliness**: The CLI must produce clean, parseable output when piped or redirected.

### Evidence-Based Decisions

Technical choices should be grounded in evidence rather than preference. When proposing a change:

1. Articulate the problem clearly.
2. Present the options with trade-offs.
3. Default to the most rigorous option that satisfies the requirement.

### The Project Lead

The Project Lead serves as the final arbiter for all technical conflicts and scope decisions. Their role is to:

- Resolve disagreements on architecture, dependencies, or design direction.
- Approve or reject feature proposals based on alignment with project goals.
- Override standards when business or usability needs demand it.

When a standard is overridden, the override is binding, but the rationale must be documented.

### Documenting Technical Debt

Intentional deviations from standards, shortcuts, or known imperfections must be documented as technical debt. Use inline `TODO` or `FIXME` comments for localized issues, and open a tracking issue for systemic debt. This ensures future contributors understand the context and can address it when priorities allow.

---

## 7. Documentation Policy

### Design First

Kai-Exman follows a **design-first** principle for all core features. Before any implementation code is written, a formal Technical Design Document (TDD) must be submitted, reviewed, and approved.

- **Location**: All design documents live under `docs/source/design/`.
- **Scope**: Any feature that introduces a new CLI command, modifies the metadata schema, changes the storage layout, or affects the experiment lifecycle requires a TDD.
- **Process**:
  1. Write the design document in the appropriate format.
  2. Submit it for review in a dedicated documentation PR or as the first commit of a feature branch.
  3. Implementation begins only after the design is approved by the Project Lead.

### Document Formats

We use two formats, chosen by the nature of the content:

| Format | Extension | Purpose | Parser |
| --- | --- | --- | --- |
| **reStructuredText** | `.rst` | API reference, structural documents, Sphinx toctrees | Native Sphinx |
| **MyST Markdown** | `.md` | Design rationale, user workflows, guiding principles | `myst_parser` |

- Use **`.rst`** for autodoc-generated API pages, index files, and any document that relies heavily on Sphinx directives.
- Use **`.md` (MyST)** for design specifications, philosophical documents, and workflow guides. MyST allows full Sphinx cross-referencing while maintaining the readability of Markdown.

### Directory Layout

```text
docs/source/
├── conf.py                 # Sphinx configuration
├── index.rst               # Master toctree
├── api.rst                 # API reference (.rst)
├── usage.rst               # User guide (.rst)
└── design/
    ├── philosophy.rst      # Core design principles (.rst)
    ├── specs.md            # Technical specifications (.md)
    └── organization.md     # Feature design documents (.md)
```

- The `design/` directory is the single source of truth for architectural decisions.
- Cross-references between `.rst` and `.md` files are fully supported via `myst_parser`.
- All documents must build cleanly with `make html` — zero warnings.

---

## 8. Technical Reference

For detailed system specifications, including the ID system, tag format, metadata schema, and UI design rules, see:

- **[docs/source/design/specs.md](docs/source/design/specs.md)** -- Architectural decisions and technical specifications.

---

## Getting Started

1. Clone the repository.
2. Install dependencies: `uv sync` or `pip install -e ".[test]"`.
3. Run tests: `pytest`.
4. Create your feature branch.
5. Follow the standards above.
6. Open a pull request.
