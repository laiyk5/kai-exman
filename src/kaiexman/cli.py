"""Kai-Exman CLI entry point.

Provides a Click-based command-line interface for experiment management
with git-log-style output, smart TTY detection, and Rich terminal rendering.
"""

from __future__ import annotations

import getpass
import io
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, overload

import click
import yaml
from rich.console import Console

from kaiexman.config import ConfigManager
from kaiexman.experiment import Experiment, validate_group, validate_tag
from kaiexman.manager import ExMan
from kaiexman.models import LockedExperimentError, MissingSummaryError

# Editor templates for the Mandatory Reflection policy.
# Lines starting with # are stripped by _require_text.
_INTENT_TEMPLATE = """\
# Hypothesis:
#
# Method:
#
# Expected outcome:
"""

_FORK_TEMPLATE = """\
# What changed from the parent:
#
# Why this change matters:
#
# Expected impact:
"""

_CONCLUSION_TEMPLATE = """\
# What worked:
#
# What did not work:
#
# Key metrics / observations:
#
# Next steps:
"""


def _require_text(
    value: str,
    prompt: str,
    empty_msg: str,
    template: str = "",
) -> str:
    """Return value if non-empty, otherwise open an editor or raise.

    In interactive mode (TTY), opens the system editor (via click.edit)
    with an optional template pre-filled.

    In non-interactive mode, raises a ClickException.

    Args:
        value: The provided value from CLI option.
        prompt: Header text to seed the editor buffer.
        empty_msg: Error message if the value is still empty after editing.
        template: Optional multi-line template to pre-fill in the editor.

    Returns:
        The non-empty text string.

    Raises:
        click.ClickException: If non-interactive and value is empty, or if
            the editor returns empty content.
    """
    if value:
        return value
    if not sys.stdin.isatty():
        raise click.ClickException(empty_msg)

    if template:
        editor_text = f"# {prompt}\n# Lines starting with # are ignored.\n{template}\n"
    else:
        editor_text = f"# {prompt}\n"

    edited = click.edit(text=editor_text)
    if edited is None:
        raise click.ClickException(empty_msg)

    # Strip comment lines and whitespace
    cleaned = "\n".join(
        line for line in edited.splitlines() if not line.strip().startswith("#")
    ).strip()

    if not cleaned:
        raise click.ClickException(empty_msg)
    return cleaned


