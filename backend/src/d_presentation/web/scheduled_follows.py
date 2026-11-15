import asyncio

from a_domain.types.enums import ExecutionProvider
from a_domain.types.errors import RankingUnavailable
from a_domain.types.ids import RunId
from d_presentation.live_runtime import OpenedRuntime, RuntimeSwitch
from d_presentation.web.workflow_runs import RunInProgress, TooManyRuns, WorkflowRuns


async def follow_rankings_on_schedule(switch: RuntimeSwitch, runs: WorkflowRuns) -> None:
    """
    The Web API's timer of the scheduled ranking follows: every api.follow_schedule_poll_seconds of the current
    settings it starts the follows that are due (start_due_follows), on the current runtime. It is the one timer that
    starts a run that orders, and it orders on a user's mock account alone. It never stops on an error of its own: it
    logs it and looks again at the next interval. The lifespan cancels it at shutdown; a follow it started is a run of
    the server like any other and is cancelled with them.
    """
    while True:
        with switch.hold() as opened:
            interval = opened.runtime.config.api.follow_schedule_poll_seconds

            try:
                await start_due_follows(opened, runs)
            except Exception as error:
                switch.logger.error(f"The scheduled ranking follows could not be looked at: {type(error).__name__}: {error}")

        await asyncio.sleep(interval)


async def start_due_follows(opened: OpenedRuntime, runs: WorkflowRuns) -> list[RunId]:
    """
    Starts the ranking follow of each user whose schedule is due now, as the button's route starts one: the same
    operation (Pipeline.follow_ranking) on the user's own Pipeline, as a background run of the server, one at a time per
    user, recorded as started by the schedule. The Pipeline is the user's on the mock account, whoever the user is: no
    setting names the broker of a scheduled follow. Nothing starts while the site prices its orders on realtime quotes
    and has none, as the route refuses then; the next look tries again. A user whose run is running, or whose follow
    cannot start, is left to the next look. It answers the runs it started.
    """
    runtime = opened.runtime
    started: list[RunId] = []

    if runtime.quotes_missing:
        return started

    for user in await runtime.signed_out.load_scheduled_followers():
        if runs.running(user.user_id) is not None:
            continue

        pipeline = runtime.pipeline_for(user, ExecutionProvider.MOCK)

        try:
            if not (await pipeline.load_follow_schedule(user)).due:
                continue

            cap = runtime.config.accounts.max_concurrent_runs
            started.append(
                runs.start(
                    user, opened.hold(), lambda run_id, follow=pipeline.follow_ranking: follow(run_id=run_id, scheduled=True), cap
                )
            )
            runtime.logger.info(f"The schedule of user {user.user_id} started the ranking follow {started[-1]}.")
        except (RankingUnavailable, RunInProgress, TooManyRuns) as error:
            runtime.logger.info(f"The scheduled ranking follow of user {user.user_id} waits: {error}")

    return started
