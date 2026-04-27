Experiment Lifecycle Design
===========================

This document defines the strict lifecycle model, CLI semantics,
and state transitions for Kai-Exman.

The design follows a single principle:

.. epigraph::

   **"Explicit creation, explicit execution."**

Experiments are created via ``init`` as drafts with empty attempts.
Execution is separate: ``run`` only operates on existing experiments.
This gives the user explicit control over creation vs. execution.


Core Concepts
-------------

Explicit Creation / Execution Separation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

All experiment operations are divided into two orthogonal phases:

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - Command Form
     - Semantics
     - Creates Experiment?
   * - ``init -d "..."``
     - Create a draft experiment with empty attempts.
     - **Yes** (new root)
   * - ``init -d "..." --inherit <pid>``
     - Create a draft child from finished parent(s).
     - **Yes** (child)
   * - ``run <id> -- cmd``
     - Execute on an existing experiment.
     - No
   * - ``finish [<id>] -s "..."``
     - Seal the experiment with a conclusion.
     - No
   * - ``abort [<id>]``
     - Give up on the experiment. No summary needed.
     - No


Experiment vs. Attempt States
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Experiment and attempt have **independent** state machines.

**Experiment states** (lifecycle):

.. code-block:: text

   draft → running → finished / aborted

- ``draft``
  The experiment directory exists but no attempt has been executed yet.
  Created by ``init``.

- ``running``
  At least one attempt exists. The experiment is **unlocked** and can
  receive additional attempts via ``run``.

- ``finished``
  The user called ``finish``, submitted a summary, and the experiment
  is **locked**. It can serve as a parent for ``init --inherit``.

- ``aborted``
  The user called ``abort``. The experiment is **locked** and has
  **no value**. It cannot be inherited from.

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
     - Create a *new* experiment from finished parent(s).
     - Parent(s) are ``finished`` (locked).

Key constraints:

- An **aborted** experiment can never be inherited from.
- A **running** experiment with a **diverged** workspace cannot be
  retried. The user must ``finish`` or ``abort`` it first, then
  ``init --inherit`` from the finished record.
- Inheritance supports **multiple parents** via repeated ``--inherit`` flags.


State Transition Diagram
------------------------

Experiment State Machine
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

                    +-------------------------+
                    | init -d "..."           |
                    | (creates draft)         |
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
    | run -- python train.py   (git clean)
    | (append attempt)    | finish -s "..."
    v                     v
  +---------+       +----------+
  | running |       | finished |
  |(new att)|       | (locked) |
  +----+----+       +----+-----+
       |                 |
       |                 | init --inherit <pid> -d "..."
       |                 v
       |            +---------+
       |            |  draft  |
       |            |(child)  |
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

Complete Workflow
^^^^^^^^^^^^^^^^^

.. code-block:: text

   User                    CLI                  ExMan               Filesystem
    |                       |                     |                     |
    |-- init -d "..." ----->|                     |                     |
    |                       |-- init() --------->|                     |
    |                       |                     |-- mkdir, snapshot ->|
    |                       |                     |<-- exp --------------|
    |                       |<-- exp_id ---------|                     |
    |                       |                     |                     |
    |-- run <id> --... ---->|                     |                     |
    |                       |-- run() ---------->|                     |
    |                       |                     |-- append attempt -->|
    |                       |                     |<-- exp --------------|
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
    |-- init --inherit <pid>|                     |                     |
    |   -d "..."            |                     |                     |
    |                       |-- init(parent_ids)->|                     |
    |                       |                     |-- init(child) ----->|
    |                       |                     |-- copy ckpts ------>|
    |                       |                     |<-- child exp -------|
    |                       |<-- child_id --------|                     |
    |                       |                     |                     |
    |-- run <child_id> ---->|                     |                     |
    |   -- python train.py  |                     |                     |
    |                       |-- run() ---------->|                     |
    |                       |-- subprocess ----->|                     |
    |                       |        |            |                     |
    |                       |        v            |                     |
    |                       |     +--+-----+      |                     |