class AliasedGroup(click.Group):
    """Click group with command aliases.

    Attributes:
        _aliases: Mapping of alias names to canonical command names.
    """

    _aliases = {"log": "list", "show": "status", "suggest-groups": "group"}

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Resolve a command name, falling back to registered aliases.

        Args:
            ctx: Click context.
            cmd_name: Command name provided by the user.

        Returns:
            The Click Command object, or None if not found.
        """
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        alias = self._aliases.get(cmd_name)
        if alias:
            return super().get_command(ctx, alias)
        return None


def _use_color(ctx: click.Context) -> bool:
    """Determine whether color output should be enabled.

    Args:
        ctx: Click context containing CLI options.

    Returns:
        True if color is enabled and stdout is a TTY.
    """
    if ctx.obj.get("no_color"):
        return False
    return sys.stdout.isatty()


def _use_pager(ctx: click.Context) -> bool:
    """Determine whether the pager should be used.

    Args:
        ctx: Click context containing CLI options.

    Returns:
        True if paging is enabled and stdout is a TTY.
    """
    if ctx.obj.get("no_pager"):
        return False
    return sys.stdout.isatty()


def _echo_lines(ctx: click.Context, lines: list[str], use_pager: bool = False) -> None:
    """Output lines with Rich colors in TTY, plain text otherwise.

    Args:
        ctx: Click context for color detection.
        lines: List of strings that may contain Rich markup tags.
        use_pager: Whether to pipe output through a pager in TTY mode.
    """
    use_color = _use_color(ctx)
    console = Console(
        file=io.StringIO(), force_terminal=use_color, soft_wrap=True, record=True
    )
    for line in lines:
        console.print(line)
    output = console.export_text(styles=use_color).rstrip("\n")
    if use_pager and _use_pager(ctx):
        os.environ.setdefault("LESS", "-R")
        click.echo_via_pager(output)
    else:
        click.echo(output)


def _resolve_exp_id(exman: ExMan, prefix: str) -> str:
    """Resolve a partial EXP_ID prefix to a full ID.

    Args:
        exman: ExMan manager instance.
        prefix: Partial or full experiment ID.

    Returns:
        The full experiment ID if exactly one experiment matches.

    Raises:
        click.ClickException: If zero or multiple experiments match the prefix.
    """
    experiments = exman.list()
    matches = [e for e in experiments if e.metadata.exp_id.startswith(prefix)]

    if len(matches) == 1:
        return matches[0].metadata.exp_id

    if len(matches) == 0:
        raise click.ClickException(f"No experiment found starting with '{prefix}'")

    ids = ", ".join(e.metadata.exp_id for e in matches)
    raise click.ClickException(
        f"Ambiguous prefix '{prefix}' matches multiple experiments: {ids}"
    )


@overload
def _resolve_exp_id_or_default(
    exman: ExMan, prefix: str | None, allow_missing: Literal[False] = False
) -> str: ...


@overload
def _resolve_exp_id_or_default(
    exman: ExMan, prefix: str | None, allow_missing: Literal[True] = True
) -> str | None: ...


def _resolve_exp_id_or_default(
    exman: ExMan, prefix: str | None, allow_missing: bool = False
) -> str | None:
    """Resolve an EXP_ID or fall back to the default experiment.

    Args:
        exman: ExMan manager instance.
        prefix: Partial or full experiment ID, or None to use default.
        allow_missing: If True, return None when no default is set.

    Returns:
        The full experiment ID, or None if allow_missing is True and
        no default is set.

    Raises:
        click.ClickException: If prefix is None and no default is set,
            or if the default ID is invalid, or if resolution fails.
    """
    if prefix:
        return _resolve_exp_id(exman, prefix)

    default_id = exman.get_default_exp_id()
    if default_id is not None:
        return default_id

    if allow_missing:
        return None

    raise click.ClickException(
        "No default experiment set. Use 'kai-exman use <id>' or provide an EXP_ID."
    )


def _validate_tag(tag: str) -> None:
    """Validate a tag and raise ClickException on failure.

    Args:
        tag: Tag name to validate.

    Raises:
        click.ClickException: If the tag format is invalid.
    """
    try:
        validate_tag(tag)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def _validate_group(group: str) -> None:
    """Validate a group and raise ClickException on failure.

    Args:
        group: Group name to validate.

    Raises:
        click.ClickException: If the group format is invalid.
    """
    try:
        validate_group(group)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@click.group(cls=AliasedGroup)
@click.option(
    "--path",
    default=lambda: os.environ.get("EXMAN_PATH", "./outputs"),
    help="Root path for experiments (default: ./outputs or EXMAN_PATH env)",
)
@click.option(
    "--no-pager",
    is_flag=True,
    help="Disable pager (auto-detected when not a TTY)",
)
@click.option(
    "--no-color",
    is_flag=True,
    help="Disable colored output (auto-detected when not a TTY)",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Enable strict mode (overrides pyproject.toml)",
)
@click.option(
    "--critical-path",
    help="Override critical paths (comma-separated, replaces defaults)",
)
@click.option(
    "--short-id-length",
    type=int,
    help="Override short ID display length (default: 8)",
)
@click.pass_context
def cli(
    ctx: click.Context,
    path: str,
    no_pager: bool,
    no_color: bool,
    strict: bool,
    critical_path: str | None,
    short_id_length: int | None,
) -> None:
    """Kai-Exman: Rigorous Experiment Management."""
    ctx.ensure_object(dict)
    ctx.obj["path"] = path
    ctx.obj["no_pager"] = no_pager
    ctx.obj["no_color"] = no_color

    cli_overrides: dict[str, Any] = {}
    if strict:
        cli_overrides["strict_mode"] = True
    if critical_path is not None:
        cli_overrides["critical_paths"] = [
            p.strip() for p in critical_path.split(",") if p.strip()
        ]
    if short_id_length is not None:
        cli_overrides["short_id_length"] = short_id_length

    ctx.obj["config"] = ConfigManager(cli_overrides=cli_overrides or None)


@cli.command()
@click.option("--description", "-d", default="", help="Experiment description")
@click.option("--tags", "-t", default="", help="Comma-separated tags")
@click.option("--config", "-c", help="Path to config YAML file")
@click.option("--group", "-g", default="default", help="Group name (default: default)")
@click.option("--data-path", help="Dataset path for automatic hash")
@click.option(
    "--inherit",
    multiple=True,
    help="Parent experiment ID to inherit from (can be used multiple times)",
)
@click.pass_context
def init(
    ctx: click.Context,
    description: str,
    tags: str,
    config: str | None,
    group: str,
    data_path: str | None,
    inherit: tuple[str, ...],
) -> None:
    """Initialize a new experiment (draft).

    Creates a directory structure, captures Git state, and optionally
    loads a YAML configuration file. Use --inherit to create a child
    experiment from one or more finished parents.
    """
    description = _require_text(
        description,
        prompt="Describe the intent of this experiment...",
        empty_msg=(
            "Experiment description is required."
            " Use --description or run interactively."
        ),
        template=_INTENT_TEMPLATE,
    )
    _validate_group(group)
    cfg = None
    if config and Path(config).exists():
        with open(config, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)

    parent_ids = list(inherit) if inherit else None
    try:
        exp = exman.init(
            description=description,
            tags=tag_list or None,
            config=cfg,
            group=group,
            data_path=data_path or "",
            parent_ids=parent_ids,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = exp.metadata.exp_id[:short_len]

    lines: list[str] = [
        "[bold green]Experiment Initialized[/bold green]",
        f"[bold]Experiment ID:[/bold] {short_id}",
        f"[bold]Path:[/bold] {exp.root}",
        f"[bold]Group:[/bold] {exp.metadata.group}",
        f"[bold]Git Hash:[/bold] {exp.metadata.git_hash or 'N/A'}",
        f"[bold]Status:[/bold] {exp.metadata.status}",
    ]
    if exp.metadata.parent_ids:
        parent_shorts = ", ".join(pid[:short_len] for pid in exp.metadata.parent_ids)
        lines.append(f"[bold]Parents:[/bold] {parent_shorts}")
    if exp.metadata.git_dirty:
        lines.append(
            "[bold yellow]Warning:[/bold yellow] Working tree has uncommitted changes"
        )
    _echo_lines(ctx, lines)


@cli.command()
@click.argument("args", nargs=-1, required=False)
@click.option("--id", "exp_id", help="Experiment ID (defaults to current)")
@click.option("--data-path", help="Dataset path for automatic hash")
@click.option("--reason", help="Reason for this attempt (e.g. 'retry after OOM')")
@click.pass_context
def run(
    ctx: click.Context,
    args: tuple[str, ...],
    exp_id: str | None,
    data_path: str | None,
    reason: str,
) -> None:
    """Execute a command on an existing experiment.

    Creates attempt 1 for a draft experiment, or appends an attempt for a
    running experiment. Finished or aborted experiments cannot be run.

    Usage:
        kai-exman run -- python train.py                    (uses default exp)
        kai-exman run --id <exp_id> -- python train.py      (uses specific exp)
    """
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)

    if exp_id:
        resolved_id = _resolve_exp_id(exman, exp_id)
    else:
        resolved_id = _resolve_exp_id_or_default(exman, None)

    command = list(args)
    if command and command[0] == "--":
        command = command[1:]

    if not command:
        raise click.ClickException(
            "No command to execute. Provide a command, e.g.:\n"
            "  kai-exman run -- python train.py"
        )

    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = resolved_id[:short_len]

    _echo_lines(ctx, [f"[bold green]Running experiment {short_id}.[/bold green]"])

    try:
        _exp, returncode = exman.run(
            resolved_id, command, data_path=data_path or "", reason=reason
        )
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc

    status_color = "green" if returncode == 0 else "red"
    _echo_lines(
        ctx,
        [
            f"[bold {status_color}]Experiment {short_id} exited with "
            f"code {returncode}.[/bold {status_color}]"
        ],
    )

    sys.exit(returncode)


@cli.command(name="list")
@click.option(
    "--sort-by",
    help="Metric name to sort by (e.g. 'acc', 'loss')",
)
@click.option(
    "--order",
    type=click.Choice(["asc", "desc"]),
    default="desc",
    help="Sort order: asc (min first) or desc (max first)",
)
@click.option(
    "--sort",
    "sort_key",
    type=click.Choice(["created", "finished", "group", "id"]),
    default=None,
    help="Sort experiments structurally",
)
@click.option(
    "--top",
    type=int,
    help="Show only the top N experiments",
)
@click.option(
    "--oneline",
    is_flag=True,
    help="Use compact one-line format per experiment",
)
@click.option(
    "--tag",
    "tag_filter",
    help="Filter experiments by tag name",
)
@click.option(
    "--group",
    "group_filter",
    help="Filter experiments by group name",
)
@click.option(
    "--tree",
    is_flag=True,
    help="Display experiments in lineage tree view",
)
@click.option(
    "--full-id",
    is_flag=True,
    help="Display full 16-character experiment IDs",
)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    sort_by: str | None,
    order: str,
    sort_key: str | None,
    top: int | None,
    oneline: bool,
    tag_filter: str | None,
    group_filter: str | None,
    tree: bool,
    full_id: bool,
) -> None:
    """List experiments with flexible view modes and sorting.

    Supports three view modes: default (log), --oneline (compact table),
    and --tree (lineage topology). Sort by creation time, finish time,
    group, ID, or by a specific metric.
    """
    if sort_by and sort_key:
        raise click.UsageError("--sort and --sort-by are mutually exclusive.")

    exman = ExMan(root=ctx.obj["path"])
    experiments = exman.list(group=group_filter)

    if tag_filter:
        experiments = [e for e in experiments if tag_filter in e.metadata.tags]

    if not experiments:
        click.echo("No experiments found.")
        return

    metric_sort: tuple[str, str, dict[str, float]] | None = None

    if sort_by:
        scored = []
        scores: dict[str, float] = {}
        for exp in experiments:
            best = exp.compute_best_metrics()
            score = None
            if sort_by in best:
                score = (
                    best[sort_by]["max"] if order == "desc" else best[sort_by]["min"]
                )
            scored.append((exp, best, score))
            if score is not None:
                scores[exp.metadata.exp_id] = score
        scored.sort(
            key=lambda x: (x[2] is None, x[2] or 0),
            reverse=order == "desc",
        )
        if top:
            scored = scored[:top]
        experiments = [s[0] for s in scored]
        metric_sort = (sort_by, order, scores)
    else:
        sort_key = sort_key or "created"
        experiments = _sort_experiments(experiments, sort_key, order)
        if top:
            experiments = experiments[:top]

    short_len = ctx.obj["config"].get("short_id_length", 8)

    if tree:
        roots, children_map = _build_lineage(experiments)
        lines = _build_tree_lines(roots, children_map, full_id, short_len)
    elif oneline:
        lines = _build_oneline_lines(experiments, full_id, short_len, metric_sort)
    else:
        lines = _build_log_lines(experiments, full_id, short_len, metric_sort)

    _echo_lines(ctx, lines, use_pager=True)


_STATUS_COLORS = {
    "success": "green",
    "running": "yellow",
    "failed": "red",
    "error": "red",
    "aborted": "dim",
}


def _format_dt(iso: str) -> str:
    """Convert an ISO timestamp to a git-log-style date string.

    Args:
        iso: ISO 8601 formatted timestamp string.

    Returns:
        Formatted date string (e.g., 'Mon Jan 01 12:00:00 2024 +0800'),
        or the truncated input if parsing fails.
    """
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return dt.strftime("%a %b %d %H:%M:%S %Y %z")
    except (ValueError, TypeError):
        return iso[:19] if len(iso) >= 19 else iso


def _format_dt_compact(iso: str) -> str:
    """Convert an ISO timestamp to a compact display string.

    Args:
        iso: ISO 8601 formatted timestamp string.

    Returns:
        Formatted date string (e.g., 'Apr 27 10:00'),
        or the truncated input if parsing fails.
    """
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%b %d %H:%M")
    except (ValueError, TypeError):
        return iso[:16] if len(iso) >= 16 else iso


def _params_line(config: dict[str, Any]) -> str:
    """Build a compact parameter summary string.

    Args:
        config: Configuration dictionary.

    Returns:
        Space-separated key=value pairs (up to 3 entries).
    """
    if not config:
        return ""
    items = list(config.items())[:3]
    return " ".join(f"{k}={v}" for k, v in items)


def _oneline_dt(iso: str) -> str:
    """Convert an ISO timestamp to a compact date string.

    Args:
        iso: ISO 8601 formatted timestamp string.

    Returns:
        Formatted date string (e.g., '2024-01-01 12:00'),
        or the truncated input if parsing fails.
    """
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso[:16] if len(iso) >= 16 else iso


def _first_line(text: str) -> str:
    """Return the first non-empty line, or empty string."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _display_id(exp_id: str, full_id: bool, short_length: int = 8) -> str:
    """Return the experiment ID to display.

    Args:
        exp_id: Full experiment identifier.
        full_id: Whether to show the full 16-character ID.
        short_length: Number of characters to show when abbreviated.

    Returns:
        The full ID if full_id is True, otherwise the first short_length chars.
    """
    return exp_id if full_id else exp_id[:short_length]


