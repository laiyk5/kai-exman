Experiment Lifecycle Design
===========================

This document defines the strict lifecycle model, CLI semantics,
and state transitions for Kai-Exman.

The design follows a single principle:

.. epigraph::

   **"If no run, no experiment."**

Every experiment record is created by executing a command.
There is no standalone "create empty experiment" step.


Core Concepts
-------------

Scripts-Centric Design
^^^^^^^^^^^^^^^^^^^^^^

All experiment operations are variations of **running a command**:

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - Command Form
     - Semantics
     - Creates Experiment?
   * - ``run -d "..." -- cmd``
     - Fresh run: create a new experiment, execute the command.
     - Yes (new)
   * - ``run --retry <id> -- cmd``
     - Retry (Case A): append attempt to a running experiment.
     - No
   * - ``run --inherit <pid> -- cmd``
     - Inherit (Case B): create child from a finished parent.
     - Yes (child)
   * - ``retry <id> -- cmd``
     - Standalone retry (Case A only). Append attempt to running experiment.
     - No (same exp)

There is no ``init`` command. A "draft" experiment is simply one that
has been created by ``run`` but whose command exited before creating
any meaningful artifacts. If you want to set up an experiment without
running anything meaningful, run a no-op command:

.. code-block:: bash

   kai-exman run -d "Setup baseline config" -- true

Experiment vs. Attempt States
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Experiment and attempt have **independent** state machines.

**Experiment states** (lifecycle):

.. code-block:: text

   draft → running → finished / aborted

- ``draft``
  The experiment directory exists but no attempt has been executed yet.
  Only possible immediately after a no-op ``run``.

- ``running``
  At least one attempt exists. The experiment is **unlocked** and can
  receive additional attempts via ``run --retry``.

- ``finished``
  The user called ``finish``, submitted a summary, and the experiment
  is **locked**. It can serve as a parent for ``run --inherit``.

- ``aborted``
  The user called ``abort``. The experiment is **locked** and has
  **no value**. It cannot be retried or inherited from.

**Attempt states** (execution outcome):

.. list-table::
   :header-rows: 1
   :widths: 20 50 30

   * - Status
     - Meaning
     - exit_code
   * - ``running``
     - Command is currently executing.
     - —
   * - ``success``
     - Command exited normally.
     - ``0``
   * - ``failed``
     - Command exited with an error.
     - ``!= 0``
   * - ``interrupted``
     - Command was killed by a signal.
     - ``< 0`` or ``>= 128``

A ``success`` attempt does **not** make the experiment ``finished``.
Only the explicit ``finish`` command can do that.

Retry vs. Inherit
^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Mode
     - Semantics
     - Conditions
   * - **Retry**
     - Append a new attempt to the *same* experiment.
     - Experiment is ``running``, workspace is **clean**.
   * - **Inherit**
     - Create a *new* experiment from a finished parent's artifacts.
     - Parent is ``finished`` (locked).

Key constraints:

- An **aborted** experiment can never be resumed or inherited from.
- A **running** experiment with a **diverged** workspace cannot be
  retried. The user must ``finish`` or ``abort`` it first, then
  ``run --inherit`` from the finished record.


State Transition Diagram
------------------------

Experiment State Machine
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

                    +-------------------------+
                    | run -d "..." -- true    |
                    | (no-op, creates draft)  |
                    +------------+------------+
                                 |
                                 v
                             +--------+
                             | draft  |
                             +---+----+
                                 |
              +------------------+------------------+
              | run -- python train.py                | (no attempt created)
              | (first attempt)                       v
              v                                   +--------+
          +---------+                               | (stays |
          | running |                               | draft) |
          +----+----+                               +--------+
               |
    +----------+----------+
    |                     |
    | run --retry <id>    | finish -s "..."
    | (clean git)         |
    v                     v
  +---------+       +----------+
  | running |       | finished |
  |(new att)|       | (locked) |
  +----+----+       +----+-----+
       |                 |
       |                 | run --inherit <pid>
       |                 v
       |            +---------+
       |            |  child  |
       |            | (draft) |
       |            +----+----+
       |                 |
       |                 | run -- python train.py
       |                 v
       |            +---------+
       |            | running |
       |            +----+----+
       |                 |
       |            +----+----+
       |            | finish  |
       |            | abort   |
       |            v         v
       |       +--------+ +--------+
       |       |finished| |aborted |
       |       |(locked)| |(locked)|
       |       +--------+ +--------+
       |
       +-----> abort
                v
            +--------+
            |aborted |
            |(locked)|
            +--------+

