"""
The daily allowance of paid AI calls, through DailyCappedAiProvider over a real database of each backend: a user's
limit, the server's total, an administrator's calls (counted, never refused), and the next Taiwan day.
"""

import asyncio
from datetime import timedelta

import chromadb
import pytest
from support.fakes import AiVendor
from support.harness import ADMINISTRATOR, MARKET_OPEN, MEMBER
from support.settings import shipped_config
from trading_stack import MovableClock, SilentLogger

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.types.errors import SignInRequired
from a_domain.types.ids import UserId
from b_application.config.ai_config import PromptsConfig
from c_infrastructure.ai_models.ai_adapter.daily_capped_ai_provider import AiAllowanceSpentError, DailyCappedAiProvider
from c_infrastructure.database.db_connector import DatabaseConnector
from d_presentation.dependencies import create_owned_ports

pytestmark = pytest.mark.asyncio

QUESTION = (Message(role=MessageRole.USER, content="?", timestamp=MARKET_OPEN),)


async def spend(provider: IAiProvider, calls: int) -> None:
    for _ in range(calls):
        await provider.generate_reply(QUESTION)


async def test_a_user_past_the_daily_limit_is_refused_until_the_next_taiwan_day(database: DatabaseConnector) -> None:
    vendor, clock = AiVendor(), MovableClock(MARKET_OPEN)
    user = DailyCappedAiProvider(vendor, database.for_owner(UserId("user")), clock, daily_calls=3, daily_calls_total=100)
    await spend(user, 3)

    with pytest.raises(AiAllowanceSpentError):
        await user.generate_reply(QUESTION)

    clock.current = MARKET_OPEN.replace(hour=0) + timedelta(days=1)
    await user.generate_reply(QUESTION)
    assert vendor.calls == 4


async def test_the_server_total_refuses_users_but_never_an_administrator(database: DatabaseConnector) -> None:
    vendor, clock = AiVendor(), MovableClock(MARKET_OPEN)
    administrator = DailyCappedAiProvider(vendor, database.for_owner(UserId("admin")), clock, daily_calls=None, daily_calls_total=5)
    first, second = (
        DailyCappedAiProvider(vendor, database.for_owner(UserId(user)), clock, daily_calls=3, daily_calls_total=5)
        for user in ("a", "b")
    )
    await spend(first, 3)
    await spend(administrator, 2)

    with pytest.raises(AiAllowanceSpentError):
        await second.generate_reply(QUESTION)

    await spend(administrator, 10)
    assert vendor.calls == 15


async def test_a_refused_call_counts_against_nothing(database: DatabaseConnector) -> None:
    vendor, clock = AiVendor(), MovableClock(MARKET_OPEN)
    user = DailyCappedAiProvider(vendor, database.for_owner(UserId("user")), clock, daily_calls=1, daily_calls_total=2)
    other = DailyCappedAiProvider(vendor, database.for_owner(UserId("other")), clock, daily_calls=1, daily_calls_total=2)
    await spend(user, 1)

    for _ in range(3):
        with pytest.raises(AiAllowanceSpentError):
            await user.generate_reply(QUESTION)

    await spend(other, 1)
    assert vendor.calls == 2


async def test_a_provider_built_for_no_owner_never_asks_the_vendor(database: DatabaseConnector) -> None:
    vendor = AiVendor()

    with pytest.raises(SignInRequired):
        await DailyCappedAiProvider(vendor, database.for_owner(None), MovableClock(MARKET_OPEN), 3, 100).generate_reply(QUESTION)

    assert vendor.calls == 0


async def test_the_wiring_caps_a_user_at_the_daily_calls_and_never_an_administrator(database: DatabaseConnector) -> None:
    config = shipped_config()
    config = config.model_copy(
        update={
            "prompts": PromptsConfig(social_sentiment="Stock {stock_id}\n{posts_text}"),
            "accounts": config.accounts.model_copy(update={"daily_ai_calls": 2}),
        }
    )
    owned_ports = create_owned_ports(
        config, database, chromadb.EphemeralClient(), AiVendor(), MovableClock(MARKET_OPEN), SilentLogger(), asyncio.Lock()
    )
    member, administrator = owned_ports(MEMBER).ai_provider, owned_ports(ADMINISTRATOR).ai_provider
    await spend(member, 2)
    await spend(administrator, 5)

    with pytest.raises(AiAllowanceSpentError):
        await member.generate_reply(QUESTION)
