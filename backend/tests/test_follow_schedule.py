"""
The scheduled ranking follow: when a user's schedule is due (the first session after a decision, from the user's time,
while the site places orders, once per decision and once a day), and the Web API's timer step that starts it: on the
user's mock account alone, recorded as started by the schedule, never twice for a decision, never for a deactivated
user or one the site hides the ranking or the mock account from, and never outside continuous trading or without a
realtime quote.
"""

import asyncio
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from support.harness import ADMINISTRATOR, ADMINISTRATOR_PASSWORD, MARKET_CLOSED, MARKET_OPEN, MEMBER, CliHarness
from support.web import app_of, client_at, ended, sign_in, write
from test_ranking_follow import CLOSES, FORMULA, daily_history, site
from test_ranking_formulas import CASH, ONE, falling_site, project  # noqa: F401

from a_domain.model.system.stats import SystemStats
from a_domain.rules.trading.follow import FollowScheduleRule, FollowTimeRule
from a_domain.rules.trading.ranking import DecisionSessionsRule
from a_domain.types.enums import ExecutionProvider, FeatureVisibility, OrderPricing, TradeAction, TradingPhase, UserStatus, Workflow
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE
from d_presentation.web.scheduled_follows import start_due_follows

pytestmark = pytest.mark.asyncio

NINE_FIVE = time(9, 5)
RULE = FollowScheduleRule(
    decision_rule=DecisionSessionsRule(decision_day=13, deadline_day=10),
    time_rule=FollowTimeRule(pricing=OrderPricing.REALTIME_QUOTE),
    times=(NINE_FIVE, time(13, 0)),
)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), TAIWAN_TIMEZONE)


def weekdays(first: date, last: date, *closed: date) -> list[date]:
    days = (first + timedelta(days=offset) for offset in range((last - first).days + 1))
    return [day for day in days if day.weekday() < 5 and day not in closed]


def follow(decided_on: date | None, started: datetime, *, scheduled: bool = False) -> SystemStats:
    return SystemStats(
        workflow=Workflow.RANKING_FOLLOW,
        execution_provider=ExecutionProvider.MOCK,
        start_time=started,
        ranking_decided_on=decided_on,
        scheduled=scheduled,
    )


def due(sessions: list[date], now: datetime, *follows: SystemStats, follow_time: time | None = NINE_FIVE) -> tuple[date | None, bool]:
    schedule = RULE.apply(follow_time, sessions, follows, now, TradingPhase.CONTINUOUS)
    return schedule.pending, schedule.due


# ----------------------------------- Rules ------------------------------------ #


def test_a_decision_is_due_from_the_users_time_on_the_first_session_after_it_and_not_on_its_own_day() -> None:
    sessions = weekdays(date(2026, 10, 1), date(2026, 10, 13))
    decided = date(2026, 10, 13)

    assert due(sessions, at(decided, 13)) == (None, False)
    assert due(sessions, at(date(2026, 10, 14), 9, 4)) == (decided, False)
    assert due(sessions, at(date(2026, 10, 14), 9, 5)) == (decided, True)
    assert due(sessions, at(date(2026, 10, 14), 13, 20)) == (decided, True)
    assert due(sessions, at(date(2026, 10, 14), 13), follow_time=None) == (decided, False)


def test_the_schedule_follows_only_while_the_site_places_orders() -> None:
    sessions = weekdays(date(2026, 10, 1), date(2026, 10, 13))
    now = at(date(2026, 10, 14), 13, 27)

    phases = {phase: RULE.apply(NINE_FIVE, sessions, [], now, phase).due for phase in TradingPhase}

    assert phases == {phase: phase == TradingPhase.CONTINUOUS for phase in TradingPhase}


def test_a_decision_day_a_holiday_moves_is_followed_on_the_session_after_the_moved_decision() -> None:
    """October 13 and 14 have no session, so the month decides at the close of the 15th and is followed on the 16th."""
    sessions = weekdays(date(2026, 10, 1), date(2026, 10, 15), date(2026, 10, 13), date(2026, 10, 14))

    assert due(sessions, at(date(2026, 10, 15), 10)) == (None, False)
    assert due(sessions, at(date(2026, 10, 16), 10)) == (date(2026, 10, 15), True)


def test_a_missed_window_is_tried_on_each_later_session_until_the_next_decision_supersedes_it() -> None:
    october, november = date(2026, 10, 13), date(2026, 11, 13)
    until_november = weekdays(date(2026, 10, 1), date(2026, 11, 12))

    assert due(until_november[:9], at(date(2026, 10, 14), 14)) == (october, True)
    assert due(until_november[:20], at(date(2026, 10, 29), 9, 30)) == (october, True)
    assert due(until_november, at(date(2026, 11, 2), 9, 30)) == (october, True)
    assert due(until_november, at(november, 13)) == (october, True)
    assert due([*until_november, november], at(date(2026, 11, 16), 9, 30)) == (november, True)
    taken_late = follow(october, at(date(2026, 11, 2), 9, 31), scheduled=True)
    assert due([*until_november, november], at(date(2026, 11, 16), 9, 30), taken_late) == (november, True)


