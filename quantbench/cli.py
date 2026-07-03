from __future__ import annotations

import json

import click

from quantbench.agent.coordinator import Coordinator
from quantbench.api import run_reader
from quantbench.config import FACTORS_DIR as DEFAULT_FACTORS_DIR
from quantbench.data.cache import file_sha256
from quantbench.config import SKILL_DOCS_DIR as DEFAULT_SKILL_DOCS_DIR
from quantbench.factors.entry import RejectedFactorError, build_entry_from_run
from quantbench.factors.parametrize import parse_param_overrides
from quantbench.factors.store import FactorStore
from quantbench.library.compare import compare_runs
from quantbench.library.index import ExperimentIndex, parse_csv_set
from quantbench.skilldocs.registry import SkillRegistryDocs


@click.command(context_settings={"help_option_names": ["-h", "--help"], "ignore_unknown_options": True})
@click.argument("args", nargs=-1, required=True, type=click.UNPROCESSED)
def main(args: tuple[str, ...]) -> None:
    forced_skills, args = _consume_repeated_option(args, "--skill")
    if args[:2] == ("library", "list"):
        _library_list(args[2:])
        return
    if args[0] == "factor":
        _factor(args[1:], forced_skills)
        return
    if args[0] == "skill":
        _skill(args[1:])
        return
    if args[0] == "compare":
        _compare(args[1:])
        return
    if args[0] == "rerun":
        _rerun(args[1:])
        return
    if args[0] == "portfolio":
        _portfolio(args[1:])
        return
    if args[0] == "monitor":
        _monitor(args[1:])
        return
    _run_request(" ".join(args), forced_skills)


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


def _rerun(args: tuple[str, ...]) -> None:
    if not args:
        raise click.UsageError("rerun requires run_id")
    run_id = args[0]
    manifest = run_reader.read_manifest(run_id)
    if manifest is None:
        raise click.ClickException(f"run not found: {run_id}")
    slices = manifest.get("data_slices") or []
    if not slices:
        raise click.ClickException(f"run {run_id} has no data_slices; cannot verify reproducible rerun data")
    drifted = []
    missing = []
    for item in slices:
        path = item.get("path")
        expected = item.get("content_hash")
        if not path or not expected:
            drifted.append(f"{item.get('symbol', 'unknown')}: missing path/hash metadata")
            continue
        from pathlib import Path

        file_path = Path(path)
        if not file_path.exists():
            missing.append(str(file_path))
            continue
        actual = file_sha256(file_path)
        if actual != expected:
            drifted.append(f"{item.get('symbol', file_path.name)}: expected {expected}, got {actual}")
    if missing or drifted:
        details = []
        if missing:
            details.append("missing slices: " + ", ".join(missing[:5]))
        if drifted:
            details.append("drifted slices: " + "; ".join(drifted[:5]))
        raise click.ClickException("Data drift detected; result is not directly comparable. " + " | ".join(details))
    click.echo(f"Data slices verified for {run_id}; cached inputs match manifest hashes.")


_PORTFOLIO_VALUE_OPTIONS = ("--method", "--cost-bps", "--split", "--max-weight")


def _portfolio(args: tuple[str, ...]) -> None:
    if not args:
        raise click.UsageError("portfolio requires a subcommand: optimize")
    command = args[0]
    if command != "optimize":
        raise click.UsageError(f"unknown portfolio subcommand: {command}")
    rest = args[1:]
    # Unlike _compare's only flag (--json-output, no value), portfolio optimize
    # has several space-separated value options (--method min_variance, etc.) -
    # a plain "not startswith('--')" filter would swallow the option's value as
    # a spurious extra run_id, so option names and the token right after them
    # both have to be excluded from the run_id list.
    run_ids = []
    skip_next = False
    for arg in rest:
        if skip_next:
            skip_next = False
            continue
        if arg.startswith("--"):
            if "=" not in arg and arg in _PORTFOLIO_VALUE_OPTIONS:
                skip_next = True
            continue
        run_ids.append(arg)
    if not run_ids:
        raise click.UsageError("portfolio optimize requires at least two run_ids")
    method = _option_value(rest, "--method")
    cost_bps_value = _option_value(rest, "--cost-bps")
    split_value = _option_value(rest, "--split")
    max_weight_value = _option_value(rest, "--max-weight")
    result = Coordinator().optimize_portfolio(
        run_ids,
        method=method,
        cost_bps=float(cost_bps_value) if cost_bps_value is not None else None,
        split=float(split_value) if split_value is not None else None,
        max_weight=float(max_weight_value) if max_weight_value is not None else None,
    )
    _echo_run_result(result)


