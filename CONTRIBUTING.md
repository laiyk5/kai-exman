# Contributing to Kai-Exman

Thank you for your interest in making Kai-Exman more rigorous. This document defines our engineering standards. We follow a philosophy of **Rigorous Flexibility**: unyielding standards for correctness and clarity, flexible enough to adapt to real-world needs.

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

## 3. Rigorous Testing

### No Temporary Tests
Do not rely on ad-hoc scripts like `tmp_test.py` for final verification.

### Pytest Assets
Every feature or bug fix must be accompanied by a formal test case in the `tests/` directory.

### CLI Testing
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

## 4. UI & Aesthetics (The Git Soul)

### Design Philosophy
Follow Git's minimalist and industrial aesthetic. No unnecessary borders, no flashy gradients. Information density and clarity come first.

### Adapting to the User
Always check `sys.stdout.isatty()`.

- **For Humans (TTY)**: Use `rich` for colors, panels, and tables. Use a pager (`less -R`) for long output.
- **For Agents / Pipes**: Provide clean, plain text without ANSI codes or decorative framing.

### Layout Standards
- Use 4-space indentations for log-style multi-line output.
- Use clear, color-coded headers (e.g., green for success, red for failure, blue for running).
- Maintain consistent spacing: one blank line between entries in list views.

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

## 6. Decision Hierarchy

1. The Project Director (you) has the final say on all decisions.
2. The Lead Engineer (Claude) is responsible for proposing the most rigorous implementation and upholding these standards.
3. When the Director explicitly overrides a standard, the override stands, but the Engineer should document the rationale if the deviation introduces technical debt.

---

## Getting Started

1. Clone the repository.
2. Install dependencies: `uv sync` or `pip install -e ".[test]"`.
3. Run tests: `pytest`.
4. Create your feature branch.
5. Follow the standards above.
6. Open a pull request.
