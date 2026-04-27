Design Philosophy
=================

Core Principles
---------------

**Filesystem as Database**
   All experiment data is stored in structured directories. No external database is required.

**Agent-First**
   Designed for LLM Agents to read, analyze, and trigger experiments. Every output is human-readable and machine-parseable.

**Strict Reproducibility**
   No experiment runs without a clean Git state and logged Data version. The commit hash and dirty flag are captured automatically.

Storage Architecture
--------------------

Root path: ``./outputs`` (override via ``EXMAN_PATH`` or ``--path``).

Each experiment is a folder::

    {EXMAN_PATH}/{date}_{id}_{tags_or_desc}/

Contents:

- ``metadata.json`` — Structured info (ID, start_time, git_commit, data_hash, status).
- ``config.yaml`` — Model hyperparameters and environment settings.
- ``metrics.jsonl`` — Append-only time-series data (one JSON object per line).
- ``env.txt`` — Snapshot of installed Python packages.
- ``code.patch`` — Git diff patch (only present if workspace was dirty at init).
- ``logs/`` — Plain text ``.log`` files for debugging.
- ``artifacts/`` — Subfolders for ``checkpoints/``, ``plots/``, and ``bad_cases.json``.
- ``summary.md`` — Final post-mortem report and next-step actions.

Experiment Lifecycle
--------------------

1. **Design** — Define hypothesis, config, and data version before running.
2. **Init** — Create folder, validate git state, write metadata and env snapshot.
3. **Track** — Log metrics (thread-safe), save artifacts, record bad cases.
4. **Finish** — Close status, compute best metrics, generate ``summary.md``.
5. **Review** — Fill in notes, insights, and next actions in the summary.

Bad Case Analysis
-----------------

Every experiment should produce a structured bad-case report. Use ``log_bad_case()`` to record mispredictions with input, prediction, ground truth, and optional metadata.

Data Versioning
---------------

Pass a ``data_version`` string (e.g., DVC hash or MD5 checksum) during ``init()`` to bind the experiment to a specific dataset state. This prevents silent data drift from breaking reproducibility.

Alternatively, use ``--data-path PATH`` on ``run`` or ``init``. Kai-Exman automatically computes a deterministic BLAKE2b hash of the file or directory and stores it in ``metadata.data_hash``. This requires no manual bookkeeping and catches any data change, including renames.

Environment Snapshots
---------------------

On initialization, ``kaiexman`` captures the current Python environment via ``pip list --format=freeze`` into ``env.txt``. This allows exact environment recreation for any historical experiment.