Legend
^^^^^^

- ``○`` — Unlocked state (draft / running)
- ``◆`` — Locked terminal state (finished / aborted)
- Solid arrows — Valid transitions
- Dashed arrows (conceptual) — Blocked paths that raise errors

Attempt Status Within a Running Experiment
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

   Experiment: running (unlocked)
   ├── attempt 1: success      ← exit_code = 0
   ├── attempt 2: failed       ← exit_code = 1
   ├── attempt 3: success      ← exit_code = 0
   └── attempt 4: interrupted  ← signal killed

   User action: finish -s "Converged to 95% acc."
   → Experiment: finished (locked)

   Note: Even though attempts 1 and 3 were "success",
   the experiment remained "running" until finish was called.


CLI Command Interaction Diagram
-------------------------------

Complete Workflow (Scripts-Centric)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

   User                    CLI                  ExMan               Filesystem
    |                       |                     |                     |
    |-- run -d "..." --...->|                     |                     |
    |                       |-- init() --------->|                     |
    |                       |                     |-- mkdir, snapshot ->|
    |                       |                     |<-- exp --------------|
    |                       |<-- exp_id ---------|                     |
    |                       |                     |                     |
    |                       |-- subprocess ----->|                     |
    |                       |   (KAI_EXMAN_*)   |                     |
    |                       |        |            |                     |
    |                       |        v            |                     |
    |                       |     +--+-----+      |                     |
    |                       |     |   OS   |      |                     |
    |                       |     +--------+      |                     |
    |                       |        |            |                     |
    |                       |<-- exit_code -------|                     |
    |                       |                     |                     |
    |                       |-- update attempt -->|                     |
    |                       |   (success/failed/  |                     |
    |                       |    interrupted)     |-- write metadata -->|
    |                       |                     |                     |
    |<-- done --------------|                     |                     |
    |                       |                     |                     |
    |-- finish -s "..." --->|                     |                     |
    |                       |-- finish() -------->|                     |
    |                       |                     |-- lock, summary.md->|
    |                       |<-- done ------------|                     |
    |                       |                     |                     |
    |-- run --retry <id> -->|                     |                     |
    |   -- python train.py  |                     |                     |
    |                       |-- resume(Case A) -->|                     |
    |                       |                     |-- append attempt -->|
    |                       |<-- exp ------------|                     |
    |                       |-- subprocess ----->|                     |
    |                       |        |            |                     |
    |                       |        v            |                     |
    |                       |     +--+-----+      |                     |
    |                       |     |   OS   |      |                     |
    |                       |     +--------+      |                     |
    |                       |        |            |                     |
    |                       |<-- exit_code -------|                     |
    |                       |                     |                     |
    |-- run --inherit <pid>|                     |                     |
    |   -d "..." -- python  |                     |                     |
    |                       |-- resume(Case B) -->|                     |
    |                       |                     |-- init(child) ----->|
    |                       |                     |-- copy ckpts ------>|
    |                       |                     |<-- child exp -------|
    |                       |<-- child_id --------|                     |
    |                       |-- subprocess ----->|                     |
    |                       |        |            |                     |
    |                       |        v            |                     |
    |                       |     +--+-----+      |                     |
    |                       |     |   OS   |      |                     |
    |                       |     +--------+      |                     |

Error Paths (Blocked Transitions)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

   User: run --retry <aborted_id> -- python train.py
   CLI ──► resume() ──► ✗ ValueError:
         "Aborted experiments cannot be resumed."

   User: run --inherit <running_id> -- python train.py
   CLI ──► resume() ──► ✗ ValueError:
         "Experiment is still running. Use `run --retry` to append an attempt."

   User: retry <aborted_id> -- python train.py
   CLI ──► resume() ──► ✗ ValueError:
         "Aborted experiments cannot be inherited."

   User: retry <aborted_id> -- python train.py
   CLI ──► resume() ──► ✗ ValueError:
         "Aborted experiments cannot be inherited."

   User: rm <parent_id>
   CLI ──► remove() ──► ✗ ValueError:
         "Cannot remove: has child experiment(s): a1b2c3d4."


