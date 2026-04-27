"""Kai-Exman CLI entry point.

Provides a Click-based command-line interface for experiment management
with git-log-style output, smart TTY detection, and Rich terminal rendering.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from kaiexman.config import ConfigManager
from kaiexman.experiment import Experiment, validate_group, validate_tag
from kaiexman.manager import ExMan


class AliasedGroup(click.Group):
    """Click group with command aliases.

    Attributes:
        _aliases: Mapping of alias names to canonical command names.
    """

    _aliases = {"log": "list"}

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


def _get_console(ctx: click.Context) -> Console:
    """Build a Rich Console appropriate for the current context.

    Args:
        ctx: Click context containing CLI options.

    Returns:
        A configured Rich Console instance.
    """
    return Console(
        force_terminal=_use_color(ctx),
        color_system="truecolor" if _use_color(ctx) else None,
    )


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
@click.pass_context
def init(
    ctx: click.Context,
    description: str,
    tags: str,
    config: str | None,
    group: str,
) -> None:
    """Initialize a new experiment.

    Creates a directory structure, captures Git state, and optionally
    loads a YAML configuration file.
    """
    _validate_group(group)
    cfg = None
    if config and Path(config).exists():
        with open(config, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    exp = exman.init(description=description, tags=tag_list, config=cfg, group=group)

    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = exp.metadata.exp_id[:short_len]

    if sys.stdout.isatty():
        console = _get_console(ctx)
        table = Table(show_header=False, box=None)
        table.add_row("[bold]Experiment ID:[/bold]", short_id)
        table.add_row("[bold]Path:[/bold]", str(exp.root))
        table.add_row("[bold]Group:[/bold]", exp.metadata.group)
        table.add_row("[bold]Git Hash:[/bold]", exp.metadata.git_hash or "N/A")
        table.add_row("[bold]Status:[/bold]", exp.metadata.status)
        if exp.metadata.git_dirty:
            table.add_row(
                "[bold yellow]Warning:[/bold yellow]",
                "Working tree has uncommitted changes",
            )

        console.print(
            Panel(
                table,
                title="[bold green]Experiment Initialized[/bold green]",
                border_style="green",
            )
        )
    else:
        click.echo("Experiment Initialized")
        click.echo(f"Experiment ID: {short_id}")
        click.echo(f"Path: {exp.root}")
        click.echo(f"Group: {exp.metadata.group}")
        click.echo(f"Git Hash: {exp.metadata.git_hash or 'N/A'}")
        click.echo(f"Status: {exp.metadata.status}")
        if exp.metadata.git_dirty:
            click.echo("Warning: Working tree has uncommitted changes")


@cli.command()
@click.option("--resume", help="Resume from experiment ID")
@click.option("--description", "-d", default="", help="Experiment description")
@click.option("--tags", "-t", default="", help="Comma-separated tags")
@click.option("--config", "-c", help="Path to config YAML file")
@click.option("--group", "-g", help="Group for new experiment (Case B resume)")
@click.argument("command", nargs=-1, required=True)
@click.pass_context
def run(
    ctx: click.Context,
    resume: str | None,
    description: str,
    tags: str,
    config: str | None,
    group: str | None,
    command: tuple[str, ...],
) -> None:
    """Run a command within an experiment context.

    Creates a new experiment (or resumes an existing one) and executes the
    provided command with KAI_EXMAN_* environment variables set.

    Usage:
        kai-exman run -- python train.py
        kai-exman run --resume <exp_id> -- python train.py
    """
    cfg = None
    if config and Path(config).exists():
        with open(config, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)

    if resume:
        resolved_id = _resolve_exp_id(exman, resume)
        exp, is_new, attempt_num = exman.resume(
            exp_id=resolved_id,
            description=description,
            tags=tag_list or None,
            config=cfg,
            group=group,
        )
    else:
        if group is not None:
            _validate_group(group)
        exp = exman.init(
            description=description,
            tags=tag_list,
            config=cfg,
            group=group or "default",
        )
        is_new = True
        attempt_num = 1

    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = exp.metadata.exp_id[:short_len]

    # Set resume environment variables
    env = os.environ.copy()
    env["KAI_EXMAN_RESUME"] = "1"
    env["KAI_EXMAN_ATTEMPT_COUNT"] = str(attempt_num)
    if resume and not is_new:
        env["KAI_EXMAN_PARENT_PATH"] = str(exp.root)
    elif resume and is_new:
        parent = exman.get(resolved_id)
        if parent is not None:
            env["KAI_EXMAN_PARENT_PATH"] = str(parent.root)

    if sys.stdout.isatty():
        console = _get_console(ctx)
        if is_new and resume:
            msg = (
                f"[bold green]Creating new experiment {short_id} "
                f"inherited from {resolved_id[:short_len]}.[/bold green]"
            )
        elif resume:
            msg = (
                f"[bold blue]Resuming experiment {short_id} "
                f"(attempt {attempt_num}).[/bold blue]"
            )
        else:
            msg = f"[bold green]Running experiment {short_id}.[/bold green]"
        console.print(msg)
    else:
        if is_new and resume:
            click.echo(
                f"Creating new experiment {short_id} inherited from "
                f"{resolved_id[:short_len]}."
            )
        elif resume:
            click.echo(f"Resuming experiment {short_id} (attempt {attempt_num}).")
        else:
            click.echo(f"Running experiment {short_id}.")

    # Execute the command
    result = subprocess.run(command, env=env)

    # Update attempt record if resuming
    if resume and not is_new and exp.metadata.attempts:
        last_attempt = exp.metadata.attempts[-1]
        last_attempt.end_time = datetime.now().isoformat()
        last_attempt.exit_code = result.returncode
        last_attempt.status = "success" if result.returncode == 0 else "failed"
        # Promote global status from latest attempt
        exp.metadata.status = last_attempt.status
        exp.write_metadata()

    # Update overall status for new experiments
    if is_new:
        exp.update_status(
            "success" if result.returncode == 0 else "failed"
        )

    sys.exit(result.returncode)


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
    help="Display experiments grouped by group in tree view",
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
    top: int | None,
    oneline: bool,
    tag_filter: str | None,
    group_filter: str | None,
    tree: bool,
    full_id: bool,
) -> None:
    """List experiments, optionally sorted by a metric.

    Displays experiments in a git-log-style format. In a TTY, uses
    Rich for colors and a pager; otherwise outputs plain text.
    """
    exman = ExMan(root=ctx.obj["path"])
    experiments = exman.list(group=group_filter)

    if tag_filter:
        experiments = [e for e in experiments if tag_filter in e.metadata.tags]

    if not experiments:
        click.echo("No experiments found.")
        return

    scored = []
    for exp in experiments:
        best = exp.compute_best_metrics()
        score = None
        if sort_by and sort_by in best:
            score = best[sort_by]["max"] if order == "desc" else best[sort_by]["min"]
        scored.append((exp, best, score))

    if sort_by:
        scored.sort(
            key=lambda x: (x[2] is None, x[2] or 0),
            reverse=False if order == "asc" else True,
        )

    if top:
        scored = scored[:top]

    short_len = ctx.obj["config"].get("short_id_length", 8)
    if tree:
        if _use_pager(ctx):
            _list_tree_rich(ctx, scored, full_id, short_len)
        else:
            _list_tree_plain(scored, full_id, short_len)
    elif _use_pager(ctx):
        _list_rich(ctx, scored, sort_by, order, oneline, full_id, short_len)
    else:
        _list_plain(scored, sort_by, order, oneline, full_id, short_len)


_STATUS_COLORS = {
    "success": "green",
    "running": "blue",
    "failed": "red",
    "finished": "green",
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


def _list_tree_rich(
    ctx: click.Context,
    scored: list[tuple[Experiment, dict[str, dict[str, float]], float | None]],
    full_id: bool,
    short_length: int,
) -> None:
    """Render experiment list in tree view with Rich.

    Args:
        ctx: Click context for color settings.
        scored: List of (experiment, best_metrics, score) tuples.
        full_id: Whether to display full 16-character IDs.
        short_length: Number of characters for abbreviated IDs.
    """
    console = Console(force_terminal=True, record=True)

    # Group experiments by group name
    groups: dict[str, list[tuple[Experiment, Any, Any]]] = {}
    for item in scored:
        g = item[0].metadata.group
        groups.setdefault(g, []).append(item)

    for group_name in sorted(groups.keys()):
        console.print(f"[bold cyan]{group_name}/[/bold cyan]")
        for exp, _best, _score in groups[group_name]:
            status_color = _STATUS_COLORS.get(exp.metadata.status, "white")
            prefix = "-> " if exp.metadata.parent_id else "    "
            disp_id = _display_id(exp.metadata.exp_id, full_id, short_length)
            desc = exp.metadata.description or "[dim](no description)[/dim]"
            tags_part = ""
            if exp.metadata.tags:
                tags_display = ", ".join(exp.metadata.tags)
                tags_part = f" [bold magenta][{tags_display}][/bold magenta]"
            line = (
                f"{prefix}[yellow]{disp_id}[/yellow]  "
                f"[{status_color}]{exp.metadata.status}[/{status_color}]  "
                f"{desc}{tags_part}"
            )
            console.print(line)
            if exp.metadata.attempts:
                attempt_strs = [
                    f"{a.reason or f'run_{a.sequence}'} ({a.status})"
                    for a in exp.metadata.attempts
                ]
                console.print(f"        Attempts: {', '.join(attempt_strs)}")
        console.print("")

    text = console.export_text(styles=True)
    os.environ.setdefault("LESS", "-R")
    click.echo_via_pager(text)


def _list_tree_plain(
    scored: list[tuple[Experiment, dict[str, dict[str, float]], float | None]],
    full_id: bool,
    short_length: int,
) -> None:
    """Render experiment list in tree view as plain text.

    Args:
        scored: List of (experiment, best_metrics, score) tuples.
        full_id: Whether to display full 16-character IDs.
        short_length: Number of characters for abbreviated IDs.
    """
    groups: dict[str, list[tuple[Experiment, Any, Any]]] = {}
    for item in scored:
        g = item[0].metadata.group
        groups.setdefault(g, []).append(item)

    for group_name in sorted(groups.keys()):
        click.echo(f"{group_name}/")
        for exp, _best, _score in groups[group_name]:
            prefix = "-> " if exp.metadata.parent_id else "    "
            disp_id = _display_id(exp.metadata.exp_id, full_id, short_length)
            desc = exp.metadata.description or "(no description)"
            tags_part = ""
            if exp.metadata.tags:
                tags_display = ", ".join(exp.metadata.tags)
                tags_part = f" [{tags_display}]"
            line = (
                f"{prefix}{disp_id}  {exp.metadata.status}  {desc}{tags_part}"
            )
            click.echo(line)
            if exp.metadata.attempts:
                attempt_strs = [
                    f"{a.reason or f'run_{a.sequence}'} ({a.status})"
                    for a in exp.metadata.attempts
                ]
                click.echo(f"        Attempts: {', '.join(attempt_strs)}")
        click.echo("")


def _list_rich(
    ctx: click.Context,
    scored: list[tuple[Experiment, dict[str, dict[str, float]], float | None]],
    sort_by: str | None,
    order: str,
    oneline: bool,
    full_id: bool,
    short_length: int,
) -> None:
    """Render experiment list with Rich and pipe through a pager.

    Args:
        ctx: Click context for color settings.
        scored: List of (experiment, best_metrics, score) tuples.
        sort_by: Metric name used for sorting, if any.
        order: Sort order string ("asc" or "desc").
        oneline: Whether to use compact one-line output.
        full_id: Whether to display full 16-character IDs.
        short_length: Number of characters for abbreviated IDs.
    """
    console = Console(force_terminal=True, record=True)

    if oneline:
        for exp, _best, score in scored:
            date_str = _oneline_dt(exp.metadata.timestamp)
            status_color = _STATUS_COLORS.get(exp.metadata.status, "white")
            status_label = exp.metadata.status.upper()

            if exp.metadata.description:
                desc = exp.metadata.description
            else:
                desc = "[dim](no description)[/dim]"

            tags_part = ""
            if exp.metadata.tags:
                tags_display = ", ".join(exp.metadata.tags)
                tags_part = f"[bold magenta][{tags_display}][/bold magenta]  "

            prefix = "[dim]->[/dim] " if exp.metadata.parent_id else ""
            disp_id = _display_id(exp.metadata.exp_id, full_id, short_length)
            id_width = 16 if full_id else short_length
            line = (
                f"{prefix}[yellow]{disp_id:{id_width}}[/yellow]  "
                f"[cyan]{date_str:16}[/cyan]  "
                f"[{status_color}]{status_label:10}[/{status_color}]  "
                f"{tags_part}"
                f"{desc}"
            )
            if sort_by:
                score_str = f"{score:.4f}" if score is not None else "-"
                line += f"  [{sort_by}={score_str}]"
            console.print(line)
    else:
        for exp, _best, score in scored:
            status_color = _STATUS_COLORS.get(exp.metadata.status, "white")
            dt = _format_dt(exp.metadata.timestamp)
            desc = exp.metadata.description or ""
            params = _params_line(exp.config)

            # Header: experiment <hash> (tag: ...) [status]
            tag_part = ""
            if exp.metadata.tags:
                tags_display = ", ".join(exp.metadata.tags)
                tag_part = f" [magenta](tag: {tags_display})[/magenta]"
            prefix = "-> " if exp.metadata.parent_id else ""
            disp_id = _display_id(exp.metadata.exp_id, full_id, short_length)
            console.print(
                f"{prefix}[yellow]experiment {disp_id}[/yellow]"
                f"{tag_part}"
                f" [[{status_color}]{exp.metadata.status}[/{status_color}]]"
            )

            if exp.metadata.parent_id:
                parent_short = exp.metadata.parent_id[:short_length]
                console.print(
                    f"    [dim]inherited from {parent_short}[/dim]"
                )

            # Metadata
            author = getpass.getuser()
            console.print(f"Author: {author}")
            console.print(f"Date:   {dt}")

            # Body: blank line, then indented description
            console.print("")
            if desc:
                console.print(f"    {desc}")
            else:
                console.print("    [dim](No description provided)[/dim]")

            # Footer: indented params / score
            footer_parts = []
            if params:
                footer_parts.append(f"Params: [blue]{params}[/blue]")
            if sort_by:
                score_str = f"{score:.4f}" if score is not None else "-"
                footer_parts.append(f"[yellow]{sort_by}={score_str}[/yellow]")
            if footer_parts:
                console.print("")
                console.print(f"    {' | '.join(footer_parts)}")

            # Blank line between experiments
            console.print("")

    text = console.export_text(styles=True)
    os.environ.setdefault("LESS", "-R")
    click.echo_via_pager(text)


def _list_plain(
    scored: list[tuple[Experiment, dict[str, dict[str, float]], float | None]],
    sort_by: str | None,
    order: str,
    oneline: bool,
    full_id: bool,
    short_length: int,
) -> None:
    """Render experiment list as plain text.

    Args:
        scored: List of (experiment, best_metrics, score) tuples.
        sort_by: Metric name used for sorting, if any.
        order: Sort order string ("asc" or "desc").
        oneline: Whether to use compact one-line output.
        full_id: Whether to display full 16-character IDs.
        short_length: Number of characters for abbreviated IDs.
    """
    if oneline:
        for exp, _best, score in scored:
            date_str = _oneline_dt(exp.metadata.timestamp)
            status_label = exp.metadata.status.upper()
            desc = exp.metadata.description or "(no description)"

            tags_part = ""
            if exp.metadata.tags:
                tags_display = ", ".join(exp.metadata.tags)
                tags_part = f"[{tags_display}]  "

            prefix = "-> " if exp.metadata.parent_id else ""
            disp_id = _display_id(exp.metadata.exp_id, full_id, short_length)
            id_width = 16 if full_id else short_length
            line = (
                f"{prefix}{disp_id:{id_width}}  {date_str:16}  {status_label:10}  "
                f"{tags_part}{desc}"
            )
            if sort_by:
                score_str = f"{score:.4f}" if score is not None else "-"
                line += f"  [{sort_by}={score_str}]"
            click.echo(line)
    else:
        for exp, _best, score in scored:
            dt = _format_dt(exp.metadata.timestamp)
            desc = exp.metadata.description or ""
            params = _params_line(exp.config)

            # Header
            tag_part = ""
            if exp.metadata.tags:
                tags_display = ", ".join(exp.metadata.tags)
                tag_part = f" (tag: {tags_display})"
            prefix = "-> " if exp.metadata.parent_id else ""
            disp_id = _display_id(exp.metadata.exp_id, full_id, short_length)
            status_part = f"[{exp.metadata.status}]"
            click.echo(f"{prefix}experiment {disp_id}{tag_part} {status_part}")
            if exp.metadata.parent_id:
                parent_short = exp.metadata.parent_id[:short_length]
                click.echo(f"    inherited from {parent_short}")
            click.echo(f"Author: {getpass.getuser()}")
            click.echo(f"Date:   {dt}")
            click.echo("")
            if desc:
                click.echo(f"    {desc}")
            else:
                click.echo("    (No description provided)")

            footer_parts = []
            if params:
                footer_parts.append(f"Params: {params}")
            if sort_by:
                score_str = f"{score:.4f}" if score is not None else "-"
                footer_parts.append(f"{sort_by}={score_str}")
            if footer_parts:
                click.echo("")
                click.echo(f"    {' | '.join(footer_parts)}")

            click.echo("")


@cli.command()
@click.argument("exp_id")
@click.option("--status", "-s", default="finished", help="Final status")
@click.option("--notes", "-n", default="", help="Post-mortem notes")
@click.pass_context
def finish(ctx: click.Context, exp_id: str, status: str, notes: str) -> None:
    """Close an experiment and generate summary.md.

    Computes best metrics, updates status, and writes a Markdown summary
    report to the experiment directory.
    """
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    resolved_id = _resolve_exp_id(exman, exp_id)
    exp = exman.finish(exp_id=resolved_id, status=status, notes=notes)

    if exp is None:
        raise click.ClickException(f"Experiment '{resolved_id}' not found.")

    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = exp.metadata.exp_id[:short_len]

    if sys.stdout.isatty():
        console = _get_console(ctx)
        console.print(
            Panel(
                f"[bold green]Experiment {short_id} finished.[/bold green]\n"
                f"Status: {status}\n"
                f"Summary written to: {exp.root / 'summary.md'}",
                title="Finish",
                border_style="green",
            )
        )
    else:
        click.echo(f"Experiment {short_id} finished.")
        click.echo(f"Status: {status}")
        click.echo(f"Summary written to: {exp.root / 'summary.md'}")


@cli.command()
@click.argument("exp_id")
@click.option(
    "--full-id",
    is_flag=True,
    help="Display full 16-character experiment ID",
)
@click.pass_context
def show(ctx: click.Context, exp_id: str, full_id: bool) -> None:
    """Display a detailed summary of a specific experiment.

    Shows metadata, configuration, and best metrics in a structured
    panel layout.
    """
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    resolved_id = _resolve_exp_id(exman, exp_id)
    exp = exman.get(resolved_id)

    if exp is None:
        raise click.ClickException(f"Experiment '{resolved_id}' not found.")

    best_metrics = exp.compute_best_metrics()
    short_len = cfg_mgr.get("short_id_length", 8)
    disp_id = _display_id(exp.metadata.exp_id, full_id, short_len)

    if sys.stdout.isatty():
        console = _get_console(ctx)

        meta_table = Table(show_header=False, box=None)
        meta_table.add_row("[bold]ID[/bold]", disp_id)
        meta_table.add_row("[bold]Group[/bold]", exp.metadata.group)
        meta_table.add_row("[bold]Status[/bold]", exp.metadata.status)
        meta_table.add_row("[bold]Description[/bold]", exp.metadata.description or "-")
        meta_table.add_row(
            "[bold]Data Version[/bold]", exp.metadata.data_version or "-"
        )
        meta_table.add_row("[bold]Git Hash[/bold]", exp.metadata.git_hash or "N/A")
        meta_table.add_row("[bold]Git Dirty[/bold]", str(exp.metadata.git_dirty))
        if exp.metadata.parent_id:
            parent_disp = _display_id(
                exp.metadata.parent_id, full_id, short_len
            )
            meta_table.add_row("[bold]Parent[/bold]", parent_disp)
        meta_table.add_row("[bold]Path[/bold]", str(exp.root))

        meta_panel = Panel(
            meta_table, title="[bold cyan]Metadata[/bold cyan]", border_style="cyan"
        )

        if exp.config:
            cfg_table = Table(show_header=False, box=None)
            for key, value in exp.config.items():
                cfg_table.add_row(f"[bold]{key}[/bold]", str(value))
            cfg_panel = Panel(
                cfg_table, title="[bold blue]Config[/bold blue]", border_style="blue"
            )
        else:
            cfg_panel = Panel(
                "[dim]No config recorded.[/dim]",
                title="[bold blue]Config[/bold blue]",
                border_style="blue",
            )

        if best_metrics:
            metrics_table = Table(show_header=True, header_style="bold magenta")
            metrics_table.add_column("Metric")
            metrics_table.add_column("Best (Max)", justify="right")
            metrics_table.add_column("Worst (Min)", justify="right")
            for key, vals in best_metrics.items():
                metrics_table.add_row(key, f"{vals['max']:.6f}", f"{vals['min']:.6f}")
            metrics_panel = Panel(
                metrics_table,
                title="[bold magenta]Best Metrics[/bold magenta]",
                border_style="magenta",
            )
        else:
            metrics_panel = Panel(
                "[dim]No metrics recorded.[/dim]",
                title="[bold magenta]Best Metrics[/bold magenta]",
                border_style="magenta",
            )

        panels = [meta_panel, cfg_panel, metrics_panel]

        if exp.metadata.attempts:
            attempts_table = Table(show_header=True, header_style="bold yellow")
            attempts_table.add_column("Run")
            attempts_table.add_column("Start")
            attempts_table.add_column("End")
            attempts_table.add_column("Status")
            for att in exp.metadata.attempts:
                name = att.reason or f"run_{att.sequence}"
                attempts_table.add_row(
                    name,
                    att.start_time[:19] if att.start_time else "-",
                    att.end_time[:19] if att.end_time else "-",
                    att.status,
                )
            attempts_panel = Panel(
                attempts_table,
                title="[bold yellow]Attempts[/bold yellow]",
                border_style="yellow",
            )
            panels.append(attempts_panel)

        for panel in panels:
            console.print(panel)
    else:
        click.echo(f"ID: {disp_id}")
        click.echo(f"Group: {exp.metadata.group}")
        click.echo(f"Status: {exp.metadata.status}")
        click.echo(f"Description: {exp.metadata.description or '-'}")
        click.echo(f"Data Version: {exp.metadata.data_version or '-'}")
        click.echo(f"Git Hash: {exp.metadata.git_hash or 'N/A'}")
        click.echo(f"Git Dirty: {exp.metadata.git_dirty}")
        if exp.metadata.parent_id:
            click.echo(f"Parent: {exp.metadata.parent_id[:short_len]}")
        click.echo(f"Path: {exp.root}")
        click.echo("")
        if exp.config:
            click.echo("Config:")
            for key, value in exp.config.items():
                click.echo(f"  {key}: {value}")
        else:
            click.echo("Config: No config recorded.")
        click.echo("")
        if best_metrics:
            click.echo("Best Metrics:")
            click.echo(f"{'Metric':<20} {'Best (Max)':>12} {'Worst (Min)':>12}")
            for key, vals in best_metrics.items():
                click.echo(f"{key:<20} {vals['max']:>12.6f} {vals['min']:>12.6f}")
        else:
            click.echo("Best Metrics: No metrics recorded.")
        if exp.metadata.attempts:
            click.echo("")
            click.echo("Attempts:")
            click.echo(
                f"{'Run':<10} {'Start':<20} {'End':<20} {'Status'}"
            )
            for att in exp.metadata.attempts:
                name = att.reason or f"run_{att.sequence}"
                start = att.start_time[:19] if att.start_time else "-"
                end = att.end_time[:19] if att.end_time else "-"
                click.echo(
                    f"{name:<10} {start:<20} {end:<20} {att.status}"
                )


@cli.command(name="tag")
@click.argument("exp_id")
@click.argument("tag_name")
@click.option("--delete", "-d", is_flag=True, help="Remove the tag")
@click.pass_context
def tag_cmd(
    ctx: click.Context,
    exp_id: str,
    tag_name: str,
    delete: bool,
) -> None:
    """Add or remove a tag on an experiment."""
    _validate_tag(tag_name)
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    resolved_id = _resolve_exp_id(exman, exp_id)
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
    if sys.stdout.isatty():
        console = _get_console(ctx)
        console.print(f"[bold green]Tag '{tag_name}' {action} {short_id}.[/bold green]")
    else:
        click.echo(f"Tag '{tag_name}' {action} {short_id}.")


@cli.command()
@click.option("--group", help="Filter tags to a specific group")
@click.pass_context
def tags(ctx: click.Context, group: str | None) -> None:
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

    if sys.stdout.isatty():
        console = _get_console(ctx)
        table = Table(show_header=True, header_style="bold")
        table.add_column("Tag", style="magenta")
        table.add_column("Count", style="blue", justify="right")
        if group is None:
            table.add_column("Groups")

        for tag in sorted(tag_counts.keys()):
            count = tag_counts[tag]
            if group is None:
                group_parts = [
                    f"{g}({c})" for g, c in sorted(tag_groups[tag].items())
                ]
                table.add_row(tag, str(count), ", ".join(group_parts))
            else:
                table.add_row(tag, str(count))

        console.print(table)
    else:
        for tag in sorted(tag_counts.keys()):
            count = tag_counts[tag]
            if group is None:
                group_parts = [
                    f"{g}:{c}" for g, c in sorted(tag_groups[tag].items())
                ]
                click.echo(f"{tag:<20} {count:>3}  {', '.join(group_parts)}")
            else:
                click.echo(f"{tag:<20} {count:>3}")


@cli.command()
@click.argument("exp_id")
@click.option("--group", "-g", required=True, help="Target group name")
@click.pass_context
def move(ctx: click.Context, exp_id: str, group: str) -> None:
    """Move an experiment to a different group."""
    _validate_group(group)
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    resolved_id = _resolve_exp_id(exman, exp_id)

    try:
        exp = exman.move(resolved_id, group)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = exp.metadata.exp_id[:short_len]
    if sys.stdout.isatty():
        console = _get_console(ctx)
        console.print(
            f"[bold green]Experiment {short_id} moved to group "
            f"'{exp.metadata.group}'.[/bold green]"
        )
    else:
        click.echo(f"Experiment {short_id} moved to group '{exp.metadata.group}'.")


@cli.command()
@click.option(
    "--threshold",
    type=float,
    help="Jaccard similarity threshold (default: from config)",
)
@click.option("--apply", is_flag=True, help="Apply suggested group moves")
@click.pass_context
def suggest_groups(
    ctx: click.Context,
    threshold: float | None,
    apply: bool,
) -> None:
    """Suggest group assignments based on config key similarity.

    Computes Jaccard similarity between experiment config keys and
    suggests the most similar group's assignment for each experiment.
    """
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)

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

    if sys.stdout.isatty():
        console = _get_console(ctx)
        table = Table(show_header=True, header_style="bold")
        table.add_column("Experiment")
        table.add_column("Current Group")
        table.add_column("Suggested Group")
        table.add_column("Similarity")

        for exp, suggested_group, score in suggestions:
            short_len = cfg_mgr.get("short_id_length", 8)
            short_id = exp.metadata.exp_id[:short_len]
            table.add_row(
                short_id,
                exp.metadata.group,
                suggested_group,
                f"{score:.2f}",
            )
        console.print(table)
    else:
        short_len = cfg_mgr.get("short_id_length", 8)
        for exp, suggested_group, score in suggestions:
            short_id = exp.metadata.exp_id[:short_len]
            click.echo(
                f"{short_id}  {exp.metadata.group} -> {suggested_group}  "
                f"({score:.2f})"
            )

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
@click.pass_context
def rm(
    ctx: click.Context,
    exp_id: str | None,
    yes: bool,
    dry_run: bool,
    clear_trash: bool,
) -> None:
    """Remove an experiment to trash, or empty the trash.

    Experiments are moved to ``.trash/`` rather than deleted permanently.
    Auto-purges the oldest trashed items if capacity limits are exceeded.
    """
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)

    if clear_trash:
        items = exman.clear_trash(dry_run=dry_run)
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

        # Re-run without dry_run after confirmation
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

    if not dry_run and not yes:
        if sys.stdout.isatty():
            short_id = resolved_id[: cfg_mgr.get("short_id_length", 8)]
            click.echo(
                f"This will move experiment '{short_id}' to trash."
            )
            if not click.confirm("Proceed?"):
                click.echo("Aborted.")
                return
        else:
            raise click.ClickException(
                "Non-TTY operation requires --yes to remove. "
                "Use --dry-run to preview."
            )

    removed_exp, purged = exman.remove(resolved_id, dry_run=dry_run)

    for path in purged:
        action = "would purge" if dry_run else "purged"
        click.echo(f"{action}: {path.name}")

    if removed_exp is not None:
        short_len = cfg_mgr.get("short_id_length", 8)
        short_id = removed_exp.metadata.exp_id[:short_len]
        action = "would move" if dry_run else "moved"
        click.echo(f"{action} experiment {short_id} to trash.")


def main() -> None:
    """CLI entry point."""
    cli()
