# Kai-Exman

[![codecov](https://codecov.io/gh/laiyk5/kai-exman/branch/main/graph/badge.svg)](https://codecov.io/gh/laiyk5/kai-exman)
[![Documentation Status](https://readthedocs.org/projects/kai-exman/badge/?version=latest)](https://kai-exman.readthedocs.io/en/latest/?badge=latest)

A filesystem-based experiment management CLI for machine learning workflows,
inspired by Git. Kai-Exman treats the filesystem as its database, requiring
no external services while providing git-log-style experiment tracking,
structured metrics logging, and reproducibility snapshots.

**Design philosophy**: *Rigorous Flexibility* — unyielding standards for
correctness and clarity, flexible enough to adapt to real-world needs.

## Installation

```bash
pip install kaiexman
```

Or from source:

```bash
git clone <repository-url>
cd kaiexman
pip install -e ".[test]"
```

## Quick Start

Create a draft experiment (description is mandatory in non-interactive mode):

```bash
kai-exman init -d "baseline training" -t "baseline,v1" --group train
```

Execute a command on the experiment:

```bash
kai-exman run --id <exp_id> -- python train.py
```

List experiments:

```bash
kai-exman list
kai-exman list --tree       # lineage view
kai-exman list --oneline    # compact
```

Seal the experiment with a conclusion:

```bash
kai-exman finish --id <exp_id> -s "Converged to 95% accuracy"
```

Create a child that inherits from a finished parent:

```bash
kai-exman init -d "tune LR" --inherit <parent_id> --group train
```

## Python API

```python
from kaiexman import ExMan

exman = ExMan()

# Create draft
exp = exman.init(description="baseline", group="train")

# Execute
exp.run(["python", "train.py"])

# Log metrics
exp.log_metrics(step=0, values={"loss": 1.2, "acc": 0.5})

# Finish
exp.finish(summary="Converged cleanly.")
```

## Documentation

- **[Usage Guide](docs/source/usage.rst)** — Full CLI and Python API reference.
- **[Design Docs](docs/source/design/)** — Architecture, lifecycle, and specifications.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — Engineering workflow and testing standards.

Build the docs locally:

```bash
cd docs
make html
```

Then open `build/html/index.html`.