def test_a_decision_is_followed_once_whoever_took_it_and_a_schedule_that_tried_today_waits_for_the_next_session() -> None:
    sessions = weekdays(date(2026, 10, 1), date(2026, 10, 13))
    decided, wednesday, thursday = date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)
    by_hand = follow(decided, at(wednesday, 9, 2))
    by_schedule = follow(decided, at(wednesday, 9, 5), scheduled=True)
    refused = follow(None, at(wednesday, 9, 5), scheduled=True)
    refused_by_hand = follow(None, at(wednesday, 9, 5))

    assert due(sessions, at(wednesday, 10), by_hand) == (None, False)
    assert due(sessions, at(thursday, 10), by_schedule) == (None, False)
    assert due(sessions, at(wednesday, 10), refused) == (decided, False)
    assert due(sessions, at(thursday, 10), refused) == (decided, True)
    assert due(sessions, at(wednesday, 10), refused_by_hand) == (decided, True)


# ------------------------------- The timer step ------------------------------- #


async def administrator(client: httpx.AsyncClient) -> None:
    assert (await sign_in(client, ADMINISTRATOR.username, ADMINISTRATOR_PASSWORD)).status_code == 200


async def schedule(client: httpx.AsyncClient, at_time: str | None) -> httpx.Response:
    return await write(client, "PUT", "/v1/rankings/follow/schedule", {"time": at_time})


async def look(app: Any) -> list[Any]:
    """One look of the timer, on the runtime that serves new work now."""
    with app.state.runtime_switch.hold() as opened:
        return await start_due_follows(opened, app.state.workflow_runs)


async def finished(harness: CliHarness, run_id: Any) -> SystemStats:
    for _ in range(200):
        if (run := harness.journal.runs.get(run_id)) is not None and run.end_time is not None:
            return run

        await asyncio.sleep(0.01)

    raise AssertionError(f"run {run_id} did not finish")


def placed(harness: CliHarness) -> list[tuple[str, TradeAction]]:
    return [(order.stock_id, order.action) for order in harness.broker.placed]


async def test_the_schedule_is_off_until_the_user_chooses_one_of_the_offered_times_and_nothing_else_is_saved() -> None:
    harness = site()

    async with app_of(harness) as app, client_at(app) as client:
        await administrator(client)
        before = (await client.get("/v1/rankings/follow")).json()["schedule"]
        refused = await schedule(client, "09:07")
        chosen = await schedule(client, "09:30")
        after = (await client.get("/v1/rankings/follow")).json()["schedule"]
        me = (await client.get("/v1/auth/me")).json()
        off = await schedule(client, None)

    offered = ["09:05:00", "09:30:00", "10:00:00", "13:00:00"]
    assert before == {"time": None, "times": offered, "pending": "2026-10-13", "due": False}
    assert (refused.status_code, refused.json()["code"]) == (422, "follow_time_not_offered")
    assert (chosen.status_code, off.status_code) == (204, 204)
    assert after == {"time": "09:30:00", "times": offered, "pending": "2026-10-13", "due": True}
    assert me["ranking_follow_time"] == "09:30:00"
    assert harness.users.by_id[ADMINISTRATOR.user_id].ranking_follow_time is None
    assert placed(harness) == []


async def test_a_due_schedule_follows_the_ranking_on_the_mock_account_once_and_says_the_schedule_started_it() -> None:
    harness = site(sinopac=True)
    harness.hold("1101", 1000, 30.0)

    async with app_of(harness) as app, client_at(app) as client:
        await administrator(client)
        assert (await look(app)) == []
        await schedule(client, "09:05")
        [run_id] = await look(app)
        run = await finished(harness, run_id)
        again = await look(app)
        answer = (await client.get("/v1/rankings/follow")).json()

    async with app_of(harness) as restarted:
        after_a_restart = await look(restarted)

    assert (run.workflow, run.execution_provider, run.scheduled) == (Workflow.RANKING_FOLLOW, ExecutionProvider.MOCK, True)
    assert (run.ranking_decided_on, run.ranking_formula) == (date(2026, 10, 13), FORMULA)
    assert placed(harness) == [("1101", TradeAction.SELL), ("2330", TradeAction.BUY), ("2317", TradeAction.BUY)]
    assert harness.real_broker.placed == []
    assert (again, after_a_restart) == ([], [])
    assert [(row["run_id"], row["scheduled"], row["ranking_decided_on"]) for row in answer["follows"]] == [
        (str(run_id), True, "2026-10-13")
    ]
    assert (answer["schedule"]["pending"], answer["schedule"]["due"]) == (None, False)


