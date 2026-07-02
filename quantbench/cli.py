from __future__ import annotations

import json

import click

from quantbench.agent.coordinator import Coordinator
from quantbench.library.compare import compare_runs
from quantbench.library.index import ExperimentIndex, parse_csv_set


@click.command(context_settings={"help_option_names": ["-h", "--help"], "ignore_unknown_options": True})
@click.argument("args", nargs=-1, required=True, type=click.UNPROCESSED)
def main(args: tuple[str, ...]) -> None:
    if args[:2] == ("library", "list"):
        _library_list(args[2:])
        return
    if args[0] == "compare":
        _compare(args[1:])
        return
    _run_request(" ".join(args))


def _library_list(args: tuple[str, ...]) -> None:
    verdict = _option_value(args, "--verdict")
    asset_class = _option_value(args, "--asset")
    factor_family = _option_value(args, "--factor-family")
    sort_field = _option_value(args, "--sort") or "created_at"
    min_sharpe_value = _option_value(args, "--min-sharpe")
    min_sharpe = float(min_sharpe_value) if min_sharpe_value is not None else None
    json_output = "--json-output" in args

    index = (
        ExperimentIndex.build()
        .filter(
            verdicts=parse_csv_set(verdict),
            asset_class=asset_class,
            factor_family=factor_family,
            min_sharpe=min_sharpe,
        )
        .sort(sort_field)
    )
    rows = index.to_dicts()
    if json_output:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    _echo_library_table(rows)


def _compare(args: tuple[str, ...]) -> None:
    json_output = "--json-output" in args
    run_ids = [arg for arg in args if not arg.startswith("--")]
    if not run_ids:
        raise click.UsageError("compare requires at least one run_id")
    table = compare_runs(run_ids)
    if json_output:
        click.echo(json.dumps(table, ensure_ascii=False, indent=2))
        return
    _echo_compare_table(table)


def _run_request(user_request: str) -> None:
    result = Coordinator().run(user_request)
    click.echo(f"Run ID: {result.run_id}")
    click.echo("Metrics:")
    for key, value in result.metrics.items():
        click.echo(f"  {key}: {value}")
    click.echo(f"Artifact directory: {result.run_dir}")
    if result.warnings:
        click.secho("\nWARNINGS - review before trusting this result:", fg="yellow", bold=True)
        for warning in result.warnings:
            click.secho(f"  - {warning}", fg="yellow")


def _option_value(args: tuple[str, ...], name: str) -> str | None:
    prefix = f"{name}="
    for arg in args:
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    if name not in args:
        return None
    index = args.index(name)
    if index + 1 >= len(args):
        raise click.UsageError(f"{name} requires a value")
    return args[index + 1]


def _echo_library_table(rows: list[dict]) -> None:
    headers = ["run_id", "hypothesis", "asset", "family", "verdict", "sharpe", "oos_sharpe", "warnings", "created_at"]
    click.echo(" | ".join(headers))
    click.echo(" | ".join("---" for _ in headers))
    for row in rows:
        click.echo(
            " | ".join(
                [
                    str(row["run_id"]),
                    _clip(str(row["hypothesis"]), 36),
                    str(row["asset_class"]),
                    str(row["factor_family"]),
                    str(row["verdict"] or ""),
                    _fmt(row["sharpe"]),
                    _fmt(row["oos_sharpe"]),
                    str(row["warning_count"]),
                    str(row["created_at"]),
                ]
            )
        )


def _echo_compare_table(table: dict) -> None:
    run_ids = table["run_ids"]
    click.echo("metric | " + " | ".join(run_ids))
    click.echo(" | ".join(["---"] * (len(run_ids) + 1)))
    click.echo("verdict | " + " | ".join(str(table["verdicts"].get(run_id) or "") for run_id in run_ids))
    for metric, values in table["metrics"].items():
        click.echo(f"{metric} | " + " | ".join(_fmt(values.get(run_id)) for run_id in run_ids))
    click.echo("")
    click.echo("critical/warning findings")
    for run_id in run_ids:
        findings = table["findings"].get(run_id) or []
        summary = "; ".join(f"{item.get('severity')}:{item.get('check')}" for item in findings) or "-"
        click.echo(f"{run_id}: {summary}")


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "..."