def _sort_experiments(
    experiments: list[Experiment],
    sort_key: str,
    order: str,
) -> list[Experiment]:
    """Sort experiments by a structural key.

    Args:
        experiments: List of experiments to sort.
        sort_key: Structural sort key (created, finished, group, id).
        order: Sort direction ("asc" or "desc").

    Returns:
        Sorted list of experiments.
    """
    reverse = order == "desc"

    def key_fn(exp: Experiment) -> Any:
        """Return sort key for an experiment."""
        if sort_key == "created":
            return exp.metadata.timestamp
        if sort_key == "finished":
            if exp.metadata.attempts:
                last_end = exp.metadata.attempts[-1].end_time
                if last_end:
                    return last_end
            return exp.metadata.timestamp
        if sort_key == "group":
            return exp.metadata.group
        if sort_key == "id":
            return exp.metadata.exp_id
        return exp.metadata.timestamp

    return sorted(experiments, key=key_fn, reverse=reverse)


def _build_lineage(
    experiments: list[Experiment],
) -> tuple[list[Experiment], dict[str, list[Experiment]]]:
    """Build a lineage graph from experiments.

    Args:
        experiments: List of experiments.

    Returns:
        Tuple of (root_experiments, children_map) where children_map
        maps parent_id to a list of child experiments.
    """
    exp_map = {e.metadata.exp_id: e for e in experiments}
    roots: list[Experiment] = []
    children_map: dict[str, list[Experiment]] = {}

    for exp in experiments:
        has_parent_in_set = any(pid in exp_map for pid in exp.metadata.parent_ids)
        if not has_parent_in_set:
            roots.append(exp)
        for pid in exp.metadata.parent_ids:
            if pid in exp_map:
                children_map.setdefault(pid, []).append(exp)

    return roots, children_map


