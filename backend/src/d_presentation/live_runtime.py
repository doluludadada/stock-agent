"""
Where the runtime a Web request, a background run or a CLI option uses comes from. The process keeps the runtimes it
opened, oldest first; the last is current. New work holds the current one until it ends; a reload opens a whole new
runtime first and only then makes it current, and a runtime no longer current closes once nothing holds it. The
settings a runtime was built from never change under the work that holds it.
"""

import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Self

from pydantic import SecretStr

from a_domain.model.system.user import GoogleConfirmation, User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.settings_files import SettingChange, SettingsEdit, SettingsProblem
from a_domain.types.enums import ExecutionProvider, SettingsFile
from a_domain.types.errors import AiAllowanceSpentError, SettingsConflictError
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import (
    InvalidSettingsError,
    get_project_root,
    production_notice,
    settings_notices,
    settings_revision,
    settings_texts,
    startup_settings,
)
from b_application.pipeline import Pipeline
from d_presentation.dependencies import STARTUP_REFUSALS, Runtime, create_process_state, open_runtime

if TYPE_CHECKING:
    from shioaji import Shioaji

type RuntimeOpener = Callable[[AppConfig, Shioaji | None], AbstractAsyncContextManager[Runtime]]
"""
Opens a runtime on the settings. The client is the one whose login a renewal replaces, which the runtime logs in past;
None opens on any login that is up and makes no login but the connection's first (ShioajiQuoteProvider.connect).
"""


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
    nothing holds it. One lock serializes the reloads, the saves and the login renewals (log_in_again); taking a hold
    never waits for it.
    """

    def __init__(self, opener: RuntimeOpener, project_root: Path, logger: ILoggingProvider) -> None:
        self.logger = logger
        # One writer of a stock's brief at a time, whichever runtime a request holds: a second request for the stock
        # waits for the first and finds its card and its company's reads done, so nothing is fetched or written twice.
        self.brief_turns: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.opener = opener
        self.project_root = project_root
        self.lock = asyncio.Lock()
        self.opened: list[OpenedRuntime] = []
        self.refused: ReloadRefused | None = None

    async def start(self, config: AppConfig) -> None:
        """Opens the first runtime, as startup always has: a refusal propagates as raised, and the process exits on it."""
        stack = AsyncExitStack()
        runtime = await stack.enter_async_context(self.opener(config, None))
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
        The watcher's and the CLI's reload rule: when the settings files on disk differ from both the revisions the
        current runtime runs on and the last refused ones, opens a runtime from the files as they are and makes it
        current. None when there is nothing new to load. A refusal leaves the current runtime serving and is kept, so
        the same files are not tried again until they change. Running it twice changes nothing the second time.
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

    async def log_in_again(self) -> bool:
        """
        Makes the Shioaji login again once it is due (Runtime.login_due): opens a runtime on the current one's settings,
        never on the files on disk, past its client, and makes it current only when it serves no less (serves_no_less),
        so a run under way keeps its client to its end. Otherwise it closes, and one whose login came up without the
        SinoPac it needed counts as a failed login; a login that outlasts api.settings_build_timeout_seconds goes on and
        counts as no failure. True when it became current.
        """
        if not self.opened[-1].runtime.login_due:
            return False

        async with self.lock:
            current = self.opened[-1].runtime

            if current.shioaji is None or not current.login_due:
                return False

            timeout = current.config.api.settings_build_timeout_seconds
            opened = await opened_within(self.opener, current.config, current.shioaji.client, timeout, self.logger)

            if opened is None:
                self.logger.warning("The Shioaji login was not made again: the runtime before serves on")
                return False

            came_up = opened.runtime.realtime_quotes
            if serves_no_less(opened.runtime, current):
                self.publish(opened)
                self.logger.info("Logged in to Shioaji again on a new client: new runs and reads use it")
                return True

            await opened.exit_stack.aclose()

            if came_up:
                current.shioaji.connection.failed(current.market_clock.now())

            self.logger.warning("The Shioaji login was not made again: the runtime before serves on")
            return False

    async def save(
        self,
        opened: OpenedRuntime,
        administrator: User,
        changes: Sequence[SettingChange],
        *,
        password: SecretStr | None,
        google_confirmation: GoogleConfirmation | None = None,
        client: str,
        host: str,
    ) -> list[SettingsEdit]:
        """
        The settings form's save, running at once or refused with the app as it was. The request's runtime must still
        be current: a page that read settings the server no longer runs is a conflict. The administrator's Pipeline
        reviews the changes and confirms the password, or for an administrator without one the fresh Google
        authentication `google_confirmation` names, started from the session that saves; changes that change no file end
        there.

        A change that turns a broker's ordering off is reviewed and, once the administrator confirmed, written on its
        own before the rest is even reviewed again. The settings files on disk are the ordering switch every order
        asks (IOrderingSwitch), so ordering is off from that write on, in every process, whatever refuses the rest of
        the save afterwards, and a runtime opened from the files then becomes current (publish_from_disk), so the pages
        answer ordering off at once. Everything else of a refused save stays unwritten. A change of SinoPac's server is
        part of the rest (ServerSwitchRule), so a refused switch leaves ordering off. The runtime the save opens logs in
        on the new server. Work that started earlier finishes on the runtime it holds.
        """
        async with self.lock:
            if opened is not self.opened[-1]:
                raise SettingsConflictError("The server reloaded its settings after this page read them; read them again")

            pipeline, actor = opened.runtime.pipeline_for(administrator, ExecutionProvider.MOCK), administrator.user_id
            switching_off = await pipeline.review_settings_form([change for change in changes if change.turns_ordering_off], host)
            edits = [] if switching_off else await pipeline.review_settings_form(changes, host)
            await pipeline.confirm_settings_save(administrator, password, google_confirmation, client)
            switched_off = [await pipeline.save_settings_file(edit, actor) for edit in switching_off]

            if not switched_off:
                return await self.write_and_publish(pipeline, edits, actor) if edits else []

            try:
                rest = await pipeline.review_settings_form(changes, host)
                return await self.write_and_publish(pipeline, rest, actor) or switched_off
            except Exception:
                await self.publish_from_disk()
                raise

    async def publish_from_disk(self) -> None:
        """
        Makes a runtime opened from the settings files as they are on disk current, best effort: after a save wrote its
        turn-off of ordering and the rest was refused. One that would not open leaves the current one serving, and the
        watcher tries again. The caller holds the lock.
        """
        try:
            self.publish(await self.open_candidate({}, None))
        except InvalidSettingsError as error:
            self.logger.warning(f"The settings on disk after a refused save were not loaded:\n{error}")

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
        save, anyone for a reload from disk. SinoPac's server switches only while no SinoPac order of any user awaits
        settlement, counted on the current runtime's database right before the check: a save's review counted them too,
        but an order may have come to await settlement since, and an edit on disk, the CLI's reload and the timer's new
        login have no review. Any failure is InvalidSettingsError, and a cancel propagates, both with whatever opened
        already closed.
        """
        current = self.opened[-1].runtime
        timeout = current.config.api.settings_build_timeout_seconds
        stack = AsyncExitStack()

        try:
            async with asyncio.timeout(timeout):
                unsettled = await current.users_orders.awaiting_settlement(ExecutionProvider.SHIOAJI)
                config = startup_settings(self.project_root, candidates, current.config, unsettled=unsettled)
                runtime = await stack.enter_async_context(self.opener(config, None))
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