def _monitor(args: tuple[str, ...]) -> None:
    if not args:
        raise click.UsageError("monitor requires a subcommand: check/watch")
    command = args[0]
    rest = args[1:]
    if command == "check":
        _monitor_check(rest)
        return
    if command == "watch":
        _monitor_watch(rest)
        return
    raise click.UsageError(f"unknown monitor subcommand: {command}")


def _monitor_check(args: tuple[str, ...]) -> None:
    from quantbench.monitor.pipeline import check_run_decay, run_monitor_pass

    json_output = "--json-output" in args
    if "--all-alive" in args:
        results = run_monitor_pass()
    else:
        run_ids = [arg for arg in args if not arg.startswith("--")]
        if not run_ids:
            raise click.UsageError("monitor check requires at least one run_id, or --all-alive")
        results = [{"run_id": run_id, **check_run_decay(run_id)} for run_id in run_ids]

    if json_output:
        click.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return
    _echo_monitor_table(results)


def _monitor_watch(args: tuple[str, ...]) -> None:
    import time

    from quantbench.config import MONITOR_POLL_INTERVAL_SECONDS
    from quantbench.monitor.pipeline import run_monitor_pass

    interval_value = _option_value(args, "--interval")
    interval = float(interval_value) if interval_value is not None else MONITOR_POLL_INTERVAL_SECONDS
    click.echo(f"Watching for decay every {interval:.0f}s. Ctrl+C to stop.")
    try:
        while True:
            results = run_monitor_pass()
            _echo_monitor_table(results)
            click.echo(f"--- checked {len(results)} run(s), sleeping {interval:.0f}s ---")
            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("Stopped.")


def _echo_monitor_table(results: list[dict]) -> None:
    headers = ["run_id", "status", "verdict/error", "recent_sharpe", "decay_ratio", "detail"]
    click.echo(" | ".join(headers))
    click.echo(" | ".join("---" for _ in headers))
    for item in results:
        status = item.get("status") or ("skipped" if "skipped" in item else "error" if "error" in item else "")
        note = item.get("verdict") or item.get("error") or item.get("skipped") or ""
        click.echo(
            " | ".join(
                [
                    str(item.get("run_id", "")),
                    str(status),
                    _clip(str(note), 40),
                    _fmt(item.get("recent_sharpe")),
                    _fmt(item.get("sharpe_decay_ratio")),
                    _clip(str(item.get("detail", "")), 60),
                ]
            )
        )


def _factor(args: tuple[str, ...], forced_skills: list[str]) -> None:
    if not args:
        raise click.UsageError("factor requires a subcommand: save/list/show/use")
    command = args[0]
    store = FactorStore(DEFAULT_FACTORS_DIR)
    if command == "save":
        if len(args) < 2:
            raise click.UsageError("factor save requires run_id")
        run_id = args[1]
        name = _option_value(args[2:], "--name")
        if not name:
            raise click.UsageError("factor save requires --name")
        notes = _option_value(args[2:], "--notes") or ""
        try:
            entry = build_entry_from_run(run_id, name, force="--force" in args, notes=notes)
            store.save_factor(entry, overwrite="--overwrite" in args)
        except RejectedFactorError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"Saved factor {entry.name} from {entry.source_run_id}")
        return
    if command == "list":
        rows = store.list_factors(
            family=_option_value(args[1:], "--family"),
            asset_class=_option_value(args[1:], "--asset"),
            min_verdict=_option_value(args[1:], "--min-verdict"),
        )
        _echo_factor_table(rows)
        return
    if command == "show":
        if len(args) < 2:
            raise click.UsageError("factor show requires name")
        _echo_factor_detail(store.load_factor(args[1]))
        return
    if command == "use":
        if len(args) < 2:
            raise click.UsageError("factor use requires name")
        name = args[1]
        params = parse_param_overrides(_option_values(args[2:], "--param"))
        request = _option_value(args[2:], "--on") or " ".join(arg for arg in args[2:] if not arg.startswith("--"))
        if not request:
            raise click.UsageError("factor use requires --on REQUEST")
        result = Coordinator().run_from_factor(name, params, request, skill_names=forced_skills, factor_store=store)
        _echo_run_result(result)
        return
    raise click.UsageError(f"unknown factor subcommand: {command}")


