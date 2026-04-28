Usage
=====

Python API
----------

Initialize an experiment manager and start tracking::

    from kaiexman import ExMan

    exman = ExMan()  # Uses ./outputs or EXMAN_PATH env var

    # 1. Create a draft experiment
    exp = exman.init(
        description="Baseline LLaMA3 run",
        tags=["baseline", "llama3"],
        config={"lr": 0.001, "batch_size": 32},
        data_version="md5:abc123def456",
        group="train",
    )

    # 2. Execute on the experiment
    exp.run(["python", "train.py"])

    # Or use ExMan directly
    exman.run(exp.metadata.exp_id, ["python", "train.py"])

    # 3. Log metrics during training
    exp.log_metrics(step=0, values={"loss": 1.2, "acc": 0.5})
    exp.log_metrics(step=1, values={"loss": 0.8, "acc": 0.7})

    # 4. Save artifacts (checkpoints, plots, etc.)
    exp.save_artifact("/tmp/best_model.pt", name="best_model.pt")

    # 5. Retrieve best metrics seen so far
    best = exp.compute_best_metrics()
    # {"loss": {"max": 1.2, "min": 0.8}, "acc": {"max": 0.7, "min": 0.5}}

    # 6. Log bad cases for analysis
    exp.log_bad_case(
        case_id="img_42",
        input_data={"features": [1.0, 2.0]},
        prediction="cat",
        ground_truth="dog",
        extra={"confidence": 0.99},
    )

    # 7. Finish the experiment (status auto-determined from last attempt)
    exp.finish(summary="Reached target accuracy; next step LR sweep.")

Inheritance and retry::

    # Retry: append a new attempt to the same running experiment
    exp.run(["python", "train.py"], reason="retry after OOM")

    # Inherit: create a child from a finished parent
    child = exman.init(
        description="Tune learning rate",
        parent_ids=[exp.metadata.exp_id],
        group="train",
    )
    child.run(["python", "train.py", "--lr", "0.01"])
    child.finish(summary="Best LR is 0.01.")

    # Multi-parent inheritance
    ensemble = exman.init(
        description="Ensemble eval",
        parent_ids=[model_a.metadata.exp_id, model_b.metadata.exp_id],
        group="eval",
    )

Organization::

    # Move an experiment to a different group
    exman.move(exp.metadata.exp_id, "eval")

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

Create a draft experiment (``--description`` is mandatory in non-TTY)::

    kai-exman init -d "Baseline run" -t "baseline,llama3" -c config.yaml --group train

Create a child from finished parent(s)::

    kai-exman init -d "Tune LR after refactor" --inherit <exp_id> --group train

    # Multi-parent inheritance
    kai-exman init -d "Ensemble eval" --inherit <id_a> --inherit <id_b> --group eval

Execute a command on an existing experiment::

    # Run on draft (creates attempt 1)
    kai-exman run --id <exp_id> -- python train.py

    # Retry on running experiment (appends attempt N)
    kai-exman run --id <exp_id> --reason "retry after OOM" -- python train.py

    # Uses default experiment if ID omitted
    kai-exman run -- python train.py

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

    kai-exman status --id <exp_id>
    kai-exman status --id <exp_id> --full-id

Set the default experiment::

    kai-exman use <exp_id>

Move an experiment to a different group::

    kai-exman move --id <exp_id> --group eval

Tag or untag an experiment::

    kai-exman tag production --id <exp_id>
    kai-exman tag production --delete --id <exp_id>

List all tags::

    kai-exman tag -l

Group management::

    # List all groups
    kai-exman group -l

    # Suggest group assignments
    kai-exman group

    # Apply suggested moves
    kai-exman group --apply

Finish an experiment and generate summary.md (``--summary`` is mandatory)::

    kai-exman finish --id <exp_id> -s "Best run so far" -n "Observed 2% gain"

Status is auto-determined from the last attempt's exit code:

- ``0`` -> ``success``
- Non-zero -> ``failed``
- ``None`` (stopped) -> ``aborted``

Abort an experiment manually (no summary required)::

    kai-exman abort --id <exp_id>

Use ``abort`` when an experiment was stopped manually or did not complete
normally. It marks the last attempt as aborted and seals the record.

Remove an experiment (moved to trash for safety)::

    kai-exman rm <exp_id>
    kai-exman rm --clear-trash  # permanently empty trash
