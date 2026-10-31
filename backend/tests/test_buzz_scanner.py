from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from trading_stack import run_status

from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import InformationSource, Workflow
from b_application.config.app_config import AppConfig
from b_application.config.collect_config import CollectRulesConfig
from b_application.config.sources_config import SourcesConfig
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from c_infrastructure.feed.ptt_provider import PttListing, PttParser
from c_infrastructure.market.twse_provider import TaiwanStockProvider

SOURCES = SourcesConfig()


class SilentLogger:
    def __getattr__(self, name: str):
        return lambda message: None


class FakeSocialMediaProvider:
    def __init__(self, articles: list[Article]) -> None:
        self._articles = articles

    async def fetch_social_articles(self, limit: int) -> list[Article]:
        return list(self._articles)

    def save_social_media_data(self, articles: list[Article]) -> None:
        return None


def make_post(stock_id: str, engagement: int = 0) -> Article:
    return Article(
        stock_id=stock_id,
        source=InformationSource.PTT_STOCK,
        title=f"[標的] {stock_id}",
        content="discussion",
        published_at=datetime(2026, 10, 30, tzinfo=UTC),
        fetched_at=datetime(2026, 10, 30, tzinfo=UTC),
        engagement=engagement,
    )


def make_config(min_mentions: int, min_engagement: int) -> AppConfig:
    return AppConfig(
        project_root=Path("."), collect_rules=CollectRulesConfig(buzz_min_mentions=min_mentions, buzz_min_engagement=min_engagement)
    )


async def make_stock_provider(monkeypatch: pytest.MonkeyPatch, stock_ids: list[str]) -> TaiwanStockProvider:
    provider = TaiwanStockProvider(exchange=SOURCES.exchange, logger=SilentLogger())

    async def fetch_from_api() -> tuple[list[Stock], dict[str, Ohlcv]]:
        return [Stock(stock_id=stock_id) for stock_id in stock_ids], {}

    monkeypatch.setattr(provider, "_fetch_from_api", fetch_from_api)
    return provider


async def scan(articles: list[Article], stock_provider: TaiwanStockProvider, config: AppConfig) -> PipelineStatus:
    scanner = BuzzScanner(
        social_media_provider=FakeSocialMediaProvider(articles), stock_provider=stock_provider, logger=SilentLogger(), config=config
    )
    status = run_status(Workflow.BUZZ_SCAN)
    await scanner.execute(status)
    return status


@pytest.mark.asyncio
async def test_buzz_articles_do_not_leak_into_later_workflows_in_the_same_session(monkeypatch: pytest.MonkeyPatch) -> None:
    stock_provider = await make_stock_provider(monkeypatch, ["2330"])
    config = make_config(min_mentions=1, min_engagement=1000)

    first_scan = await scan([make_post("2330")], stock_provider, config)
    second_scan = await scan([make_post("2330")], stock_provider, config)
    later_lookup = await stock_provider.get_by_id("2330")

    assert len(first_scan.buzz_stocks[0].articles) == 1
    assert len(second_scan.buzz_stocks[0].articles) == 1
    assert later_lookup is not None
    assert later_lookup.articles == []


@pytest.mark.asyncio
async def test_a_stock_qualifies_by_mention_count_or_by_engagement(monkeypatch: pytest.MonkeyPatch) -> None:
    stock_provider = await make_stock_provider(monkeypatch, ["1111", "2222", "3333"])
    config = make_config(min_mentions=20, min_engagement=100)
    many_mentions = [make_post("1111") for _ in range(20)]
    one_engaged_post = [make_post("2222", engagement=100)]
    below_both_thresholds = [make_post("3333", engagement=5) for _ in range(19)]

    status = await scan([*many_mentions, *one_engaged_post, *below_both_thresholds], stock_provider, config)

    assert [stock.stock_id for stock in status.buzz_stocks] == ["1111", "2222"]
    assert [len(stock.articles) for stock in status.buzz_stocks] == [20, 1]
    assert status.stats.buzz_scanned == 3
    assert status.stats.buzz_qualified == 2


@pytest.mark.asyncio
async def test_engagement_one_below_the_threshold_does_not_qualify(monkeypatch: pytest.MonkeyPatch) -> None:
    stock_provider = await make_stock_provider(monkeypatch, ["2222"])
    config = make_config(min_mentions=20, min_engagement=100)

    status = await scan([make_post("2222", engagement=60), make_post("2222", engagement=39)], stock_provider, config)

    assert status.buzz_stocks == []
    assert status.stats.buzz_scanned == 1
    assert status.stats.buzz_qualified == 0


def test_ptt_post_engagement_counts_every_push_boo_and_arrow() -> None:
    html = """
    <div id="main-content">
      <div class="article-metaline">作者 tester</div>
      股票代碼：2330
      台積電法說會後的看法，內文足夠長。
      <div class="push"><span class="push-tag">推 </span><span>u1</span></div>
      <div class="push"><span class="push-tag">推 </span><span>u2</span></div>
      <div class="push"><span class="push-tag">噓 </span><span>u3</span></div>
      <div class="push"><span class="push-tag">→ </span><span>u4</span></div>
    </div>
    """
    parser = PttParser(SOURCES.ptt, max_body_length=3000)
    listing = PttListing(title="[標的] 2330 台積電 多", url="https://www.ptt.cc/bbs/Stock/M.1.html", published_date=date(2026, 10, 30))

    article = parser.parse_article(html, listing, stock_universe={"2330"})

    assert article is not None
    assert article.stock_id == "2330"
    assert article.engagement == 4