def _skill(args: tuple[str, ...]) -> None:
    if not args:
        raise click.UsageError("skill requires a subcommand: list/show")
    registry = SkillRegistryDocs(DEFAULT_SKILL_DOCS_DIR)
    if args[0] == "list":
        headers = ["name", "description", "triggers"]
        click.echo(" | ".join(headers))
        click.echo(" | ".join("---" for _ in headers))
        for doc in registry.load_all():
            click.echo(f"{doc.name} | {doc.description} | {', '.join(doc.triggers)}")
        return
    if args[0] == "show":
        if len(args) < 2:
            raise click.UsageError("skill show requires name")
        doc = registry.get(args[1])
        click.echo(f"name: {doc.name}")
        click.echo(f"description: {doc.description}")
        click.echo(f"triggers: {', '.join(doc.triggers)}")
        click.echo("")
        click.echo(doc.body)
        return
    raise click.UsageError(f"unknown skill subcommand: {args[0]}")


def _run_request(user_request: str, forced_skills: list[str] | None = None) -> None:
    result = Coordinator().run(user_request, skill_names=forced_skills)
    _echo_run_result(result)


def _echo_run_result(result) -> None:
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


def _option_values(args: tuple[str, ...], name: str) -> list[str]:
    values: list[str] = []
    index = 0
    prefix = f"{name}="
    while index < len(args):
        arg = args[index]
        if arg.startswith(prefix):
            values.append(arg[len(prefix) :])
        elif arg == name:
            if index + 1 >= len(args):
                raise click.UsageError(f"{name} requires a value")
            values.append(args[index + 1])
            index += 1
        index += 1
    return values


def _consume_repeated_option(args: tuple[str, ...], name: str) -> tuple[list[str], tuple[str, ...]]:
    values: list[str] = []
    kept: list[str] = []
    index = 0
    prefix = f"{name}="
    while index < len(args):
        arg = args[index]
        if arg.startswith(prefix):
            values.append(arg[len(prefix) :])
        elif arg == name:
            if index + 1 >= len(args):
                raise click.UsageError(f"{name} requires a value")
            values.append(args[index + 1])
            index += 1
        else:
            kept.append(arg)
        index += 1
    return values, tuple(kept)


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


def _echo_factor_table(rows) -> None:
    headers = ["name", "family", "asset", "source_verdict", "source_sharpe", "param_summary", "saved_at"]
    click.echo(" | ".join(headers))
    click.echo(" | ".join("---" for _ in headers))
    for entry in rows:
        params = ", ".join(f"{param['name']}={param['value']:g}" for param in entry.parameters)
        click.echo(
            " | ".join(
                [
                    entry.name,
                    entry.family,
                    entry.asset_class,
                    str(entry.source_verdict or ""),
                    _fmt(entry.source_metrics.get("sharpe")),
                    params,
                    entry.saved_at,
                ]
            )
        )


def _echo_factor_detail(entry) -> None:
    click.echo(f"name: {entry.name}")
    click.echo(f"family: {entry.family}")
    click.echo(f"asset_class: {entry.asset_class}")
    click.echo(f"source_run_id: {entry.source_run_id}")
    click.echo(f"source_verdict: {entry.source_verdict}")
    click.echo(f"source_metrics: {json.dumps(entry.source_metrics, ensure_ascii=False, sort_keys=True)}")
    click.echo(f"parameters: {json.dumps(entry.parameters, ensure_ascii=False)}")
    click.echo(f"saved_from_rejected: {entry.saved_from_rejected}")
    if entry.notes:
        click.echo(f"notes: {entry.notes}")
    click.echo("")
    click.echo("known_limitations:")
    for finding in entry.source_findings:
        click.echo(f"- {finding.get('severity')} [{finding.get('check')}]: {finding.get('message')}")
    click.echo("")
    click.echo("code:")
    click.echo(entry.code.rstrip())


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "..."
