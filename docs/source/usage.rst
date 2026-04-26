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
    )

    exp.log_metrics(step=0, values={"loss": 1.2, "acc": 0.5})
    exp.log_metrics(step=1, values={"loss": 0.8, "acc": 0.7})

    exman.finish(exp_id=exp.metadata.exp_id, status="success", notes="Good convergence.")

CLI
---

Initialize a new experiment::

    kai-exman init --description "Baseline run" --tags "baseline,llama3" --config config.yaml

List experiments::

    kai-exman --path ./outputs list