Command Reference
-----------------

Lifecycle Commands
^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Command
     - Purpose
     - Constraints
   * - ``run -d "..." [--data-path PATH] -- cmd``
     - Fresh run: create a new experiment and execute the command.
     - ``description`` is **required**. ``--data-path`` is optional.
   * - ``run --retry <id> [--data-path PATH] -- cmd``
     - Retry (Case A): append attempt to a running experiment.
     - Exp must be ``running``, git **clean**.
   * - ``run --inherit <pid> -d "..." [--data-path PATH] -- cmd``
     - Inherit (Case B): create child from a finished parent.
     - ``description`` is **required**.
   * - ``retry <id> [--data-path PATH] -- cmd``
     - Standalone retry (Case A only). Append attempt to a running experiment.
     - Exp must be ``running``, git **clean**.
   * - ``finish [<id>] -s "..."``
     - Seal the experiment with a conclusion.
     - ``summary`` is **required**, at least one attempt.
   * - ``abort [<id>]``
     - Give up on the experiment. No summary needed.
     - At least one attempt. Locks permanently.

Management Commands
^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - Command
     - Purpose
     - Constraints
   * - ``list`` / ``list --tree``
     - List experiments.
     - Shows intent / conclusion per mode.
   * - ``show <id>``
     - Display full details.
     - —
   * - ``tag <id> <tag>``
     - Add/remove tags.
     - —
   * - ``move <id> -g <group>``
     - Move to another group.
     - —
   * - ``rm <id>``
     - Move to trash.
     - Rejected if experiment has children.
   * - ``rm --clear-trash``
     - Purge trash permanently.
     - —


Data Model
----------

Metadata
^^^^^^^^

.. code-block:: python

   class Metadata:
       exp_id: str              # 16-char hex
       group: str
       description: str         # intent (required at run / run --inherit)
       summary: str | None      # conclusion (required at finish)
       tags: list[str]
       status: str              # "draft" | "running" | "finished" | "aborted"
       locked: bool             # True for finished / aborted
       parent_id: str | None    # set only by run --inherit
       git_hash: str | None
       git_dirty: bool
       data_version: str
       data_hash: str           # blake2b of --data-path (auto-computed)
       timestamp: str           # creation time
       finished_at: str | None
       attempts: list[Attempt]
       deletable: bool          # cascade-removable when childless

Attempt
^^^^^^^

.. code-block:: python

   class Attempt:
       sequence: int
       status: str              # "running" | "success" | "failed" | "interrupted"
       start_time: str
       end_time: str | None
       exit_code: int | None
       reason: str              # e.g. "run_1", "retry_after_oom"
       command: list[str]        # argv recorded at attempt start


Rule Summary
------------

Run (Fresh) Rules
^^^^^^^^^^^^^^^^^

- Always creates a **new** experiment.
- ``description`` is **required**.
- ``tags``, ``config``, ``group`` are optional.
- After the subprocess exits, the experiment status remains ``running``
  (not ``success`` or ``failed``). Only the *attempt* records the outcome.

Retry Rules
^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 10 45 45

   * - ✅/❌
     - Condition
     - Outcome
   * - ✅
     - Exp is ``running``, git clean, hash matches
     - Append new attempt to same experiment
   * - ❌
     - Exp is ``finished`` (locked)
     - Cannot retry; use ``run --inherit`` to create a child.
   * - ❌
     - Exp is ``aborted`` (locked)
     - Permanently prohibited
   * - ❌
     - Exp is ``running``, git dirty
     - Reject; finish/abort first, then inherit

Inherit Rules
^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 10 45 45

   * - ✅/❌
     - Condition
     - Outcome
   * - ✅
     - Parent is ``finished``
     - Create child experiment, copy checkpoints
   * - ❌
     - Parent is ``aborted``
     - No value; permanently prohibited
   * - ❌
     - Parent is ``running``
     - Not finished yet; finish first
   * - ✅
     - ``description`` provided for the child
     - New experiment intent recorded
   * - ✅
     - ``tags`` / ``config`` / ``group`` optional
     - Override inherited values

Finish Rules
^^^^^^^^^^^^

- At least one attempt must exist.
- ``summary`` is **required**.
- ``locked`` is set to ``True``.
- ``status`` becomes ``finished``.
- ``summary.md`` is generated.

Abort Rules
^^^^^^^^^^^

