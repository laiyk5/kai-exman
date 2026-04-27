# Kai-Exman

A filesystem-based experiment management CLI for machine learning workflows,
inspired by Git. Kai-Exman treats the filesystem as its database, requiring
no external services while providing git-log-style experiment tracking,
structured metrics logging, and reproducibility snapshots. Deleted experiments
are moved to a trash folder with automatic capacity management to prevent
accidental data loss.

## Installation

```bash
pip install kaiexman
```

Or install from source:

```bash
git clone <repository-url>
cd kaiexman
pip install -e ".[test]"
```

## Quick Start

### Initialize a new experiment

```bash
kai-exman init --description "baseline training" --tags "baseline,v1" --group train
```

### Run a command inside an experiment context

```bash
# Fresh experiment
kai-exman run --description "training run" -- python train.py

# Resume an experiment (automatic Case A / Case B detection)
kai-exman run --resume <exp_id> -- python train.py
```

When resuming, Kai-Exman compares the current Git state against the parent experiment:

- **Case A (Retry)**: Same commit, clean workspace. Appends a new attempt to the existing experiment.
- **Case B (Evolution)**: Different commit or dirty workspace. Creates a new experiment with the old one as its parent.

### Track metrics and artifacts (Python API)

```python
from kaiexman import ExMan

exman = ExMan()
exp = exman.init(description="my experiment", group="train")

# Log metrics
exp.log_metrics(step=0, values={"loss": 1.5, "acc": 0.3})
exp.log_metrics(step=1, values={"loss": 0.8, "acc": 0.6})

# Save a checkpoint
exp.save_artifact("/tmp/best_model.pt", name="best_model.pt")

# Get best metrics seen so far
best = exp.compute_best_metrics()
# {"loss": {"max": 1.5, "min": 0.8}, "acc": {"max": 0.6, "min": 0.3}}

# Finish the experiment (status auto-determined from last attempt)
finished = exman.finish(exp.metadata.exp_id, notes="Solid baseline.")
```

### List and filter experiments

```bash
# Default log view
kai-exman list

# Compact one-line view
kai-exman list --oneline

# Lineage tree view (shows parent/child relationships)
kai-exman list --tree

# Filter by tag or group
kai-exman list --tag baseline --group train

# Sort by metric, creation time, or group
kai-exman list --sort-by acc --order desc
kai-exman list --sort created --order desc

# Show full 16-character IDs
kai-exman list --full-id
```

### Show experiment details

```bash
kai-exman show <exp_id>
kai-exman show --full-id <exp_id>
```

### Move experiments between groups

```bash
kai-exman move <exp_id> eval
```

### Tag or untag an experiment

```bash
kai-exman tag <exp_id> production
kai-exman tag <exp_id> production -d
```

### Remove an experiment (moved to trash for safety)

```bash
kai-exman rm <exp_id>
kai-exman rm --clear-trash  # permanently empty trash
```

### Finish an experiment and generate a summary

```bash
kai-exman finish <exp_id> --notes "Best run so far"
```

Status is determined automatically from the last attempt's exit code:

| Exit code | Status |
| --- | --- |
| `0` | `success` |
| Non-zero | `failed` |
| `None` (stopped) | `aborted` |

### Abort an experiment manually

```bash
kai-exman abort <exp_id> --notes "Stopped early due to NaN"
```

Use `abort` when an experiment was stopped manually or did not complete
normally. It marks the last attempt as aborted and seals the record.

## Motivation

Machine learning projects generate hundreds of experiments. Ad-hoc tracking
spreadsheets and manual note-taking break down at scale. Kai-Exman provides
a rigorous, reproducible, and agent-friendly system where every experiment
is a self-contained directory with metadata, configuration, metrics, and
artifacts.

The design philosophy is **Rigorous Flexibility**: unyielding standards for
correctness and clarity, flexible enough to adapt to real-world needs.

## Insights

### Experiment Design

Experiments must be designed before they are run.

- **Training experiments** should split data into train / validation / test.
The test set must never be used for tuning. Use the validation set to guide
model design and hyperparameters. To avoid overfitting the validation set,
use K-fold cross-validation.
- **Ablation studies** should be planned in advance. Design experiments to
extract knowledge across runs, isolating which design choices actually matter.

Experiments are rarely successful on the first attempt. Failed experiments are
valuable --- they provide the signal needed to improve the next iteration.

### Experiment Recording

Experiments are multi-stage, and some stages are resource-intensive (time,
compute, materials). High-cost stages need periodic checkpointing for both
analysis and resumption. Checkpoints must be capable of restoring full
experiment state.

Record as much structured data as possible: logs, module inputs and outputs,
and intermediate artifacts. Structured data is ideal; semi-structured logs are
the minimum acceptable form.

Every experiment should capture:

- Environment state (pip freeze, Git commit hash)
- Experimental settings (hyperparameters, data version)
- Timing and resource usage
- A structured experiment record sheet

Experiments must be **reproducible**:

- Code should be committed before running. Each experiment records the current
  Git commit hash and checks for uncommitted changes.
- Data should be under version control. Record dataset MD5 hashes and version
  numbers to prevent data corruption from breaking reproducibility.

### Experiment Analysis

- **Bad Case Report**: Every experiment should produce a Bad Case Report
  exporting the worst-performing samples. Understanding why the model fails
  informs the next design iteration.
- **Significance Testing**: When a promising method is found, run multiple
  seeds, record mean and standard deviation. A single good run may be noise.

### Experiment Monitoring

Experiments require active monitoring. A run heading in the wrong direction
should be killed automatically rather than consuming resources indefinitely.
Monitor structured output data programmatically, trigger alerts on anomalous
patterns, and invoke predefined handler routines to notify humans or agents.

| Layer | Content | Storage Form |
| --- | --- | --- |
| **Metadata** | Experiment ID, timestamp, Git commit, user, description | `metadata.json` |
| **Config** | Learning rate, batch size, model architecture, seed | `config.yaml` |
| **Metrics** | Per-step loss, accuracy, latency, memory usage | `metrics.jsonl` |
| **Logs** | Module I/O samples, error traces, feature distributions | `.log` files |
| **Artifacts** | Best model, checkpoints, visualizations | `artifacts/` directory |

### Multi-Experiment Management

A single project contains many experiment types: baselines, latency benchmarks,
ablation studies, and primary experiments. Each experiment needs a unique,
unambiguous reference for rapid lookup.

At scale, semantic tags are essential. A naming convention such as
`[project]-[variant]-[hyperparams]-[date]-[description]` allows a researcher to
understand an experiment's purpose at a glance.

After every experiment, a **mandatory post-mortem summary** is required:
record results, insights, and concrete next-step recommendations.

## Documentation

- **[CONTRIBUTING.md](CONTRIBUTING.md)** -- Engineering workflow, testing
  standards, commit conventions, and governance.
- **[docs/design/specs.md](docs/design/specs.md)** -- Technical architecture:
  ID system, tag format, metadata schema, UI design rules, and API reference.
