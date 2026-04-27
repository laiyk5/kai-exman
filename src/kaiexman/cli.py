"""Kai-Exman CLI entry point.

Provides a Click-based command-line interface for experiment management
with git-log-style output, smart TTY detection, and Rich terminal rendering.
"""

from __future__ import annotations

import getpass
import os
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
from kaiexman.experiment import Experiment, validate_tag
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
@click.pass_context
def init(ctx: click.Context, description: str, tags: str, config: str | None) -> None:
    """Initialize a new experiment.

    Creates a directory structure, captures Git state, and optionally
    loads a YAML configuration file.
    """
    cfg = None
    if config and Path(config).exists():
        with open(config, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    cfg_mgr: ConfigManager = ctx.obj["config"]
    exman = ExMan(root=ctx.obj["path"], config=cfg_mgr)
    exp = exman.init(description=description, tags=tag_list, config=cfg)

    short_len = cfg_mgr.get("short_id_length", 8)
    short_id = exp.metadata.exp_id[:short_len]

    if sys.stdout.isatty():
        console = _get_console(ctx)
        table = Table(show_header=False, box=None)
        table.add_row("[bold]Experiment ID:[/bold]", short_id)
        table.add_row("[bold]Path:[/bold]", str(exp.root))
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
        click.echo(f"Git Hash: {exp.metadata.git_hash or 'N/A'}")
        click.echo(f"Status: {exp.metadata.status}")
        if exp.metadata.git_dirty:
            click.echo("Warning: Working tree has uncommitted changes")


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
    full_id: bool,
) -> None:
    """List experiments, optionally sorted by a metric.

    Displays experiments in a git-log-style format. In a TTY, uses
    Rich for colors and a pager; otherwise outputs plain text.
    """
    exman = ExMan(root=ctx.obj["path"])
    experiments = exman.list()

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
    if _use_pager(ctx):
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

            disp_id = _display_id(exp.metadata.exp_id, full_id, short_length)
            id_width = 16 if full_id else short_length
            line = (
                f"[yellow]{disp_id:{id_width}}[/yellow]  "
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
            disp_id = _display_id(exp.metadata.exp_id, full_id, short_length)
            console.print(
                f"[yellow]experiment {disp_id}[/yellow]"
                f"{tag_part}"
                f" [[{status_color}]{exp.metadata.status}[/{status_color}]]"
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

            disp_id = _display_id(exp.metadata.exp_id, full_id, short_length)
            id_width = 16 if full_id else short_length
            line = (
                f"{disp_id:{id_width}}  {date_str:16}  {status_label:10}  "
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
            disp_id = _display_id(exp.metadata.exp_id, full_id, short_length)
            click.echo(f"experiment {disp_id}{tag_part} [{exp.metadata.status}]")
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
        meta_table.add_row("[bold]Status[/bold]", exp.metadata.status)
        meta_table.add_row("[bold]Description[/bold]", exp.metadata.description or "-")
        meta_table.add_row(
            "[bold]Data Version[/bold]", exp.metadata.data_version or "-"
        )
        meta_table.add_row("[bold]Git Hash[/bold]", exp.metadata.git_hash or "N/A")
        meta_table.add_row("[bold]Git Dirty[/bold]", str(exp.metadata.git_dirty))
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

        console.print(meta_panel)
        console.print(cfg_panel)
        console.print(metrics_panel)
    else:
        click.echo(f"ID: {disp_id}")
        click.echo(f"Status: {exp.metadata.status}")
        click.echo(f"Description: {exp.metadata.description or '-'}")
        click.echo(f"Data Version: {exp.metadata.data_version or '-'}")
        click.echo(f"Git Hash: {exp.metadata.git_hash or 'N/A'}")
        click.echo(f"Git Dirty: {exp.metadata.git_dirty}")
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