- At least one attempt must exist.
- **No summary required.** The act of aborting is the statement.
- ``locked`` is set to ``True``.
- ``status`` becomes ``aborted``.
- A minimal ``summary.md`` may be generated with a default note
  (e.g. "Aborted by user.").
- **No future operations allowed** on this experiment.

Delete Rules
^^^^^^^^^^^^

Direct Delete
'''''''''''''

- An experiment with **no child experiments** → can be moved to trash.
- An experiment with **child experiments** → **rejected**, but can be
  marked as **deletable**.

Mark Deletable
''''''''''''''

.. code-block:: bash

   kai-exman rm <parent_id> --mark-deletable

A deletable experiment is **not** removed immediately. It is scheduled
for automatic removal when its **last child** is deleted.

Cascade Delete
''''''''''''''

When an experiment is removed, the system checks its parent:

1. If the parent is marked **deletable**.
2. If the parent has **no remaining children** after this removal.
3. If both are true → the parent is also removed (recursively).

Example:

.. code-block:: text

   grandparent (deletable)
       └── parent (deletable)
               └── child

   User: rm child
   → child moved to trash
   → parent has no children left → parent moved to trash
   → grandparent has no children left → grandparent moved to trash

Trash auto-purges oldest items when capacity limits are exceeded.


Design Decisions
----------------

D1: Scripts-Centric Design ("If No Run, No Experiment")
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Decision:** There is no standalone ``init`` command. Every experiment
is created by executing a command.

**Rationale:**
An experiment without execution has no observable outcome.
If a user wants to "prepare" an experiment without running real work,
they run a no-op command:

.. code-block:: bash

   kai-exman run -d "Setup baseline" -- true

This keeps the CLI surface minimal and enforces the principle that
experiments are defined by what they *do*, not just what they *intend*.

D2: Unified ``run`` Command
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Decision:** ``run`` has three mutually exclusive modes:

1. **Default** (no flags) — create a new experiment.
2. ``--retry <id>`` — explicit Case A (retry).
3. ``--inherit <pid>`` — explicit Case B (inherit).

A standalone ``retry`` command is retained for explicit Case A retries.

**Rationale:**
Retry, inherit, and fresh run are all fundamentally "execute a command
in an experiment context." Unifying them under ``run`` makes the CLI
more discoverable and reduces the number of top-level commands.

D3: Experiment vs. Attempt States Are Independent
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Decision:**

- **Attempt** states: ``running``, ``success``, ``failed``, ``interrupted``.
- **Experiment** states: ``draft``, ``running``, ``finished``, ``aborted``.

After a ``run`` command exits, the *attempt* records the outcome
(``success`` / ``failed`` / ``interrupted``), but the *experiment*
remains ``running`` (unlocked). Only ``finish`` or ``abort`` can
change the experiment's global state.

**Rationale:**
An attempt is a single observation. An experiment is a complete
exploration that may span multiple attempts. A successful attempt
is just one data point; the user may want to retry for stability
or finish to record their conclusion.

D4: Abort Requires No Summary
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Decision:** ``abort`` does **not** require a ``summary``.

**Rationale:**
An aborted experiment is explicitly marked as having **no value**.
Requiring a summary would create the false impression that the
experiment contributes something worth documenting. The abort action
itself is the complete statement.

D5: Retry Supports Optional ``--reason``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Decision:** ``retry`` accepts an optional ``--reason`` flag.

.. code-block:: bash

   kai-exman retry <id> --reason "retry after OOM" -- python train.py

If omitted, ``Attempt.reason`` defaults to ``"run_N"``.

**Rationale:**
When an experiment has many attempts, auto-generated names like
``"run_5"`` are uninformative. An optional reason helps users
remember *why* they retried without forcing them to document
every trivial retry.

D6: Inherit Requires Description
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Decision:** ``run --inherit`` (Case B) always requires a
``description`` for the child experiment.

**Rationale:**
Inheriting is not retrying. The child experiment is a *new*
exploration with a different intent (different code, different
hyperparameters, etc.). A mandatory description ensures every
experiment has a stated purpose.

D7: Parent Protection on Delete
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Decision:** An experiment with child experiments cannot be deleted.

**Rationale:**
Inheritance creates a lineage. Deleting a parent would orphan its
children, breaking reproducibility. Users must delete children first
before removing a parent.
