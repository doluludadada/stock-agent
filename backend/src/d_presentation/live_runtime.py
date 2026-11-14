"""
Where the runtime a Web request, a background run or a CLI option uses comes from. The process keeps the runtimes it
opened, oldest first; the last is current. New work holds the current one until it ends; a reload opens a whole new
runtime first and only then makes it current, and a runtime no longer current closes once nothing holds it. The
settings a runtime was built from never change under the work that holds it.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable, Generator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pydantic import SecretStr

from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.settings_files import SettingChange, SettingsEdit, SettingsProblem
from a_domain.types.enums import ExecutionProvider, SettingsFile
from a_domain.types.errors import SettingsConflictError
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import (
    InvalidSettingsError,
    get_project_root,
    settings_notices,
    settings_revision,
    settings_texts,
    startup_settings,
)
from b_application.pipeline import Pipeline
from d_presentation.dependencies import STARTUP_REFUSALS, Runtime, create_process_state, open_runtime

type RuntimeOpener = Callable[[AppConfig], AbstractAsyncContextManager[Runtime]]


@dataclass(eq=False, slots=True)
class OpenedRuntime:
    """One runtime the switch opened, how many holders still use it, and whether a newer one replaced it."""

    runtime: Runtime
    exit_stack: AsyncExitStack
    holds: int = 0
    retired: bool = False
    closing: asyncio.Task[None] | None = None

    @contextmanager
    def hold(self) -> Generator[Self]:
        """
        Keeps this runtime open from the enter to the exit. The enter counts at once and never waits, so no reload can
        close the runtime between the moment work reads it and the moment it uses it.
        """
        self.holds += 1

        try:
            yield self
        finally:
            self.holds -= 1
            self.close_when_unused()

    def retire(self) -> None:
        self.retired = True
        self.close_when_unused()

    def close_when_unused(self) -> None:
        """
        Starts the close once, in the background, so the request that released the last hold does not wait for the
        database and the other adapters to close. The task is kept here, so it is not collected before it ends.
        """
        if self.retired and self.holds == 0 and self.closing is None:
            self.closing = asyncio.get_running_loop().create_task(self.exit_stack.aclose())


@dataclass(frozen=True, slots=True)
class SettingsReloaded:
    """Settings files the process runs on now: the revisions it read and those it replaced."""

    revisions: dict[SettingsFile, str]
    previous: dict[SettingsFile, str]


@dataclass(frozen=True, slots=True)
class ReloadRefused:
    """Settings files on disk the app would not start with: the revisions it read, and why."""

    revisions: dict[SettingsFile, str]
    problems: tuple[SettingsProblem, ...]


type SettingsReload = SettingsReloaded | ReloadRefused


def startup_problems(error: Exception, logger: ILoggingProvider) -> list[SettingsProblem]:
    """
    What a refused start says, the way startup says it: the settings' located problems, every other startup refusal in
    its own words. Any other error (a database that cannot be reached, a driver's own exception) is logged whole for the
    operator and named by its type only, because a driver's text can carry a connection string.
    """
    if isinstance(error, InvalidSettingsError):
        return error.problems

    if isinstance(error, STARTUP_REFUSALS):
        return [SettingsProblem(message=str(error))]

    logger.error(f"The app would not start with the new settings: {type(error).__name__}: {error}")
    return [SettingsProblem(message=f"The app would not start: {type(error).__name__}. The server log has the details.")]


class RuntimeSwitch:
    """
    The runtimes this process has open, oldest first; the last is current. New requests, runs and CLI options hold the
    current one. A reload opens a whole new runtime from the settings files first (the startup itself, the database and
    the broker login included), and only when it started appends it and retires the one before, which closes once
    nothing holds it. One lock serializes the reloads; taking a hold never waits for it.
    """

    def __init__(self, opener: RuntimeOpener, project_root: Path, logger: ILoggingProvider) -> None:
        self.logger = logger
        self.opener = opener
        self.project_root = project_root
        self.lock = asyncio.Lock()
        self.opened: list[OpenedRuntime] = []
        self.refused: ReloadRefused | None = None

    async def start(self, config: AppConfig) -> None:
        """Opens the first runtime, as startup always has: a refusal propagates as raised, and the process exits on it."""
        stack = AsyncExitStack()
        runtime = await stack.enter_async_context(self.opener(config))
        runtime.become_current()
        self.opened.append(OpenedRuntime(runtime, stack))

    @contextmanager
    def hold(self) -> Generator[OpenedRuntime]:
        """The runtime current at the enter, held until the exit. Never waits: a reload in progress is not current yet."""
        with self.opened[-1].hold() as opened:
            yield opened

    @property
    def running(self) -> dict[SettingsFile, str]:
        """The revision of each file the current runtime was built from: what new requests run on."""
        return dict(self.opened[-1].runtime.config.settings_revisions)

    async def reload(self) -> SettingsReload | None:
        """
        The watcher's reload rule: when the settings files on disk differ from both the revisions the current runtime
        runs on and the last refused ones, opens a runtime from the files as they are and makes it current. None when
        there is nothing new to load. A refusal leaves the current runtime serving and is kept, so the same files are
        not tried again until they change. Running it twice changes nothing the second time.
        """
        async with self.lock:
            revisions = {file: settings_revision(text) for file, text in settings_texts(self.project_root).items()}
            running = self.running

            if revisions == running:
                self.refused = None
                return None

            if self.refused is not None and self.refused.revisions == revisions:
                return None

            try:
                opened = await self.open_candidate({}, None)
            except InvalidSettingsError as error:
                self.refused = ReloadRefused(revisions, tuple(error.problems))
                self.logger.warning(f"The settings on disk were not loaded:\n{error}")
                return self.refused

            self.publish(opened)
            return SettingsReloaded(self.running, running)

    async def log_in_again(self) -> None:
        """
        The Web API timer's new Shioaji login: while the current runtime's login is down, because it failed when the
        runtime opened or Shioaji reported its session down since, a runtime opened from the settings files as a reload
        opens one, which logs in again on a new client, becomes current. A runtime that would not open leaves the current
        one serving, and the next interval tries again.
        """
        async with self.lock:
            if not self.opened[-1].runtime.login_down:
                return

            try:
                opened = await self.open_candidate({}, None)
            except InvalidSettingsError as error:
                self.logger.warning(f"The Shioaji login is down, and a runtime to log in again would not open:\n{error}")
                return

            self.publish(opened)

    async def save(
        self,
        opened: OpenedRuntime,
        administrator: User,
        changes: Sequence[SettingChange],
        *,
        password: SecretStr | None,
        google_confirmation: str | None = None,
        client: str,
        host: str,
    ) -> list[SettingsEdit]:
        """
        The settings form's save, running at once or refused with nothing written and the app as it was. The request's
        runtime must still be current: a page that read settings the server no longer runs is a conflict. The
        administrator's Pipeline reviews the changes and confirms the password, or for an administrator without one the
        fresh Google authentication `google_confirmation` names; changes that change no file end there.
        Work that started earlier finishes on the runtime it holds.
        """
        async with self.lock:
            if opened is not self.opened[-1]:
                raise SettingsConflictError("The server reloaded its settings after this page read them; read them again")

            pipeline = opened.runtime.pipeline_for(administrator, ExecutionProvider.MOCK)
            edits = await pipeline.review_settings_form(administrator, changes, host, password, google_confirmation, client)

            if not edits:
                return []

            return await self.write_and_publish(pipeline, edits, administrator.user_id)

    async def write_and_publish(self, pipeline: Pipeline, edits: Sequence[SettingsEdit], actor: UserId) -> list[SettingsEdit]:
        """
        Opens one runtime on every edited text, which `actor` can still sign in to, writes each file with its backup and
        audit entry, and makes the runtime current. A write that fails, another editor's save in between included,
        closes the new runtime and swaps nothing; a file written before it stays written, and the watcher loads it like
        an edit on disk. The caller holds the lock.
        """
        previous = self.running
        candidate = await self.open_candidate({edit.file: edit.text for edit in edits}, actor)

        try:
            saved = [await pipeline.save_settings_file(edit, actor) for edit in edits]
        except BaseException:
            await candidate.exit_stack.aclose()
            raise

        self.publish(candidate)
        self.logger.info(f"Settings saved from the Web and reloaded: {describe(SettingsReloaded(self.running, previous))}.")
        return saved

    async def open_candidate(self, candidates: Mapping[SettingsFile, str], administrator: UserId | None) -> OpenedRuntime:
        """
        A runtime a reload may make current: the settings loaded with the candidate texts, the whole startup within
        api.settings_build_timeout_seconds, and an editor an administrator can still sign in to: `administrator` for a
        save, anyone for a reload from disk. Any failure is InvalidSettingsError, and a cancel propagates, both with
        whatever opened already closed.
        """
        current = self.opened[-1].runtime
        timeout = current.config.api.settings_build_timeout_seconds
        stack = AsyncExitStack()

        try:
            async with asyncio.timeout(timeout):
                config = startup_settings(self.project_root, candidates, current.config.environment, current.config.audience)
                runtime = await stack.enter_async_context(self.opener(config))
                await runtime.signed_out.confirm_editor_access(await current.signed_out.load_sign_in_options(), administrator)
        except BaseException as error:
            await asyncio.shield(stack.aclose())

            if isinstance(error, TimeoutError):
                raise InvalidSettingsError([SettingsProblem(message=f"The app did not start within {timeout:g} seconds.")]) from None

            if isinstance(error, Exception):
                raise InvalidSettingsError(startup_problems(error, self.logger)) from None

            raise

        return OpenedRuntime(runtime, stack)

    def publish(self, opened: OpenedRuntime) -> None:
        """Makes `opened` current and retires the runtime before it; runtimes that finished closing are dropped."""
        opened.runtime.become_current()
        self.opened[-1].retire()
        self.opened.append(opened)
        self.refused = None
        self.opened = [runtime for runtime in self.opened if runtime.closing is None or not runtime.closing.done()]

    async def close(self) -> None:
        """At process exit, after the runs were stopped: every runtime closes, a held one too, and the switch waits."""
        async with self.lock:
            for opened in self.opened:
                opened.retired = True
                opened.closing = opened.closing or asyncio.get_running_loop().create_task(opened.exit_stack.aclose())

            await asyncio.gather(*(opened.closing for opened in self.opened if opened.closing), return_exceptions=True)


@asynccontextmanager
async def open_runtime_switch(project_root: Path | None = None) -> AsyncGenerator[RuntimeSwitch]:
    """
    The process's runtimes, for the CLI and the Web API: the first one opened from config/ as startup always did, then
    any one a reload opens. The logger and the sign-in attempt log are the process's, shared by every runtime. Every
    runtime still open closes when the caller is done.
    """
    root = project_root or get_project_root()
    config = startup_settings(root)
    process = create_process_state(config)

    for notice in settings_notices(root):
        process.logger.warning(notice)

    switch = RuntimeSwitch(lambda candidate: open_runtime(candidate, process), root, process.logger)
    await switch.start(config)

    try:
        yield switch
    finally:
        await switch.close()


async def watch_settings(switch: RuntimeSwitch) -> None:
    """
    The Web API's look at config/ for edits made outside the app: every api.settings_poll_seconds of the current
    settings, a reload when a file changed. A reload or a refusal is logged once, and the same refused files are not
    tried again until they change. It never stops on an error of its own: it logs it and looks again at the next
    interval. The lifespan cancels it at shutdown.
    """
    while True:
        with switch.hold() as opened:
            interval = opened.runtime.config.api.settings_poll_seconds

        await asyncio.sleep(interval)

        try:
            reload = await switch.reload()
        except Exception as error:
            switch.logger.error(f"The settings files could not be checked: {type(error).__name__}: {error}")
            continue

        if isinstance(reload, SettingsReloaded):
            switch.logger.info(f"Settings reloaded from disk: {describe(reload)}.")


async def collect_daily_data(switch: RuntimeSwitch) -> None:
    """
    The Web API's collection of the daily data, at the start, then every api.archive_interval_hours of the current
    settings, on the current runtime: first the TWSE and TPEX open data the OpenAPI serves only for its latest session,
    day, month or quarter (closes, material information, EPS statistics, valuation ratios, balance sheets, income
    statements, monthly revenue and TWSE news) into the archive, then, on a personal site, the exchanges' daily reports
    of the sessions its history cache lacks, then the news of the stocks users hold or watch into the article store.
    Before them, a Shioaji login that is down is made again
    (RuntimeSwitch.log_in_again). A step never stops it on an error of its own: it logs it, goes on to the next and
    tries again at the next interval. The lifespan cancels it at shutdown and waits until the step it stopped has ended.
    """
    while True:
        await switch.log_in_again()

        with switch.hold() as opened:
            interval = opened.runtime.config.api.archive_interval_hours
            pipeline = opened.runtime.signed_out

            for step, failure in (
                (pipeline.archive_daily_closes, "The open data could not be archived"),
                (pipeline.refresh_daily_history, "The exchanges' daily history could not be refreshed"),
                (pipeline.refresh_article_store, "The article store could not be refreshed"),
            ):
                try:
                    await step()
                except Exception as error:
                    switch.logger.error(f"{failure}: {type(error).__name__}: {error}")

        await asyncio.sleep(interval * 3600)


def describe(reload: SettingsReloaded) -> str:
    """`appsetting.yaml 1a2b3c4d5e6f -> 6f5e4d3c2b1a`, for each file whose revision changed."""
    changed = [file for file in SettingsFile if reload.revisions.get(file) != reload.previous.get(file)]
    return ", ".join(
        f"{file.file_name} {reload.previous.get(file, '')[:12]} -> {reload.revisions.get(file, '')[:12]}" for file in changed
    )