def _build_log_lines(
    experiments: list[Experiment],
    full_id: bool,
    short_len: int,
    metric_sort: tuple[str, str, dict[str, float]] | None = None,
) -> list[str]:
    """Build git-log-style lines for experiment list.

    Args:
        experiments: List of experiments to render.
        full_id: Whether to display full 16-character IDs.
        short_len: Number of characters for abbreviated IDs.
        metric_sort: Optional (name, order, exp_id->score) tuple.

    Returns:
        List of markup strings representing the log view.
    """
    lines: list[str] = []
    for exp in experiments:
        status_color = _STATUS_COLORS.get(exp.metadata.status, "white")
        dt = _format_dt(exp.metadata.timestamp)
        desc = exp.metadata.description or ""
        summary = exp.metadata.summary or ""
        params = _params_line(exp.config)

        tag_part = ""
        if exp.metadata.tags:
            tags_display = ", ".join(exp.metadata.tags)
            tag_part = f" [magenta](tag: {tags_display})[/magenta]"
        disp_id = _display_id(exp.metadata.exp_id, full_id, short_len)
        lines.append(
            f"[yellow]experiment {disp_id}[/yellow]"
            f"{tag_part}"
            f" [[{status_color}]{exp.metadata.status}[/{status_color}]]"
        )

        if exp.metadata.parent_ids:
            for pid in exp.metadata.parent_ids:
                parent_short = pid[:short_len]
                lines.append(f"[dim]Parent: {parent_short}[/dim]")

        lines.append(f"Author: {getpass.getuser()}")
        lines.append(f"Date:   {dt}  |  Group: {exp.metadata.group}")
        lines.append("")

        # Prominent description at the top (first line only, indented)
        first_desc = _first_line(desc)
        if first_desc:
            lines.append(f"[bold cyan]Intent:[/bold cyan] {first_desc}")
        else:
            lines.append("[dim](No description provided)[/dim]")

        footer_parts = []
        if params:
            footer_parts.append(f"Params: [blue]{params}[/blue]")
        if metric_sort:
            name, _order, scores = metric_sort
            score = scores.get(exp.metadata.exp_id)
            score_str = f"{score:.4f}" if score is not None else "-"
            footer_parts.append(f"[yellow]{name}={score_str}[/yellow]")
        if footer_parts:
            lines.append("")
            lines.append(" | ".join(footer_parts))

        # Summary at the bottom for sealed experiments (first line only)
        first_summary = _first_line(summary)
        if first_summary:
            lines.append("")
            lines.append(f"[bold green]Conclusion:[/bold green] {first_summary}")

        lines.append("")
    return lines


