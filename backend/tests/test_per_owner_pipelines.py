"""
Which ports dependencies.py hands each user's Pipeline: the signed-out one reads nobody's data, a user's own ports are
theirs, and only an administrator holds a real broker, only while its login is up. test_ai_allowance.py covers the AI
limit the wiring gives each.
"""

import pytest
from support.harness import ADMINISTRATOR, MEMBER, MEMBER_PASSWORD, build_harness, rising_history

from a_domain.rules.trading.order_rule import BrokerLink
from a_domain.types.enums import ExecutionProvider
from a_domain.types.errors import BrokerUnavailable, RealBrokerRefused, SignInRequired

pytestmark = pytest.mark.asyncio


async def test_the_signed_out_pipeline_reads_nobodys_data_but_answers_the_public_pages() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))
    signed_out = harness.runtime.signed_out

    for operation in (signed_out.load_watchlist(), signed_out.load_runs(10, 0), signed_out.load_technical_settings()):
        with pytest.raises(SignInRequired):
            await operation

    assert [stock.stock_id for stock in await signed_out.search_stocks("2330")] == ["2330"]


async def test_a_users_pipeline_works_on_the_users_own_watchlist_and_journal() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    members = harness.runtime.pipeline_for(MEMBER, ExecutionProvider.MOCK)

    await members.watch_manually(["2330"])

    assert [entry.stock_id for entry in (await members.load_watchlist()).watchlist] == ["2330"]
    assert (await harness.pipeline.load_watchlist()).watchlist == []
    assert harness.watchlist.rows == [] and harness.owners[MEMBER.user_id].watchlist_repository.rows != []


async def test_only_an_administrator_holds_the_real_broker_and_every_user_their_own_mock_account() -> None:
    harness = build_harness(sinopac=True)
    harness.users.add(MEMBER, MEMBER_PASSWORD)
    harness.real_broker.cash = 42_000

    with pytest.raises(RealBrokerRefused):
        harness.runtime.pipeline_for(MEMBER, ExecutionProvider.SHIOAJI)

    sinopac = await harness.pipeline_on(ExecutionProvider.SHIOAJI).load_account_history(None)
    mock = await harness.runtime.pipeline_for(MEMBER, ExecutionProvider.MOCK).load_account_history(None)
    assert (sinopac.account.cash, mock.account.cash) == (42_000, harness.owners[MEMBER.user_id].mock_broker.cash)
    assert (harness.runtime.brokers_for(ADMINISTRATOR), harness.runtime.brokers_for(MEMBER)) == (
        [ExecutionProvider.MOCK, ExecutionProvider.SHIOAJI],
        [ExecutionProvider.MOCK],
    )

    with pytest.raises(SignInRequired):
        await harness.runtime.signed_out.load_account_history(None)


async def test_no_pipeline_holds_sinopac_while_its_login_is_down_or_where_the_site_has_none() -> None:
    harness = build_harness(sinopac=True)
    harness.real_broker.current_link = BrokerLink(broker=ExecutionProvider.SHIOAJI, up=False, simulation=True)

    with pytest.raises(BrokerUnavailable):
        harness.pipeline_on(ExecutionProvider.SHIOAJI)

    with pytest.raises(BrokerUnavailable):
        build_harness().pipeline_on(ExecutionProvider.SHIOAJI)

    assert harness.runtime.brokers_for(ADMINISTRATOR) == [ExecutionProvider.MOCK]
