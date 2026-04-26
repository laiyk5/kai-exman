import getpass
import os
import sys
from datetime import datetime
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from kaiexman.manager import ExMan


class AliasedGroup(click.Group):
    _aliases = {"log": "list"}

    def get_command(self, ctx, cmd_name):
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        alias = self._aliases.get(cmd_name)
        if alias:
            return super().get_command(ctx, alias)
        return None


def _use_color(ctx: click.Context) -> bool:
    if ctx.obj.get("no_color"):
        return False
    return sys.stdout.isatty()


def _use_pager(ctx: click.Context) -> bool:
    if ctx.obj.get("no_pager"):
        return False
    return sys.stdout.isatty()


def _get_console(ctx: click.Context) -> Console:
    return Console(
        force_terminal=_use_color(ctx),
        color_system="truecolor" if _use_color(ctx) else None,
    )


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
@click.pass_context
def cli(
    ctx: click.Context,
    path: str,
    no_pager: bool,
    no_color: bool,
) -> None:
    """Kai-Exman: Rigorous Experiment Management"""
    ctx.ensure_object(dict)
    ctx.obj["path"] = path
    ctx.obj["no_pager"] = no_pager
    ctx.obj["no_color"] = no_color


@cli.command()
@click.option("--description", "-d", default="", help="Experiment description")
@click.option("--tags", "-t", default="", help="Comma-separated tags")
@click.option("--config", "-c", help="Path to config YAML file")
@click.pass_context
def init(ctx: click.Context, description: str, tags: str, config: str | None) -> None:
    """Initialize a new experiment"""
    cfg = None
    if config and Path(config).exists():
        with open(config, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    exman = ExMan(root=ctx.obj["path"])
    exp = exman.init(description=description, tags=tag_list, config=cfg)

    console = _get_console(ctx)
    table = Table(show_header=False, box=None)
    table.add_row("[bold]Experiment ID:[/bold]", exp.metadata.exp_id)
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
@click.pass_context
def list_cmd(
    ctx: click.Context,
    sort_by: str | None,
    order: str,
    top: int | None,
    oneline: bool,
) -> None:
    """List experiments, optionally sorted by a metric"""
    exman = ExMan(root=ctx.obj["path"])
    experiments = exman.list()

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

    if _use_pager(ctx):
        _list_rich(ctx, scored, sort_by, order, oneline)
    else:
        _list_plain(scored, sort_by, order, oneline)


_STATUS_COLORS = {
    "success": "green",
    "running": "blue",
    "failed": "red",
}


def _format_dt(iso: str) -> str:
    """Convert ISO timestamp to human-readable date + time."""
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return iso[:19] if len(iso) >= 19 else iso


def _params_line(config: dict) -> str:
    """Return up to 3 key=value snippets from config."""
    if not config:
        return ""
    items = list(config.items())[:3]
    return " ".join(f"{k}={v}" for k, v in items)


def _list_rich(
    ctx: click.Context,
    scored: list,
    sort_by: str | None,
    order: str,
    oneline: bool,
) -> None:
    console = Console(force_terminal=True, record=True)

    if oneline:
        for exp, _best, score in scored:
            date_str = exp.metadata.timestamp[:10]
            status_color = _STATUS_COLORS.get(exp.metadata.status, "white")
            desc = exp.metadata.description or "-"
            tags_str = " ".join(exp.metadata.tags) if exp.metadata.tags else ""

            line = (
                f"[yellow]{exp.metadata.exp_id:8}[/yellow] "
                f"[cyan]{date_str:10}[/cyan] "
                f"([{status_color}]{exp.metadata.status:10}[/{status_color}]) "
                f"{desc}"
            )
            if tags_str:
                line += f" -- [magenta]{tags_str}[/magenta]"
            if sort_by:
                score_str = f"{score:.4f}" if score is not None else "-"
                line += f"  [{sort_by}={score_str}]"
            console.print(line)
    else:
        for exp, _best, score in scored:
            status_color = _STATUS_COLORS.get(exp.metadata.status, "white")
            dt = _format_dt(exp.metadata.timestamp)
            desc = exp.metadata.description or "-"
            tags_str = " ".join(exp.metadata.tags) if exp.metadata.tags else ""
            params = _params_line(exp.config)

            # Header: ID + Status
            console.print(
                f"[yellow]{exp.metadata.exp_id:8}[/yellow] "
                f"([{status_color}]{exp.metadata.status}[/{status_color}])"
            )

            # Author + Date
            author = getpass.getuser()
            console.print(f"Author: {author} | Date: {dt}")

            # Indented description
            if desc:
                console.print(f"\n    {desc}")

            # Footer: Tags + Params + optional sort score
            footer_parts = []
            if tags_str:
                footer_parts.append(f"Tags: [magenta]{tags_str}[/magenta]")
            if params:
                footer_parts.append(f"Params: [blue]{params}[/blue]")
            if sort_by:
                score_str = f"{score:.4f}" if score is not None else "-"
                footer_parts.append(f"[yellow]{sort_by}={score_str}[/yellow]")
            if footer_parts:
                console.print(f"\n    {' | '.join(footer_parts)}")

            # Blank line separator
            console.print("")

    text = console.export_text(styles=True)
    os.environ.setdefault("LESS", "-R")
    click.echo_via_pager(text)


def _list_plain(
    scored: list,
    sort_by: str | None,
    order: str,
    oneline: bool,
) -> None:
    if oneline:
        for exp, _best, score in scored:
            date_str = exp.metadata.timestamp[:10]
            desc = exp.metadata.description or "-"
            tags_str = " ".join(exp.metadata.tags) if exp.metadata.tags else ""

            line = (
                f"{exp.metadata.exp_id:8} "
                f"{date_str:10} "
                f"({exp.metadata.status:10}) "
                f"{desc}"
            )
            if tags_str:
                line += f" -- {tags_str}"
            if sort_by:
                score_str = f"{score:.4f}" if score is not None else "-"
                line += f"  [{sort_by}={score_str}]"
            click.echo(line)
    else:
        for exp, _best, score in scored:
            dt = _format_dt(exp.metadata.timestamp)
            desc = exp.metadata.description or "-"
            tags_str = " ".join(exp.metadata.tags) if exp.metadata.tags else ""
            params = _params_line(exp.config)

            click.echo(f"{exp.metadata.exp_id:8} ({exp.metadata.status})")
            click.echo(f"Author: {getpass.getuser()} | Date: {dt}")
            if desc:
                click.echo(f"\n    {desc}")

            footer_parts = []
            if tags_str:
                footer_parts.append(f"Tags: {tags_str}")
            if params:
                footer_parts.append(f"Params: {params}")
            if sort_by:
                score_str = f"{score:.4f}" if score is not None else "-"
                footer_parts.append(f"{sort_by}={score_str}")
            if footer_parts:
                click.echo(f"\n    {' | '.join(footer_parts)}")

            click.echo("")


@cli.command()
@click.argument("exp_id")
@click.option("--status", "-s", default="finished", help="Final status")
@click.option("--notes", "-n", default="", help="Post-mortem notes")
@click.pass_context
def finish(ctx: click.Context, exp_id: str, status: str, notes: str) -> None:
    """Close an experiment and generate summary.md"""
    exman = ExMan(root=ctx.obj["path"])
    exp = exman.finish(exp_id=exp_id, status=status, notes=notes)

    if exp is None:
        click.echo(f"Experiment '{exp_id}' not found.", err=True)
        raise click.Exit(1)

    console = _get_console(ctx)
    console.print(
        Panel(
            f"[bold green]Experiment {exp_id} finished.[/bold green]\n"
            f"Status: {status}\n"
            f"Summary written to: {exp.root / 'summary.md'}",
            title="Finish",
            border_style="green",
        )
    )


@cli.command()
@click.argument("exp_id")
@click.pass_context
def show(ctx: click.Context, exp_id: str) -> None:
    """Display a detailed summary of a specific experiment"""
    exman = ExMan(root=ctx.obj["path"])
    exp = exman.get(exp_id)

    if exp is None:
        click.echo(f"Experiment '{exp_id}' not found.", err=True)
        raise click.Exit(1)

    best_metrics = exp.compute_best_metrics()
    console = _get_console(ctx)

    meta_table = Table(show_header=False, box=None)
    meta_table.add_row("[bold]ID[/bold]", exp.metadata.exp_id)
    meta_table.add_row("[bold]Status[/bold]", exp.metadata.status)
    meta_table.add_row("[bold]Description[/bold]", exp.metadata.description or "-")
    meta_table.add_row("[bold]Data Version[/bold]", exp.metadata.data_version or "-")
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


def main() -> None:
    cli()
