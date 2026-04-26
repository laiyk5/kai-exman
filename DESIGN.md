# Kai-Exman Technical Design

## 1. Core Philosophy
- **Filesystem as Database**: All experiment data is stored in structured directories.
- **Agent-First**: Designed for LLM Agents to read, analyze, and trigger experiments.
- **Strict Reproducibility**: No experiment runs without a clean Git state and logged Data version.

## 2. Storage Architecture
### Root Path
- Default: `./outputs`
- Override: Environment variable `EXMAN_PATH` or CLI `--path` flag.

### Directory Structure (The Schema)
Each experiment is a folder: `{EXMAN_PATH}/{date}_{id}_{tags_or_desc}/`
Inside each folder:
- `metadata.json`: Structured info (ID, start_time, git_commit, dvc_hash, status).
- `config.yaml`: Model hyperparameters and environment settings.
- `metrics.jsonl`: Append-only time-series data (one JSON object per line).
- `logs/`: Plain text `.log` files for human/agent debugging.
- `artifacts/`: Subfolders for `checkpoints/`, `plots/`, and `bad_cases/`.
- `summary.md`: Final post-mortem report and next-step actions.

## 3. Data Schema (Pydantic Models)
- **Metadata**: 
    - `exp_id`: UUID or sequential ID.
    - `timestamp`: ISO format.
    - `git_hash`: Current commit ID.
    - `tags`: List of semantic strings.
    - `data_version`: MD5 or DVC hash.
- **Metrics**: 
    - `step`: int.
    - `values`: dict of floats.
    - `timestamp`: epoch float.

## 4. Key Components & Skill Set
The tool provides a Python API and CLI that maps to Agent Skills:

### A. Lifecycle Management
- `init(description, tags, config)`: Creates folder, validates git state, writes metadata.
- `update_status(status)`: Transitions from `running` to `success`, `failed`, or `aborted`.

### B. Tracking
- `log_metrics(step, metrics_dict)`: Thread-safe append to `metrics.jsonl`.
- `save_artifact(source_path, name)`: Moves/copies files to the `artifacts/` folder.

### C. Retrieval (The "Search Engine")
- `list(filter_criteria)`: Scan folders and parse `metadata.json` for rapid filtering.
- `get_best(metric_name, mode="max")`: Scans metrics to find the SOTA experiment.

### D. Safety & Monitoring
- `watchdog()`: A background process that checks `metrics.jsonl` and triggers `kill` if `NaN` or logic error is detected.

## 5. CLI Interface
- `kaiexman init --tags "baseline,llama3" --config config.yaml`
- `kaiexman list --last 24h`
- `kaiexman summary <exp_id>`