def _build_oneline_lines(
    experiments: list[Experiment],
    full_id: bool,
    short_len: int,
    metric_sort: tuple[str, str, dict[str, float]] | None = None,
) -> list[str]:
    """Build compact one-line format for experiment list.

    Args:
        experiments: List of experiments to render.
        full_id: Whether to display full 16-character IDs.
        short_len: Number of characters for abbreviated IDs.
        metric_sort: Optional (name, order, exp_id->score) tuple.

    Returns:
        List of markup strings representing the oneline view.
    """
    lines: list[str] = []
    for exp in experiments:
        status_color = _STATUS_COLORS.get(exp.metadata.status, "white")
        status_label = exp.metadata.status.upper()
        disp_id = _display_id(exp.metadata.exp_id, full_id, short_len)
        dt = _oneline_dt(exp.metadata.timestamp)
        id_width = 16 if full_id else short_len

        raw_desc = exp.metadata.description or ""
        desc = _first_line(raw_desc) or "[dim](no description)[/dim]"

        tags_part = ""
        if exp.metadata.tags:
            tags = ", ".join(exp.metadata.tags)
            tags_part = f"[magenta]{tags}[/magenta]  "

        finished = ""
        if exp.metadata.finished_at:
            finished = _oneline_dt(exp.metadata.finished_at)
            finished = f"[dim]→ {finished:16}[/dim]  "

        line = (
            f"[yellow]{disp_id:{id_width}}[/yellow]  "
            f"[cyan]{dt:16}[/cyan]  "
            f"[{status_color}]{status_label:8}[/{status_color}]  "
            f"{finished}"
            f"[cyan]{exp.metadata.group:10}[/cyan]  "
            f"{tags_part}{desc}"
        )

        if metric_sort:
            name, _order, scores = metric_sort
            score = scores.get(exp.metadata.exp_id)
            score_str = f"{score:.4f}" if score is not None else "-"
            line += f"  [{name}={score_str}]"

        lines.append(line)
    return lines


def _build_tree_lines(
    roots: list[Experiment],
    children_map: dict[str, list[Experiment]],
    full_id: bool,
    short_len: int,
) -> list[str]:
    """Build experiment lineage tree lines.

    Args:
        roots: Root experiments (no parent in the set).
        children_map: Maps parent_id to child experiments.
        full_id: Whether to display full 16-character IDs.
        short_len: Number of characters for abbreviated IDs.

    Returns:
        List of markup strings representing the tree view.
    """
    lines: list[str] = []
    rendered: set[str] = set()

    def _render_node(
        exp: Experiment,
        prefix: str,
        is_last: bool,
        is_root: bool,
        path_ids: set[str],
    ) -> None:
        """Render a single tree node and its children recursively."""
        status_color = _STATUS_COLORS.get(exp.metadata.status, "white")
        status_label = exp.metadata.status.upper()
        disp_id = _display_id(exp.metadata.exp_id, full_id, short_len)
        raw_desc = exp.metadata.description or ""
        first_desc = _first_line(raw_desc)
        if first_desc:
            desc = first_desc if len(first_desc) <= 30 else first_desc[:27] + "..."
        else:
            desc = "[dim](no description)[/dim]"

        is_draft = not exp.metadata.attempts
        if is_draft:
            status_label = "DRAFT"
            status_color = "dim"

        multi_marker = ""
        if not is_root and len(exp.metadata.parent_ids) > 1:
            multi_marker = " [dim][multi-parent][/dim]"

        if is_root:
            connector = "○" if is_draft else "*"
        else:
            connector = "`-- o" if is_last else "|-- o"

        line = (
            f"{prefix}{connector} [yellow]{disp_id}[/yellow]  "
            f"[{status_color}]{status_label}[/{status_color}]  {desc}{multi_marker}"
        )
        lines.append(line)

        # Avoid cycles
        if exp.metadata.exp_id in path_ids:
            return

        # Only expand children on the first visit to avoid duplicated subtrees
        should_expand = exp.metadata.exp_id not in rendered
        rendered.add(exp.metadata.exp_id)
        if not should_expand:
            return

        children = children_map.get(exp.metadata.exp_id, [])
        for i, child in enumerate(children):
            child_is_last = i == len(children) - 1
            child_prefix = prefix + ("    " if is_last else "|   ")
            _render_node(
                child,
                child_prefix,
                child_is_last,
                is_root=False,
                path_ids=path_ids | {exp.metadata.exp_id},
            )

    for root in roots:
        _render_node(root, "", is_last=True, is_root=True, path_ids=set())
        lines.append("")

    return lines


