Usage
=====

Python API
----------

Initialize an experiment manager and start tracking::

    from kaiexman import ExMan

    exman = ExMan()  # Uses ./outputs or EXMAN_PATH env var

    exp = exman.init(
        description="Baseline LLaMA3 run",
        tags=["baseline", "llama3"],
        config={"lr": 0.001, "batch_size": 32},
        data_version="md5:abc123def456",
        group="train",
    )

    # Log metrics during training
    exp.log_metrics(step=0, values={"loss": 1.2, "acc": 0.5})
    exp.log_metrics(step=1, values={"loss": 0.8, "acc": 0.7})

    # Save artifacts (checkpoints, plots, etc.)
    exp.save_artifact("/tmp/best_model.pt", name="best_model.pt")

    # Retrieve best metrics seen so far
    best = exp.compute_best_metrics()
    # {"loss": {"max": 1.2, "min": 0.8}, "acc": {"max": 0.7, "min": 0.5}}

    # Log bad cases for analysis
    exp.log_bad_case(
        case_id="img_42",
        input_data={"features": [1.0, 2.0]},
        prediction="cat",
        ground_truth="dog",
        extra={"confidence": 0.99},
    )

    # Finish the experiment (status auto-determined from last attempt)
    finished = exman.finish(
        exp_id=exp.metadata.exp_id,
        notes="Good convergence."
    )

Resume and lineage::

    # Case A: same commit, clean workspace -> append attempt to existing experiment
    exp, is_new, attempt_num = exman.resume(exp.metadata.exp_id)

    # Case B: dirty workspace or different commit -> new experiment with parent link
    # (automatic when git state diverges)

    # Move an experiment to a different group
    moved = exman.move(exp.metadata.exp_id, "eval")

    # List all experiments
    experiments = exman.list()

    # Filter by group or tag
    train_exps = exman.list(group="train")

    # Get a specific experiment by full or partial ID
    retrieved = exman.get(exp.metadata.exp_id)

    # Remove to trash (with automatic capacity management)
    exman.remove(exp.metadata.exp_id)

CLI
---

Global options::

    kai-exman --path ./outputs --strict <command>

Initialize a new experiment::

    kai-exman init --description "Baseline run" --tags "baseline,llama3" --config config.yaml --group train

Run a command inside an experiment context::

    # Fresh experiment
    kai-exman run --description "training run" -- python train.py

    # Resume an experiment (automatic Case A / Case B detection)
    kai-exman run --resume <exp_id> -- python train.py

List experiments::

    # Default log view
    kai-exman list

    # Compact one-line view
    kai-exman list --oneline

    # Lineage tree view (shows parent/child relationships)
    kai-exman list --tree

    # Filter by tag or group
    kai-exman list --tag baseline --group train

    # Sort by metric, creation time, group, or ID
    kai-exman list --sort-by acc --order desc
    kai-exman list --sort created --order desc

    # Show full 16-character IDs
    kai-exman list --full-id

Show experiment details::

    kai-exman show <exp_id>
    kai-exman show --full-id <exp_id>

Move an experiment to a different group::

    kai-exman move <exp_id> eval

Tag or untag an experiment::

    kai-exman tag <exp_id> production
    kai-exman tag <exp_id> production --delete

List all tags::

    kai-exman tags

Finish an experiment and generate summary.md::

    kai-exman finish <exp_id> --notes "Best run so far"

Status is auto-determined from the last attempt's exit code:

- ``0`` -> ``success``
- Non-zero -> ``failed``
- ``None`` (stopped) -> ``aborted``

Abort an experiment manually::

    kai-exman abort <exp_id> --notes "Stopped early due to NaN"

Use ``abort`` when an experiment was stopped manually or did not complete
normally. It marks the last attempt as aborted and seals the record.

Remove an experiment (moved to trash for safety)::

    kai-exman rm <exp_id>
    kai-exman rm --clear-trash  # permanently empty trash

Suggest group assignments based on config similarity::

    kai-exman suggest-groups
