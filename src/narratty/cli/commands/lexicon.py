"""``narratty lexicon``: inspect the pronunciation lexicon of a spec."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.cli.arguments import SpecArgument

lexicon_app = typer.Typer(help="Show or check how technical terms are pronounced.", no_args_is_help=True)


@lexicon_app.command("show")
def show_command(spec: Path = SpecArgument) -> None:
    """List the merged lexicon entries for a spec, with the level each comes from."""
    from rich.table import Table

    from narratty.spec import load_spec
    from narratty.tts.lexicon import load_lexicon
    from narratty.ui.console import out

    lexicon = load_lexicon(spec, load_spec(spec).tts)
    table = Table(show_header=True, header_style="bold")
    for column in ("term", "say", "source"):
        table.add_column(column, overflow="fold")
    for entry in sorted(lexicon.entries, key=lambda e: e.term.lower()):
        table.add_row(entry.term, entry.say, entry.source)
    out.print(table)


@lexicon_app.command("check")
def check_command(spec: Path = SpecArgument) -> None:
    """List narration words that look hard to pronounce and no lexicon entry covers."""
    from narratty.spec import load_spec
    from narratty.tts.lexicon import load_lexicon
    from narratty.ui.console import err, out

    loaded = load_spec(spec)
    lexicon = load_lexicon(spec, loaded.tts)
    found = 0
    for scene in loaded.narrated_scenes:
        for word in lexicon.unknown_words(scene.narration or ""):
            out.print(f"{scene.id}: {word}", highlight=False, markup=False)
            found += 1
    if found:
        err.print(
            f"{found} word{'s' if found != 1 else ''} without a lexicon entry; "
            "add the ones that sound wrong to tts.lexicon or narratty.lexicon.toml",
            highlight=False,
        )
    else:
        err.print("every unusual word has a lexicon entry", highlight=False)