Error Paths (Blocked Transitions)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

   User: run <finished_id> -- python train.py
   CLI ──► run() ──► ✗ ValueError:
         "Experiment is finished. Use `init --inherit <id>` to create a child."

   User: run <aborted_id> -- python train.py
   CLI ──► run() ──► ✗ ValueError:
         "Aborted experiments cannot be run."

   User: init --inherit <running_id> -d "..."
   CLI ──► init() ──► ✗ ValueError:
         "Experiment is still running. Finish or abort it first."

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
   * - ``init -d "..." [--data-path PATH]``
     - Create a draft experiment.
     - ``description`` is **required** in non-TTY mode.
   * - ``init -d "..." --inherit <pid>``
     - Create a draft child from finished parent(s).
     - Parent must be ``finished``. Can repeat ``--inherit`` for multi-parent.
   * - ``run [<id>] -- cmd``
     - Execute on an existing experiment.
     - Draft → attempt 1. Running → append attempt (git clean).
   * - ``run [<id>] --reason "..." -- cmd``
     - Execute with an explicit attempt reason.
     - Optional. Defaults to ``run_N``.
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
   * - ``status [<id>]``
     - Display full details (alias: ``show``).
     - —
   * - ``tag [<id>] <tag>``
     - Add/remove tags.
     - ``tag -l`` lists all tags.
   * - ``group``
     - Suggest group assignments.
     - ``group -l`` lists all groups.
   * - ``move [<id>] -g <group>``
     - Move to another group.
     - —
   * - ``rm [<id>]``
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
       description: str         # intent (required at init)
       summary: str | None      # conclusion (required at finish)
       tags: list[str]
       status: str              # "draft" | "running" | "finished" | "aborted"
       locked: bool             # True for finished / aborted
       parent_ids: list[str]    # set by init --inherit
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
       reason: str              # e.g. "run_1", "retry after OOM"
       command: list[str]        # argv recorded at attempt start


Rule Summary
------------

Run Rules
^^^^^^^^^

- Operates on an **existing** experiment. Never creates a new one.
- On a **draft** → creates attempt 1 and executes.
- On a **running** experiment → appends attempt N (git clean required).
- On a **finished** or **aborted** experiment → raises.

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
     - Cannot retry; use ``init --inherit`` to create a child.
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
     - Create child experiment, copy checkpoints from all parents
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
- A minimal ``summary.md`` is generated with a default note
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

D1: Explicit Creation / Execution Separation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Decision:** ``init`` is the only command that creates experiments.
``run`` is execution-only and never creates.

**Rationale:**
Creation and execution are conceptually different acts. The user should
declare intent before running. A draft experiment can exist without
execution — it represents a planned experiment with configuration,
tags, and inheritance set up in advance.

This replaces the old "scripts-centric" model where ``run`` silently
created experiments, making it impossible to set up an experiment
without also executing a command.

D2: Unified ``run`` Command (Execution-Only)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Decision:** ``run`` only executes on existing experiments. It handles
both drafts (first attempt) and running experiments (append attempt).
No ``--retry`` or ``--inherit`` flags.

**Rationale:**
Since ``init`` handles creation, ``run`` only needs to execute. A single
execution command is simpler than three variants. The user provides the
experiment ID (or uses the default), and ``run`` does the right thing.

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

**Decision:** ``run`` accepts an optional ``--reason`` flag.

.. code-block:: bash

   kai-exman run <id> --reason "retry after OOM" -- python train.py

If omitted, ``Attempt.reason`` defaults to ``"run_N"``.

**Rationale:**
When an experiment has many attempts, auto-generated names like
``"run_5"`` are uninformative. An optional reason helps users
remember *why* they retried without forcing them to document
every trivial retry.

D6: Inherit Requires Description
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Decision:** ``init --inherit`` always requires a
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