async def test_a_window_the_schedule_missed_is_followed_on_the_next_session_and_costs_no_read_of_a_user_meanwhile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = site(now=MARKET_CLOSED)
    reads: list[int] = []
    users = harness.users.users

    async def counted() -> list[Any]:
        reads.append(len(reads))
        return await users()

    async with app_of(harness) as app, client_at(app) as client:
        await administrator(client)
        await schedule(client, "09:05")
        monkeypatch.setattr(harness.users, "users", counted)
        closed = await look(app)
        harness.clock.current_time = MARKET_OPEN.replace(hour=9, minute=4) + timedelta(days=1)
        early = await look(app)
        read_by_then = len(reads)
        harness.clock.current_time += timedelta(minutes=1)

        for stock_id, history in daily_history().items():
            harness.list_stock(stock_id, history, realtime_price=CLOSES[stock_id])

        [run_id] = await look(app)
        run = await finished(harness, run_id)

    assert (closed, early, read_by_then) == ([], [], 1)
    assert (run.scheduled, run.ranking_decided_on, len(placed(harness))) == (True, date(2026, 10, 13), 2)


async def test_no_scheduled_follow_starts_without_a_realtime_quote_login_and_the_decision_stays_pending() -> None:
    harness = site(realtime_quotes=False)

    async with app_of(harness) as app, client_at(app) as client:
        await administrator(client)
        await schedule(client, "09:05")
        started = await look(app)
        pending = (await client.get("/v1/rankings/follow")).json()["schedule"]["pending"]

    assert (pending, started, harness.journal.runs, placed(harness)) == ("2026-10-13", [], {}, [])


async def test_a_click_and_the_schedule_never_run_together_and_the_decision_the_click_took_is_not_followed_again() -> None:
    harness = site()

    async with app_of(harness) as app, client_at(app) as client:
        await administrator(client)
        await schedule(client, "09:05")
        clicked = await write(client, "POST", "/v1/rankings/follow", {})
        while_it_runs = await look(app)
        await ended(client, clicked.json()["run_id"])
        after_the_click = await look(app)

    assert (clicked.status_code, while_it_runs, after_the_click) == (202, [], [])
    assert [(run.scheduled, run.ranking_decided_on) for run in harness.journal.runs.values()] == [(False, date(2026, 10, 13))]
    assert placed(harness) == [("2330", TradeAction.BUY), ("2317", TradeAction.BUY)]


async def test_a_click_while_the_scheduled_follow_runs_is_refused_as_a_run_in_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = site()
    deciding = asyncio.Event()
    save_signals = harness.journal.save_signals

    async def held(run_id: Any, signals: Any) -> None:
        await deciding.wait()
        await save_signals(run_id, signals)

    monkeypatch.setattr(harness.journal, "save_signals", held)

    async with app_of(harness) as app, client_at(app) as client:
        await administrator(client)
        await schedule(client, "09:05")
        [run_id] = await look(app)
        clicked = await write(client, "POST", "/v1/rankings/follow", {})
        second_look = await look(app)
        deciding.set()
        await finished(harness, run_id)

    assert second_look == []

    assert (clicked.status_code, clicked.json()["code"]) == (409, "run_in_progress")
    assert [run.scheduled for run in harness.journal.runs.values()] == [True]
    assert placed(harness) == [("2330", TradeAction.BUY), ("2317", TradeAction.BUY)]


async def test_nobody_follows_for_a_deactivated_user_or_one_the_site_hides_the_ranking_or_the_mock_account_from() -> None:
    hidden = {}

    for feature in ("ranking", "mock_account"):
        harness = site(features={feature: FeatureVisibility.ADMINISTRATORS})
        harness.users.by_id[MEMBER.user_id] = replace(harness.users.by_id[MEMBER.user_id], ranking_follow_time=NINE_FIVE)

        async with app_of(harness) as app:
            hidden[feature] = (await look(app), harness.journal.runs)

    harness = site()
    harness.users.by_id[ADMINISTRATOR.user_id] = replace(
        harness.users.by_id[ADMINISTRATOR.user_id], ranking_follow_time=NINE_FIVE, status=UserStatus.DEACTIVATED
    )

    async with app_of(harness) as app:
        deactivated = await look(app)
        harness.users.by_id[ADMINISTRATOR.user_id] = replace(harness.users.by_id[ADMINISTRATOR.user_id], status=UserStatus.ACTIVE)
        [run_id] = await look(app)
        await finished(harness, run_id)

    assert hidden == {"ranking": ([], {}), "mock_account": ([], {})}
    assert (deactivated, len(placed(harness))) == ([], 2)


async def test_a_scheduled_follow_under_a_formula_that_holds_cash_sells_to_cash_on_the_mock_account(project: Path) -> None:  # noqa: F811
    harness = falling_site(project)
    harness.hold("2317", 1000, 50.0)
    harness.hold("1101", 1000, 30.0)

    async with app_of(harness) as app, client_at(app) as client:
        await administrator(client)
        saved = await client.put(
            "/v1/admin/settings",
            json={
                "confirm": True,
                "changes": [{"path": "ranking.active_formula", "value": CASH.name}],
                "password": ADMINISTRATOR_PASSWORD,
            },
        )
        await schedule(client, "09:05")
        [run_id] = await look(app)
        run = await finished(harness, run_id)
        again = await look(app)

    assert saved.status_code == 200, saved.text
    assert (run.scheduled, run.ranking_formula, ONE.name != CASH.name) == (True, CASH, True)
    assert placed(harness) == [("1101", TradeAction.SELL), ("2317", TradeAction.SELL)]
    assert (harness.real_broker.placed, again) == ([], [])