@cli.command()
@click.option("--id", "exp_id", help="Experiment ID (defaults to current)")
@click.option(
    "--summary",
    "-s",
    default="",
    help="Mandatory conclusion reflecting on the experiment",
)
@click.option("--notes", "-n", default="", help="Additional post-mortem notes")
@click.pass_context
def finish(ctx: click.Context, exp_id: str | None, summary: str, notes: str) -> None:
    """Close an experiment and generate summary.md.

    Computes best metrics, determines final status from the last attempt's
    exit code, and writes a Markdown summary report.

    Status is determined automatically:
      - exit_code == 0        → success
      - exit_code != 0        → failed
      - exit_code is None     → aborted
    """
    summary = _require_text(
        summary,
        prompt="Write a conclusion reflecting on this experiment...",
        empty_msg=(
            "Experiment summary is required. Use --summary or run interactively."
        ),
        template=_CONCLUSION_TEMPLATE,
    )
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    resolved_id = _resolve_exp_id_or_default(exman, exp_id)

    try:
        exp = exman.finish(exp_id=resolved_id, notes=notes, summary=summary)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except LockedExperimentError as exc:
        raise click.ClickException(str(exc)) from exc
    except MissingSummaryError as exc:
        raise click.ClickException(str(exc)) from exc

    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = exp.metadata.exp_id[:short_len]
    status = exp.metadata.status
    status_color = _STATUS_COLORS.get(status, "white")

    status_line = (
        f"[bold {status_color}]Experiment {short_id} {status}.[/bold {status_color}]"
    )
    _echo_lines(
        ctx,
        [
            status_line,
            f"Status: {status}",
            f"Summary written to: {exp.root / 'summary.md'}",
        ],
    )


@cli.command()
@click.option("--id", "exp_id", help="Experiment ID (defaults to current)")
@click.option("--notes", "-n", default="", help="Additional post-mortem notes")
@click.pass_context
def abort(ctx: click.Context, exp_id: str | None, notes: str) -> None:
    """Abort an experiment and generate summary.md.

    Marks the last attempt as aborted (no exit code) and seals the lab
    record. No summary is required — the abort action itself is the
    statement that the experiment has no value.
    """
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    resolved_id = _resolve_exp_id_or_default(exman, exp_id)

    try:
        finished = exman.abort(exp_id=resolved_id, notes=notes)
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    except LockedExperimentError as exc:
        raise click.ClickException(str(exc)) from exc

    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = finished.metadata.exp_id[:short_len]
    _echo_lines(
        ctx,
        [
            f"[bold dim]Experiment {short_id} aborted.[/bold dim]",
            f"Summary written to: {finished.root / 'summary.md'}",
        ],
    )


@cli.command(name="status")
@click.option("--id", "exp_id", help="Experiment ID (defaults to current)")
@click.option(
    "--full-id",
    is_flag=True,
    help="Display full 16-character experiment ID",
)
@click.pass_context
def status(ctx: click.Context, exp_id: str | None, full_id: bool) -> None:
    """Display a detailed summary of a specific experiment.

    Shows metadata, configuration, and best metrics in a structured
    panel layout.
    """
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    resolved_id = _resolve_exp_id_or_default(exman, exp_id)
    exp = exman.get(resolved_id)

    if exp is None:
        raise click.ClickException(f"Experiment '{resolved_id}' not found.")

    best_metrics = exp.compute_best_metrics()
    short_len = cfg_mgr.get("short_id_length", 8)
    disp_id = _display_id(exp.metadata.exp_id, full_id, short_len)

    lines: list[str] = [
        f"[bold cyan]ID:[/bold cyan] {disp_id}",
        f"[bold cyan]Group:[/bold cyan] {exp.metadata.group}",
        f"[bold cyan]Status:[/bold cyan] {exp.metadata.status}",
        f"[bold cyan]Description:[/bold cyan] {exp.metadata.description or '-'}",
        f"[bold cyan]Summary:[/bold cyan] {exp.metadata.summary or '-'}",
        f"[bold cyan]Data Version:[/bold cyan] {exp.metadata.data_version or '-'}",
        f"[bold cyan]Data Hash:[/bold cyan] {exp.metadata.data_hash or 'N/A'}",
        f"[bold cyan]Git Hash:[/bold cyan] {exp.metadata.git_hash or 'N/A'}",
        f"[bold cyan]Git Dirty:[/bold cyan] {exp.metadata.git_dirty}",
    ]
    if exp.metadata.parent_ids:
        for pid in exp.metadata.parent_ids:
            parent_disp = _display_id(pid, full_id, short_len)
            lines.append(f"[bold cyan]Parent:[/bold cyan] {parent_disp}")
    lines.append(f"[bold cyan]Path:[/bold cyan] {exp.root}")
    lines.append("")

    if exp.config:
        lines.append("[bold blue]Config:[/bold blue]")
        for key, value in exp.config.items():
            lines.append(f"  {key}: {value}")
    else:
        lines.append("[dim]Config: No config recorded.[/dim]")
    lines.append("")

    if best_metrics:
        lines.append("[bold magenta]Best Metrics:[/bold magenta]")
        lines.append(f"{'Metric':<20} {'Best (Max)':>12} {'Worst (Min)':>12}")
        for key, vals in best_metrics.items():
            lines.append(f"{key:<20} {vals['max']:>12.6f} {vals['min']:>12.6f}")
    else:
        lines.append("[dim]Best Metrics: No metrics recorded.[/dim]")

    if exp.metadata.attempts:
        lines.append("")
        lines.append("[bold yellow]Attempts:[/bold yellow]")
        lines.append(f"{'Run':<10} {'Start':<20} {'End':<20} {'Status':<12} Command")
        for att in exp.metadata.attempts:
            name = att.reason or f"run_{att.sequence}"
            start = att.start_time[:19] if att.start_time else "-"
            end = att.end_time[:19] if att.end_time else "-"
            cmd = " ".join(att.command) if att.command else "-"
            if len(cmd) > 40:
                cmd = cmd[:37] + "..."
            lines.append(f"{name:<10} {start:<20} {end:<20} {att.status:<12} {cmd}")

    _echo_lines(ctx, lines)


