"""The CLI's start: the first-time administrator setup on an empty installation, then sign-in. Only administrators may use it."""

from pydantic import SecretStr, TypeAdapter, ValidationError

from a_domain.model.system.user import User
from a_domain.types.enums import Permission
from a_domain.types.errors import AlreadySetUpError, SignInRefused, SignInThrottled, UserExistsError
from a_domain.types.values import NewPassword
from b_application.pipeline import Pipeline
from d_presentation.cli import terminal

CLI_CLIENT = "cli"
"""The client address the attempt limits count the CLI's sign-ins under: it runs on the machine itself."""

KEY_BACKUP = (
    "Back up secrets/accounts.key with the database now if you have not: it is the only way to read the saved usernames "
    "and emails, and without the same key no one can sign in again. ACCOUNTS_KEY replaces it when you set one."
)


async def sign_in(pipeline: Pipeline) -> User | None:
    """
    The signed-in administrator, or None to exit. On an installation with no user yet it sets up the first
    administrator, who is then signed in. A user who may not use the CLI is told to use the web app.
    """
    options = await pipeline.load_sign_in_options()
    user = await set_up_first_administrator(pipeline) if options.needs_first_administrator else await ask_credentials(pipeline)

    if user is None:
        return None

    if Permission.USE_CLI not in user.permissions:
        terminal.console.print(
            "[red]Only an administrator can use the CLI: it reaches manual BUY and the real broker. Use the web app.[/red]"
        )
        return None

    terminal.console.print(f"[green]Signed in: {user.username} ({user.role.value}).[/green]")
    return user


async def ask_credentials(pipeline: Pipeline) -> User | None:
    """Asks a username or email and a password until they match, the attempt limits refuse, or the user leaves."""
    while (identifier := terminal.ask_user("Username or email")) is not None:
        if (password := terminal.ask_secret("Password")) is None:
            return None

        try:
            return await pipeline.sign_in(identifier, password, CLI_CLIENT)
        except SignInRefused as refused:
            terminal.console.print(f"[yellow]{refused}[/yellow]")
        except SignInThrottled as throttled:
            terminal.console.print(f"[red]{throttled}[/red]")
            return None

    return None


async def set_up_first_administrator(pipeline: Pipeline) -> User | None:
    """No user exists yet: asks the administrator's username, email and password (twice), and saves them."""
    terminal.console.print("No administrator yet. Set one up: the data of the single-owner version becomes theirs.")

    while (username := terminal.ask_user("Username (3 to 32 letters, digits, '.', '_' or '-')")) is not None:
        email = terminal.ask_user("Email")
        password = ask_new_password()

        if email is None or password is None:
            return None

        try:
            user = await pipeline.set_up_first_administrator(username, email, password)
        except (ValidationError, UserExistsError, AlreadySetUpError) as refused:
            terminal.console.print(f"[yellow]Not saved: {refused}[/yellow]")
            continue

        terminal.console.print(f"[green]Administrator {user.username} set up.[/green] {KEY_BACKUP}")
        return user

    return None


def ask_new_password() -> SecretStr | None:
    """A password of 12 to 256 characters, typed twice. None when the user leaves."""
    while (password := terminal.ask_secret("Password (12 to 256 characters)")) is not None:
        if (again := terminal.ask_secret("Password again")) is None:
            return None

        if password.get_secret_value() != again.get_secret_value():
            terminal.console.print("[yellow]The passwords differ. Try again.[/yellow]")
            continue

        try:
            return TypeAdapter(NewPassword).validate_python(password)
        except ValidationError:
            terminal.console.print("[yellow]A password needs 12 to 256 characters.[/yellow]")

    return None