def serves_no_less(renewed: Runtime, current: Runtime) -> bool:
    """
    Whether a renewal's runtime serves no less than the current one, so it may become current: it has realtime quotes,
    and SinoPac where the site offers it, unless the current one has no SinoPac to order on either: none, as on a site
    whose account check always fails, such as the CA certificate's activation on production, or one whose own client
    Shioaji reported down. So such a site still takes its renewals, and quotes alone are better than none.
    """
    return renewed.realtime_quotes and (
        renewed.real_broker is not None or current.real_broker is None or not current.real_broker.link().up
    )


async def opened_within(
    opener: RuntimeOpener, config: AppConfig, replaced: Shioaji | None, timeout: float, logger: ILoggingProvider
) -> OpenedRuntime | None:
    """
    A runtime `opener` opened on `config` past the client `replaced` within `timeout` seconds, or None when it would not open,
    logged by the error's type alone: a driver's text can carry a connection string. A cancel closes what opened and
    propagates.
    """
    stack = AsyncExitStack()

    try:
        async with asyncio.timeout(timeout):
            runtime = await stack.enter_async_context(opener(config, replaced))
    except BaseException as error:
        await asyncio.shield(stack.aclose())

        if not isinstance(error, Exception):
            raise

        logger.warning(f"A runtime to log in to Shioaji again would not open: {type(error).__name__}")
        return None

    return OpenedRuntime(runtime, stack)


@asynccontextmanager
async def open_runtime_switch(project_root: Path | None = None) -> AsyncGenerator[RuntimeSwitch]:
    """
    The process's runtimes, for the CLI and the Web API: the first one opened from config/ as startup always did, then
    any one a reload opens. The logger and the sign-in attempt log are the process's, shared by every runtime. Every
    runtime still open closes when the caller is done.
    """
    root = project_root or get_project_root()
    config = startup_settings(root, unsettled=0)
    process = create_process_state(config)

    for notice in [*settings_notices(root), *production_notice(config)]:
        process.logger.warning(notice)

    switch = RuntimeSwitch(lambda candidate, replaced: open_runtime(candidate, process, replaced=replaced), root, process.logger)
    await switch.start(config)

    try:
        yield switch
    finally:
        await switch.close()


