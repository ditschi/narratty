"""``narratty voices``: list curated and installed voices, and download them."""

from __future__ import annotations

import typer

from narratty.cli.completion import complete_provider, complete_voice

voices_app = typer.Typer(
    help="List voices, or download one with `voices pull`.",
    invoke_without_command=True,
    no_args_is_help=False,
)

ProviderOption = typer.Option(
    None,
    "--provider",
    "-p",
    help="Only this TTS provider (piper or kokoro).",
    autocompletion=complete_provider,
)


@voices_app.callback()
def voices_command(
    ctx: typer.Context,
    provider: str | None = ProviderOption,
    installed: bool = typer.Option(False, "--installed", help="Only voices that are downloaded."),
) -> None:
    """List curated voices and those installed locally."""
    if ctx.invoked_subcommand is not None:
        return
    from rich.table import Table

    from narratty.paths import data_dir
    from narratty.tts.catalog import PROVIDERS
    from narratty.tts.registry import get_provider
    from narratty.ui.console import out

    table = Table(show_header=True, header_style="bold")
    for column in ("provider", "voice", "language", "installed", "description"):
        table.add_column(column)
    for name in PROVIDERS if provider is None else (provider,):
        for voice in get_provider(name, data_dir()).voices():
            if installed and not voice.installed:
                continue
            mark = "[green]yes[/]" if voice.installed else "no"
            table.add_row(voice.provider, voice.id, voice.language, mark, voice.description)
    out.print(table)


@voices_app.command("pull")
def pull_command(
    voice: str = typer.Argument(
        ..., help="Voice id, e.g. en_US-lessac-medium.", autocompletion=complete_voice
    ),
    provider: str | None = ProviderOption,
) -> None:
    """Download a voice (and its model) into the data directory."""
    from narratty.paths import data_dir
    from narratty.tts.catalog import voice_ids
    from narratty.tts.registry import get_provider
    from narratty.ui.console import err

    if provider is None:
        provider = "kokoro" if voice in voice_ids("kokoro") else "piper"
    engine = get_provider(provider, data_dir())
    if engine.is_installed(voice):
        err.print(f"{provider} voice {voice} is already installed", highlight=False)
        return
    engine.install(voice)
    err.print(f"[green]installed[/] {provider} voice {voice}", highlight=False)