@cli.command(name="tag")
@click.argument("tag_name", required=False)
@click.option("--id", "exp_id", help="Experiment ID (defaults to current)")
@click.option("--delete", "-d", is_flag=True, help="Remove the tag")
@click.option("--list", "-l", is_flag=True, help="List all tags with counts")
@click.option("--group", help="Filter tags to a specific group")
@click.pass_context
def tag_cmd(
    ctx: click.Context,
    tag_name: str,
    exp_id: str | None,
    delete: bool,
    list: bool,
    group: str | None,
) -> None:
    """Add, remove, or list tags.

    Usage:
        kai-exman tag <tag_name>                    # add tag to default exp
        kai-exman tag <tag_name> --id <exp_id>      # add tag to specific exp
        kai-exman tag -d <tag_name>                 # remove tag from default exp
        kai-exman tag -d <tag_name> --id <exp_id>   # remove tag from specific exp
        kai-exman tag -l                            # list all tags
        kai-exman tag -l --group <group>            # list tags in a group
    """
    if list:
        _list_tags(ctx, group)
        return

    if not tag_name:
        raise click.ClickException("TAG_NAME is required. Use -l to list tags.")

    _validate_tag(tag_name)
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    resolved_id = _resolve_exp_id_or_default(exman, exp_id)
    exp = exman.get(resolved_id)

    if exp is None:
        raise click.ClickException(f"Experiment '{resolved_id}' not found.")

    if delete:
        exp.remove_tag(tag_name)
        action = "removed from"
    else:
        exp.add_tag(tag_name)
        action = "added to"

    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = resolved_id[:short_len]
    _echo_lines(
        ctx,
        [f"[bold green]Tag '{tag_name}' {action} {short_id}.[/bold green]"],
    )


def _list_tags(ctx: click.Context, group: str | None) -> None:
    """List all tags across experiments, optionally filtered by group."""
    exman = ExMan(root=ctx.obj["path"])
    experiments = exman.list(group=group)

    tag_counts: dict[str, int] = {}
    tag_groups: dict[str, dict[str, int]] = {}

    for exp in experiments:
        for tag in exp.metadata.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
            tag_groups.setdefault(tag, {})
            tag_groups[tag][exp.metadata.group] = (
                tag_groups[tag].get(exp.metadata.group, 0) + 1
            )

    if not tag_counts:
        click.echo("No tags found.")
        return

    lines: list[str] = []
    header = f"[bold]{'Tag':<20} {'Count':>5}[/bold]"
    if group is None:
        header += "  [bold]Groups[/bold]"
    lines.append(header)

    for tag in sorted(tag_counts.keys()):
        count = tag_counts[tag]
        if group is None:
            group_parts = [f"{g}({c})" for g, c in sorted(tag_groups[tag].items())]
            lines.append(f"{tag:<20} {count:>5}  {', '.join(group_parts)}")
        else:
            lines.append(f"{tag:<20} {count:>5}")

    _echo_lines(ctx, lines, use_pager=True)


@cli.command()
@click.option("--id", "exp_id", help="Experiment ID (defaults to current)")
@click.option("--group", "-g", required=True, help="Target group name")
@click.pass_context
def move(ctx: click.Context, exp_id: str | None, group: str) -> None:
    """Move an experiment to a different group."""
    _validate_group(group)
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    resolved_id = _resolve_exp_id_or_default(exman, exp_id)

    try:
        exp = exman.move(resolved_id, group)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = exp.metadata.exp_id[:short_len]
    _echo_lines(
        ctx,
        [
            f"[bold green]Experiment {short_id} moved to group "
            f"'{exp.metadata.group}'.[/bold green]"
        ],
    )


@cli.command()
@click.argument("exp_id")
@click.pass_context
def use(ctx: click.Context, exp_id: str) -> None:
    """Set the default experiment for the current root."""
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    resolved_id = _resolve_exp_id(exman, exp_id)

    exp = exman.get(resolved_id)
    if exp is None:
        raise click.ClickException(f"Experiment '{resolved_id}' not found.")

    exman.set_default_exp_id(resolved_id)
    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = resolved_id[:short_len]
    _echo_lines(
        ctx,
        [f"[bold green]Default experiment set to {short_id}.[/bold green]"],
    )


