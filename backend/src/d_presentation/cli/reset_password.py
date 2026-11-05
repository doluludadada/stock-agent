"""
`just reset-password <username or email>`: a new password for a user, set on the machine with the database and the
accounts key it already has. For an administrator locked out of every account; every session of the user ends.
"""

import asyncio
import os
import sys

from b_application.config.settings_loader import get_project_root, startup_settings
from d_presentation.cli import terminal, user_views
from d_presentation.dependencies import STARTUP_REFUSALS, create_process_state, open_runtime


async def reset_password(identifier: str) -> int:
    config = startup_settings(get_project_root())

    async with open_runtime(config, create_process_state(config)) as runtime:
        password = user_views.ask_new_password()

        if password is None:
            terminal.console.print("[yellow]Cancelled. Nothing changed.[/yellow]")
            return 1

        user = await runtime.signed_out.reset_password(identifier, password)

    if user is None:
        terminal.console.print(f"[red]No user is named {identifier}. Nothing changed.[/red]")
        return 1

    terminal.console.print(f"[green]New password set for {user.username}. Their sessions ended; they sign in again.[/green]")
    return 0


if __name__ == "__main__":
    exit_code = 1

    try:
        exit_code = asyncio.run(reset_password(sys.argv[1])) if len(sys.argv) == 2 else 2
    except STARTUP_REFUSALS as error:
        terminal.console.print(str(error), style="red", markup=False, highlight=False)
    finally:
        os._exit(exit_code)
