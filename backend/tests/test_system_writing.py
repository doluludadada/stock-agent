"""
The site's own writing: once a session's daily data is held, the Web API's timer writes the company card and the day's
brief of each of the monthly ranking's top stocks, on the site's own AI budget, resumably, and never orders.
"""

import asyncio
import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pytest
from support.harness import ADMINISTRATOR, MARKET_OPEN, CliHarness
from test_ranking import SESSIONS, market
from test_stock_brief import INSTRUCTIONS

from a_domain.model.chat.message import Message
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.ai.system_writing_log import SystemWriting
from a_domain.types.enums import BriefStatus, ExecutionProvider, MessageRole
from a_domain.types.errors import AiAllowanceSpentError
from b_application.pipeline import Pipeline
from c_infrastructure.ai_models.ai_adapter.system_ai_provider import SystemAiProvider
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.system_writing_log import SqlSystemWritingLog
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE
from d_presentation.dependencies import compose_runtime
from d_presentation.live_runtime import BriefTurns, write_for_system_stocks

pytestmark = pytest.mark.asyncio

TODAY = MARKET_OPEN.date()
MOVEMENT = json.dumps({"movement": [{"text": "The held data does not explain the move.", "sources": ["S1"]}]})


class SystemAi:
    """The AI of the site's own writing: it keeps the stock each prompt names and answers a brief, or raises a stock's failure."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.failures: dict[str, Exception] = {}

    async def __call__(self, messages: tuple[Message, ...]) -> Message:
        stock_id = messages[-1].content.split("Stock: ")[1].split(" ")[0]
        self.asked.append(stock_id)

        if stock_id in self.failures:
            raise self.failures[stock_id]

        return Message(role=MessageRole.ASSISTANT, content=MOVEMENT, timestamp=messages[-1].timestamp)


def writing_site(daily_ai_calls: int = 60, daily_stocks: int = 30, **system_writing: object) -> tuple[CliHarness, SystemAi]:
    """
    The ranking's market, whose top two are 2330 and 2317 at the session of March 17, with the brief's prompt and a
    system AI, which a budget of 0 leaves out as the wiring does. The runtime is composed again so that the Pipelines
    read the changed settings.
    """
    harness = market()
    page = harness.config.stock_page
    writing = page.system_writing.model_copy(update={"daily_ai_calls": daily_ai_calls, **system_writing})
    brief = page.brief.model_copy(update={"daily_stocks": daily_stocks})
    prompts = harness.config.prompts.model_copy(update={"stock_brief": INSTRUCTIONS["stock_brief_prompt"]})
    harness.config = harness.config.model_copy(
        update={"stock_page": page.model_copy(update={"system_writing": writing, "brief": brief}), "prompts": prompts}
    )
    ai = SystemAi()
    harness.system_ai.generate_reply = ai  # pyright: ignore[reportAttributeAccessIssue]
    harness.dependencies = replace(harness.dependencies, system_ai_provider=harness.system_ai if daily_ai_calls else None)
    harness.runtime = compose_runtime(harness.config, harness.logger, harness.clock, harness.dependencies)
    return harness, ai


def writer(harness: CliHarness) -> Pipeline:
    pipeline = harness.runtime.system_writer
    assert pipeline is not None
    return pipeline


async def step(harness: CliHarness) -> None:
    await write_for_system_stocks(harness.runtime.system_writer, BriefTurns(), harness.logger)


def next_session(harness: CliHarness, day: date) -> None:
    for history in harness.prices.history.values():
        close = history[-1].close + 1
        history.append(
            Ohlcv(
                ts=datetime.combine(day, time(13, 30), TAIWAN_TIMEZONE),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=10**6,
            )
        )


async def test_a_round_begins_with_the_rankings_top_stocks_and_ranks_the_market_once(monkeypatch: pytest.MonkeyPatch) -> None:
    harness, _ = writing_site()
    loads: list[int] = []
    load = harness.dependencies.bar_matrix_provider.load_ranking_history

    async def counted():
        loads.append(1)
        return await load()

    monkeypatch.setattr(harness.dependencies.bar_matrix_provider, "load_ranking_history", counted)
    pipeline = writer(harness)
    restarted = compose_runtime(harness.config, harness.logger, harness.clock, harness.dependencies).system_writer

    assert await pipeline.load_system_writing() == ["2330", "2317"]
    assert await pipeline.load_system_writing() == ["2330", "2317"]
    assert restarted is not None and await restarted.load_system_writing() == ["2330", "2317"]

    assert len(loads) == 1
    assert harness.system_writings.rounds == {
        SESSIONS[-1]: SystemWriting(session=SESSIONS[-1], started_on=TODAY, stock_ids=["2330", "2317"])
    }


async def test_the_timer_writes_each_stocks_brief_on_the_sites_own_model_and_the_round_is_done() -> None:
    harness, ai = writing_site()
    users_ai_calls: list[object] = []
    harness.ai.generate_reply = users_ai_calls.append  # pyright: ignore[reportAttributeAccessIssue]

    await step(harness)
    await step(harness)

    assert ai.asked == ["2330", "2317"] and users_ai_calls == []
    written = [await harness.briefs.find(stock_id, TODAY) for stock_id in ("2330", "2317")]
    assert [(brief.status, brief.model) for brief in written if brief is not None] == [(BriefStatus.WRITTEN, "claude-haiku-5-5")] * 2
    assert await writer(harness).load_system_writing() == []
    assert harness.company_basics.asked == ["2330", "2317"]
    assert [stock_id for stock_id, _ in harness.annual_reports.asked] == ["2330", "2330", "2317", "2317"]
    assert harness.broker.fills == [] and harness.journal.orders == {}


async def test_a_new_round_waits_for_a_new_session_and_writes_once_per_day() -> None:
    harness, ai = writing_site()
    await step(harness)

    next_session(harness, date(2026, 3, 18))
    await step(harness)
    assert ai.asked == ["2330", "2317"], "the day's briefs are written already"

    harness.clock.current_time = MARKET_OPEN + timedelta(days=1)
    await step(harness)
    assert ai.asked == ["2330", "2317"], "no new session since the round of March 18 was done"

    next_session(harness, date(2026, 3, 19))
    await step(harness)
    assert ai.asked == ["2330", "2317", "2330", "2317"]
    assert sorted(harness.system_writings.rounds) == [date(2026, 3, 17), date(2026, 3, 18), date(2026, 3, 19)]


async def test_a_spent_budget_stops_the_round_which_goes_on_where_it_stopped() -> None:
    harness, ai = writing_site()
    ai.failures["2317"] = AiAllowanceSpentError("The site's own AI calls of today are spent.")

    await step(harness)

    assert ai.asked == ["2330", "2317"]
    assert await writer(harness).load_system_writing() == ["2317"]
    assert await harness.briefs.find("2317", TODAY) is None, "a refused call keeps no claim"
    assert any("stops for now at 2317" in message for _, message in harness.logger.records)

    ai.failures.clear()
    harness.runtime = compose_runtime(harness.config, harness.logger, harness.clock, harness.dependencies)
    await step(harness)

    assert ai.asked == ["2330", "2317", "2317"]
    assert await writer(harness).load_system_writing() == []


async def test_a_stock_that_fails_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    harness, ai = writing_site()
    write = Pipeline.write_stock_brief

    async def failing(pipeline: Pipeline, stock_id: str):
        if stock_id == "2330":
            raise RuntimeError("the news site answered nonsense")
        return await write(pipeline, stock_id)

    monkeypatch.setattr(Pipeline, "write_stock_brief", failing)
    await step(harness)

    assert ai.asked == ["2317"]
    assert ("error", "The site's own writing failed for 2330: RuntimeError: the news site answered nonsense") in harness.logger.records
    assert await writer(harness).load_system_writing() == ["2330"]


async def test_a_brief_the_ai_fails_to_write_is_asked_again_at_the_next_look() -> None:
    harness, ai = writing_site()
    ai.failures["2330"] = RuntimeError("vendor down")

    await step(harness)
    failed = await harness.briefs.find("2330", TODAY)
    ai.failures.clear()
    await step(harness)

    assert failed is not None and failed.status == BriefStatus.FAILED
    assert ai.asked == ["2330", "2317", "2330"]
    assert (await harness.briefs.find("2330", TODAY)).status == BriefStatus.WRITTEN  # type: ignore[union-attr]


async def test_a_budget_of_zero_turns_the_sites_own_writing_off_and_ranks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    harness, ai = writing_site(daily_ai_calls=0)

    async def never():
        raise AssertionError("the market was ranked")

    monkeypatch.setattr(harness.dependencies.bar_matrix_provider, "load_ranking_history", never)
    await step(harness)

    assert harness.runtime.system_writer is None
    assert ai.asked == [] and harness.system_writings.rounds == {}


async def test_a_request_on_the_signed_out_pipeline_never_spends_the_sites_budget() -> None:
    harness, ai = writing_site()

    answer = await harness.runtime.signed_out.write_stock_brief("2330")

    assert ai.asked == [], "only the timer's system writer holds the system's provider"
    assert answer is not None and answer.today is not None and answer.today.status == BriefStatus.FAILED
    assert any("Stock brief failed for 2330: SignInRequired" in message for _, message in harness.logger.records)


async def test_the_sites_briefs_take_none_of_the_stocks_viewers_may_ask_for_a_day() -> None:
    harness, ai = writing_site(daily_stocks=1)
    viewer, viewers_ai = harness.runtime.pipeline_for(ADMINISTRATOR, ExecutionProvider.MOCK), SystemAi()
    harness.ai.generate_reply = viewers_ai  # pyright: ignore[reportAttributeAccessIssue]

    await step(harness)

    assert ai.asked == ["2330", "2317"], "no limit of stocks holds the site's own writing"
    assert (await viewer.load_stock_brief("1101")).stocks_left == 1, "the day's one stock is still the viewers'"

    answer = await viewer.write_stock_brief("1101")

    assert answer is not None and answer.today is not None
    assert (answer.today.status, answer.stocks_left, viewers_ai.asked) == (BriefStatus.WRITTEN, 0, ["1101"])


async def test_a_viewer_who_spent_the_days_stocks_does_not_stop_the_sites_own_writing() -> None:
    harness, ai = writing_site(daily_stocks=1)
    harness.ai.generate_reply = SystemAi()  # pyright: ignore[reportAttributeAccessIssue]
    await harness.runtime.pipeline_for(ADMINISTRATOR, ExecutionProvider.MOCK).write_stock_brief("1101")

    await step(harness)

    assert ai.asked == ["2330", "2317"]
    assert await writer(harness).load_system_writing() == []


async def test_the_timer_waits_for_a_stocks_turn_while_a_viewers_request_holds_it() -> None:
    harness, ai = writing_site()
    turns = BriefTurns()

    async with turns.of("2330"):
        timer = asyncio.get_running_loop().create_task(write_for_system_stocks(harness.runtime.system_writer, turns, harness.logger))
        await asyncio.sleep(0.05)
        assert ai.asked == []

    await timer
    assert ai.asked == ["2330", "2317"]


async def test_users_stocks_follow_the_rankings_only_where_the_setting_says_so() -> None:
    off, _ = writing_site()
    on, _ = writing_site(users_stocks=True)

    for harness in (off, on):
        harness.users_stocks.stock_ids = {"1101", "2330"}

    assert await writer(off).load_system_writing() == ["2330", "2317"]
    assert await writer(on).load_system_writing() == ["2330", "2317", "1101"]


async def test_no_round_begins_while_nothing_is_ranked_and_no_users_stock_is_taken() -> None:
    harness, ai = writing_site()
    harness.archive.monthly_revenues.clear()

    await step(harness)

    assert ai.asked == [] and harness.system_writings.rounds == {}


# ------------------------------------------------- the tables ------------------------------------------------- #


class CountingAi:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        self.calls += 1
        return Message(role=MessageRole.ASSISTANT, content="ok", timestamp=MARKET_OPEN)

    def save_response(self, stock_id: str, content: str) -> None:
        return None


async def test_the_sites_calls_are_counted_per_day_apart_from_every_user_and_refused_past_the_budget(
    database: DatabaseConnector,
) -> None:
    from support.databases import execute
    from trading_stack import MovableClock

    clock, vendor = MovableClock(MARKET_OPEN), CountingAi()
    system = SystemAiProvider(vendor, database, clock, daily_calls=2)
    question = (Message(role=MessageRole.USER, content="?", timestamp=MARKET_OPEN),)

    await system.generate_reply(question)
    await system.generate_reply(question)

    with pytest.raises(AiAllowanceSpentError):
        await system.generate_reply(question)

    clock.current = MARKET_OPEN + timedelta(days=1)
    await system.generate_reply(question)

    with pytest.raises(AiAllowanceSpentError):
        await SystemAiProvider(vendor, database, clock, daily_calls=0).generate_reply(question)

    assert vendor.calls == 3
    await execute("DO $$ BEGIN ASSERT (SELECT count(*) FROM ai_calls) = 0 AND (SELECT count(*) FROM ai_call_totals) = 0; END $$")
    await execute("DO $$ BEGIN ASSERT (SELECT array_agg(calls ORDER BY day) FROM system_ai_calls) = ARRAY[2, 1]; END $$")


async def test_the_first_round_begun_for_a_session_is_the_one_kept(database: DatabaseConnector) -> None:
    log = SqlSystemWritingLog(database)
    first = SystemWriting(session=SESSIONS[-1], started_on=TODAY, stock_ids=["2330", "2317"])
    second = SystemWriting(session=SESSIONS[-1], started_on=TODAY + timedelta(days=1), stock_ids=["1101"])

    assert await log.find(SESSIONS[-1]) is None
    assert await log.begin(first) == first
    assert await log.begin(second) == first
    assert await log.find(SESSIONS[-1]) == first
