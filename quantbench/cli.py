import click

from quantbench.agent.coordinator import Coordinator


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("request", nargs=-1, required=True)
def main(request: tuple[str, ...]) -> None:
    user_request = " ".join(request)
    result = Coordinator().run(user_request)
    click.echo(f"Run ID: {result.run_id}")
    click.echo("Metrics:")
    for key, value in result.metrics.items():
        click.echo(f"  {key}: {value}")
    click.echo(f"Artifact directory: {result.run_dir}")
    if result.warnings:
        click.secho("\n⚠️  WARNINGS - review before trusting this result:", fg="yellow", bold=True)
        for warning in result.warnings:
            click.secho(f"  - {warning}", fg="yellow")