async def watch_settings(switch: RuntimeSwitch) -> None:
    """
    The Web API's look at config/ for edits made outside the app: every api.settings_poll_seconds of the current
    settings, a reload when a file changed (RuntimeSwitch.reload). A reload or a refusal is logged once, and the same
    refused files are not tried again until they change. It never stops on an error of its own: it logs it and looks
    again at the next interval. The lifespan cancels it at shutdown.
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


async def run_steps(logger: ILoggingProvider, *steps: tuple[Callable[[], Awaitable[object]], str]) -> None:
    """
    A timer's round: each step in order, given with the words that say it failed. A step never stops the round on an
    error of its own: it is logged under those words and the next step goes on. A spent budget of AI calls is no
    error: it is said once, and the step waits for the next round.
    """
    for step, failure in steps:
        try:
            await step()
        except AiAllowanceSpentError as error:
            logger.info(f"{failure} for now: {error}")
        except Exception as error:
            logger.error(f"{failure}: {type(error).__name__}: {error}")


async def collect_daily_data(switch: RuntimeSwitch) -> None:
    """
    The Web API's collection of the daily data, on the current runtime: the TWSE and TPEX open data the OpenAPI serves
    only for its latest period into the archive, on a personal site the exchanges' daily reports of the sessions its
    history cache lacks, the monthly ranking, the news of the stocks users hold or watch into the article store, and
    the site's own writing for the ranking's top stocks (write_for_system_stocks). It runs a round at the start, then
    at api.archive_interval_hours after the last or at the next weekday's market_hours.settled, whichever comes first.
    It loads the ranking right after the daily history, so a new session's ranking history is built here and not in a
    viewer's request. A step's error is logged and the next step goes on (run_steps). The lifespan cancels it at
    shutdown and waits until the step it stopped has ended.
    """
    while True:
        with switch.hold() as opened:
            interval = timedelta(hours=opened.runtime.config.api.archive_interval_hours)
            pipeline = opened.runtime.signed_out
            clock = opened.runtime.market_clock
            # Read before the round, so a round that ends past the settle starts the next one at once.
            settled = clock.next_settled_time()

            await run_steps(
                switch.logger,
                (pipeline.archive_daily_closes, "The open data could not be archived"),
                (pipeline.refresh_daily_history, "The exchanges' daily history could not be refreshed"),
                (pipeline.load_ranking, "The monthly ranking could not be loaded"),
                (pipeline.refresh_article_store, "The article store could not be refreshed"),
                (
                    partial(write_for_system_stocks, opened.runtime.system_writer, switch.brief_turns, switch.logger),
                    "The site's own writing could not go on",
                ),
            )
            wait = min(interval, settled - clock.now())

        await asyncio.sleep(wait.total_seconds())


async def collect_world(switch: RuntimeSwitch) -> None:
    """
    The Web API's world timer, at the start, then every api.world_interval_minutes of the current settings, on the current
    runtime: the world news feeds and the world indicators' tables read into what the site holds
    (Pipeline.refresh_world), at the feeds' own pace, since a wire service's feed lists only its last few hours; then,
    on the runtime's system writer, the day's world brief once it is due (Pipeline.write_world_brief), which is no
    step while the site's own writing is off. A step never stops it on an error of its own: it logs it and tries again
    at the next round; a spent budget of the site's own AI calls is said once a round. The lifespan cancels it at
    shutdown and waits until the step it stopped has ended. It sends no order: neither operation has an order step.
    """
    while True:
        with switch.hold() as opened:
            interval = opened.runtime.config.api.world_interval_minutes
            writer = opened.runtime.system_writer
            steps = [(opened.runtime.signed_out.refresh_world, "The world could not be read")]
            steps += [(writer.write_world_brief, "The world brief could not be written")] if writer is not None else []

            await run_steps(switch.logger, *steps)

        await asyncio.sleep(interval * 60)


async def write_for_system_stocks(pipeline: Pipeline | None, turns: defaultdict[str, asyncio.Lock], logger: ILoggingProvider) -> None:
    """
    The timer's last step, on the runtime's system writer, None while the site's own writing is off: each stock the site
    still writes for by itself (Pipeline.load_system_writing) written in its turn as a viewer's request would
    (Pipeline.write_stock_brief). A stock that fails is logged and the next goes on; a spent budget ends the step until
    the next interval.
    """
    if pipeline is None:
        return

    for stock_id in await pipeline.load_system_writing():
        try:
            async with turns[stock_id]:
                await pipeline.write_stock_brief(stock_id)
        except AiAllowanceSpentError as error:
            logger.info(f"The site's own writing stops for now at {stock_id}: {error}")
            return
        except Exception as error:
            logger.error(f"The site's own writing failed for {stock_id}: {type(error).__name__}: {error}")


def describe(reload: SettingsReloaded) -> str:
    """`appsetting.yaml 1a2b3c4d5e6f -> 6f5e4d3c2b1a`, for each file whose revision changed."""
    changed = [file for file in SettingsFile if reload.revisions.get(file) != reload.previous.get(file)]
    return ", ".join(
        f"{file.file_name} {reload.previous.get(file, '')[:12]} -> {reload.revisions.get(file, '')[:12]}" for file in changed
    )