@cli.command(name="group")
@click.option("-l", "--list", "list_flag", is_flag=True, help="List all groups")
@click.option(
    "--threshold",
    type=float,
    help="Jaccard similarity threshold (default: from config)",
)
@click.option("--apply", is_flag=True, help="Apply suggested group moves")
@click.pass_context
def group_cmd(
    ctx: click.Context,
    list_flag: bool,
    threshold: float | None,
    apply: bool,
) -> None:
    """Manage experiment groups.

    With no flags: suggest group assignments based on config key similarity.
    With -l: list all existing groups and experiment counts.
    """
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)

    if list_flag:
        experiments = exman.list()
        if not experiments:
            click.echo("No experiments found.")
            return

        group_counts: dict[str, int] = {}
        for exp in experiments:
            group_counts[exp.metadata.group] = (
                group_counts.get(exp.metadata.group, 0) + 1
            )

        lines: list[str] = []
        lines.append(f"[bold]{'Group':<20} {'Experiments':>11}[/bold]")
        for group, count in sorted(group_counts.items()):
            lines.append(f"{group:<20} {count:>11}")

        _echo_lines(ctx, lines)
        return

    if threshold is not None:
        # Temporarily override config for this run
        original = exman.config._config.get("cluster_threshold")
        exman.config._config["cluster_threshold"] = threshold

    suggestions = exman.suggest_groups()

    if threshold is not None and original is not None:
        exman.config._config["cluster_threshold"] = original

    if not suggestions:
        click.echo("No group suggestions above the similarity threshold.")
        return

    lines = []
    lines.append(
        f"[bold]{'Experiment':<12} {'Current':<12} {'Suggested':<12} Similarity[/bold]"
    )
    short_len = cfg_mgr.get("short_id_length", 8)
    for exp, suggested_group, score in suggestions:
        short_id = exp.metadata.exp_id[:short_len]
        lines.append(
            f"{short_id:<12} {exp.metadata.group:<12} {suggested_group:<12} {score:.2f}"
        )

    _echo_lines(ctx, lines)

    if apply:
        if not sys.stdout.isatty():
            raise click.ClickException(
                "Non-TTY operation requires explicit confirmation. "
                "Use --apply in an interactive terminal, or use 'move' directly."
            )
        if not click.confirm("Apply suggested group moves?"):
            click.echo("Aborted.")
            return

        for exp, suggested_group, _score in suggestions:
            exman.move(exp.metadata.exp_id, suggested_group)
            short_id = exp.metadata.exp_id[: cfg_mgr.get("short_id_length", 8)]
            click.echo(f"Moved {short_id} to group '{suggested_group}'.")


@cli.command()
@click.argument("exp_id", required=False)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option("--dry-run", is_flag=True, help="Show what would happen without acting")
@click.option("--clear-trash", is_flag=True, help="Permanently empty the trash")
@click.option(
    "--mark-deletable",
    is_flag=True,
    help="Mark experiment for automatic removal when children are gone",
)
@click.pass_context
def rm(
    ctx: click.Context,
    exp_id: str | None,
    yes: bool,
    dry_run: bool,
    clear_trash: bool,
    mark_deletable: bool,
) -> None:
    """Remove an experiment to trash, or empty the trash.

    Experiments are moved to ``.trash/`` rather than deleted permanently.
    Parent experiments with children cannot be removed directly; use
    ``--mark-deletable`` to schedule them for cascade removal.

    Auto-purges the oldest trashed items if capacity limits are exceeded.
    """
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)

    if clear_trash:
        items = exman.clear_trash(dry_run=True)
        if not items:
            click.echo("Trash is already empty.")
            return

        if not dry_run and not yes:
            if sys.stdout.isatty():
                click.echo(
                    f"This will permanently delete {len(items)} trashed experiment(s)."
                )
                if not click.confirm("Proceed?"):
                    click.echo("Aborted.")
                    return
            else:
                raise click.ClickException(
                    "Non-TTY operation requires --yes to clear trash. "
                    "Use --dry-run to preview."
                )

        if not dry_run:
            items = exman.clear_trash(dry_run=False)

        for path in items:
            action = "would delete" if dry_run else "deleted"
            click.echo(f"{action}: {path.name}")
        return

    if exp_id is None:
        raise click.ClickException("EXP_ID is required unless --clear-trash is used.")

    resolved_id = _resolve_exp_id(exman, exp_id)
    exp = exman.get(resolved_id)
    if exp is None:
        raise click.ClickException(f"Experiment '{resolved_id}' not found.")

    short_len = cfg_mgr.get("short_id_length", 8)

    if mark_deletable:
        if dry_run:
            click.echo(f"Would mark experiment {resolved_id[:short_len]} as deletable.")
            return
        exman.mark_deletable(resolved_id)
        click.echo(f"Marked experiment {resolved_id[:short_len]} as deletable.")
        return

    if not dry_run and not yes:
        if sys.stdout.isatty():
            click.echo(
                f"This will move experiment '{resolved_id[:short_len]}' to trash."
            )
            if not click.confirm("Proceed?"):
                click.echo("Aborted.")
                return
        else:
            raise click.ClickException(
                "Non-TTY operation requires --yes to remove. Use --dry-run to preview."
            )

    try:
        removed_exp, purged = exman.remove(resolved_id, dry_run=dry_run)
    except ValueError as exc:
        msg = str(exc)
        if "child experiment" in msg.lower():
            raise click.ClickException(
                f"{msg} Use --mark-deletable to schedule cascade removal."
            ) from exc
        raise click.ClickException(msg) from exc

    for path in purged:
        action = "would purge" if dry_run else "purged"
        click.echo(f"{action}: {path.name}")

    if removed_exp is not None:
        short_id = removed_exp.metadata.exp_id[:short_len]
        action = "would move" if dry_run else "moved"
        click.echo(f"{action} experiment {short_id} to trash.")


def main() -> None:
    """CLI entry point."""
    cli()
