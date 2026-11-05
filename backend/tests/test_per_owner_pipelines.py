"""
Which ports dependencies.py hands each user's Pipeline: the signed-out one reads nobody's data, a user's own ports are
theirs, and only an administrator holds a real broker. test_ai_allowance.py covers the AI limit the wiring gives each.
"""

import pytest
from support.harness import ADMINISTRATOR, MEMBER, MEMBER_PASSWORD, build_harness, real_broker_config, rising_history

from a_domain.types.errors import SignInRequired
from d_presentation.dependencies import RealBrokerRefused

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
    members = harness.runtime.pipeline_for(MEMBER)

    await members.watch_manually(["2330"])

    assert [entry.stock_id for entry in (await members.load_watchlist()).watchlist] == ["2330"]
    assert (await harness.pipeline.load_watchlist()).watchlist == []
    assert harness.watchlist.rows == [] and harness.owners[MEMBER.user_id].watchlist_repository.rows != []


async def test_only_an_administrator_holds_the_real_broker() -> None:
    config = real_broker_config()
    harness = build_harness(config=config)

    with pytest.raises(RealBrokerRefused):
        harness.runtime.pipeline_for(MEMBER)

    status = await harness.runtime.pipeline_for(ADMINISTRATOR).load_account_history(None)
    assert status.account.cash == harness.broker.cash

    with pytest.raises(SignInRequired):
        await harness.runtime.signed_out.load_account_history(None)
