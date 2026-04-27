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

Initialize a new experiment:

```bash
kai-exman init --description "baseline training" --tags "baseline,v1"
```

Log metrics during training (via Python API):

```python
from kaiexman import ExMan

exman = ExMan()
exp = exman.init(description="my experiment")
exp.log_metrics(step=0, values={"loss": 1.5, "acc": 0.3})
exp.log_metrics(step=1, values={"loss": 0.8, "acc": 0.6})
```

List experiments with git-log-style output:

```bash
kai-exman list
kai-exman list --tag baseline --sort-by acc
```

Show a specific experiment:

```bash
kai-exman show <exp_id>
```

Tag or untag an experiment:

```bash
kai-exman tag <exp_id> production
kai-exman tag <exp_id> production -d
```

Remove an experiment (moved to trash for safety):

```bash
kai-exman rm <exp_id>
kai-exman rm --clear-trash  # permanently empty trash
```

Finish an experiment and generate a summary:

```bash
kai-exman finish <exp_id> --status success --notes "Best run so far"
```

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
