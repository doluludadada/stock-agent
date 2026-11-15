import asyncio

from a_domain.model.system.user import User
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
    Starts the ranking follow of each user whose schedule is due now (start_follow_if_due). Nothing starts while the
    site prices its orders on realtime quotes and has none, as the route refuses then; the next look tries again. One
    user's error never keeps the users after them from their follow: a user whose run is running, or whose follow
    cannot start, waits for the next look, and any other error is logged for that user. It answers the runs it started.
    """
    runtime = opened.runtime
    started: list[RunId] = []

    if runtime.quotes_missing:
        return started

    for user in await runtime.signed_out.load_scheduled_followers():
        try:
            if (run_id := await start_follow_if_due(opened, runs, user)) is not None:
                started.append(run_id)
                runtime.logger.info(f"The schedule of user {user.user_id} started the ranking follow {run_id}.")
        except (RankingUnavailable, RunInProgress, TooManyRuns) as error:
            runtime.logger.info(f"The scheduled ranking follow of user {user.user_id} waits: {error}")
        except Exception as error:
            runtime.logger.error(f"The scheduled ranking follow of user {user.user_id} did not start: {type(error).__name__}: {error}")

    return started


async def start_follow_if_due(opened: OpenedRuntime, runs: WorkflowRuns, user: User) -> RunId | None:
    """
    Starts the ranking follow of a user whose schedule is due, as the button's route starts one: the same operation
    (Pipeline.follow_ranking) on the user's own Pipeline, as a background run of the server, one at a time per user,
    recorded as started by the schedule. The Pipeline is the user's on the mock account, whoever the user is: no
    setting names the broker of a scheduled follow. Whether it is due may take a read of the whole history, so the
    users whose schedule may run are asked for again right before the start: a user who turned the schedule off, was
    deactivated or lost a feature meanwhile is not followed. None for a user whose follow does not start.
    """
    runtime = opened.runtime

    if runs.running(user.user_id) is not None:
        return None

    pipeline = runtime.pipeline_for(user, ExecutionProvider.MOCK)

    if not (await pipeline.load_follow_schedule(user)).due:
        return None

    if user.user_id not in {follower.user_id for follower in await runtime.signed_out.load_scheduled_followers()}:
        return None

    cap = runtime.config.accounts.max_concurrent_runs

    return runs.start(user, opened.hold(), lambda run_id: pipeline.follow_ranking(run_id=run_id, scheduled=True), cap)
