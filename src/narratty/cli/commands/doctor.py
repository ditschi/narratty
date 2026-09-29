"""``narratty doctor``: preflight checks for the selected runtime."""

from __future__ import annotations

from narratty.cli.options import RuntimeOption
from narratty.runtime import Runtime


def doctor_command(runtime: Runtime = RuntimeOption) -> None:
    """Check that the tools the selected runtime needs are installed."""
    # Imported lazily so ``--help`` and shell completion stay fast.
    from rich.table import Table

    from narratty.doctor import run_checks
    from narratty.errors import MissingDependencyError
    from narratty.runtime import resolve_runtime
    from narratty.ui.console import out

    resolved = resolve_runtime(runtime)
    out.print(f"runtime: [bold]{resolved.runtime.value}[/] ({resolved.reason})", highlight=False)

    results = run_checks(resolved)
    table = Table(show_header=True, header_style="bold")
    table.add_column("tool")
    table.add_column("status")
    table.add_column("used for")
    table.add_column("path / how to install", overflow="fold")
    for result in results:
        status = "[green]ok[/]" if result.ok else "[red]missing[/]"
        detail = result.path if result.path is not None else result.tool.install_hint
        table.add_row(result.tool.name, status, result.tool.purpose, detail)
    out.print(table)

    missing = [result.tool.name for result in results if not result.ok]
    if missing:
        raise MissingDependencyError(
            f"missing: {', '.join(missing)}",
            hint="Install the tools listed above, or use --runtime docker to render in a container.",
        )
