from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, time, timedelta

from pydantic import PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.model.market.article import Article
from a_domain.model.market.world_indicator import IndicatorReading
from a_domain.rules.ai.stock_brief import BriefContext, BriefFact, article_fact, held_fact, keyed_facts
from a_domain.types.enums import BriefSourceKind, BriefStatus, MarketScope


@dataclass(frozen=True, kw_only=True)
class WorldBriefDueRule:
    """
    Whether the day's world brief is to be asked for now. Never while the site writes none (`on`), and not before
    `write_at` of the Taipei day. From then on: when the day has no brief; when its brief failed and was asked for
    longer than `retry` ago, so a failure that repeats spends few AI calls; and when it is still being written
    `claim_time` after its claim, which a stopped server left behind. A written brief is the day's: nothing follows.
    """

    on: bool
    write_at: time
    retry: timedelta
    claim_time: timedelta

    def apply(self, held: StockBrief | None, now: datetime) -> bool:
        if not self.on or now.time() < self.write_at:
            return False

        if held is None:
            return True

        match held.status:
            case BriefStatus.WRITTEN:
                return False
            case BriefStatus.WRITING:
                return held.abandoned(now - self.claim_time)
            case BriefStatus.FAILED:
                return held.claimed_at < now - self.retry


def indicator_line(reading: IndicatorReading) -> str:
    """One held reading as the prompt says it: the level on its day, and its move from the reading before."""
    percent = reading.indicator.in_percent
    level = f"{reading.value:.2f}%" if percent else f"{reading.value:,.4f}"
    said = f"{reading.indicator.label} {level} on {reading.day.isoformat()}"

    if reading.change is None or reading.previous is None or reading.previous_day is None:
        return f"{said}; no earlier reading held"

    before = f"{reading.previous:.2f}%" if percent else f"{reading.previous:,.4f}"
    move = f"{reading.change:+.2f} percentage points" if percent else f"{reading.change:+.2%}"
    return f"{said}: {move} from {before} on {reading.previous_day.isoformat()}"


def named_stocks(text: str, listed: Mapping[str, str], name_length: PositiveInt) -> frozenset[str]:
    """
    The listed stocks a text names itself: those whose id stands in it as a word of its own, and those whose name,
    of `name_length` characters or more, it holds. A name that is part of a longer name the text holds too is not named:
    Nanya Technology's name holds Nan Ya Plastics' and names only itself. A name can still be part of another word, as
    Nan Ya's is of the word for Southeast Asia, so this only bounds what a sentence may link: the AI names the stock,
    and it is linked when it is among these (BriefReplyRule).
    """
    words = set("".join(character if character.isascii() and character.isalnum() else " " for character in text).split())
    held = {stock_id: name for stock_id, name in listed.items() if len(name) >= name_length and name in text}
    whole = {stock_id for stock_id, name in held.items() if not any(name != longer and name in longer for longer in held.values())}
    return frozenset(whole | {stock_id for stock_id in listed if stock_id in words})


@dataclass(frozen=True, kw_only=True)
class WorldBriefContextRule:
    """
    What the day's world brief may rest on, chosen from held data alone and bounded in size. First each held
    indicator's newest reading with its move from the reading before, when it is of the last `indicator_days` days.
    Then the world news published in the `window_hours` hours up to `now`, newest first, at most `articles`: of
    `retrieved`, what the brief's search found among the kept world news by meaning, or, while the search found
    nothing, of `articles`, the newest kept. An item is its publisher, its title and the feed's own summary, cut at
    `article_text_length`; what says the same in the same words is given once. Each item also carries the listed stocks
    its own text names (`listed`: id to name; a name shorter than `stock_name_length` names no stock), which alone a
    sentence citing it may link. Each fact gets a key the AI cites, in this order.
    """

    window_hours: PositiveInt
    articles: PositiveInt
    article_text_length: PositiveInt
    indicator_days: PositiveInt
    stock_name_length: PositiveInt

    def apply(
        self,
        readings: Sequence[IndicatorReading],
        articles: Sequence[Article],
        retrieved: Sequence[Article],
        listed: Mapping[str, str],
        now: datetime,
    ) -> BriefContext:
        since = now - timedelta(hours=self.window_hours)
        fresh = [reading for reading in readings if reading.day >= now.date() - timedelta(days=self.indicator_days)]
        recent = [article for article in retrieved or articles if since <= article.published_at <= now]
        newest_first = sorted(recent, key=lambda article: article.published_at, reverse=True)
        indicators = [held_fact(BriefSourceKind.INDICATOR, reading.day, indicator_line(reading)) for reading in fresh]
        found = {fact.text: fact for fact in indicators}

        for article in newest_first[: self.articles]:
            fact = article_fact(article, self.article_text_length)
            said = f"{article.source.label}: {fact.text}"
            source = replace(fact.source, origin=article.source)
            found.setdefault(said, BriefFact(source=source, text=said, stocks=named_stocks(said, listed, self.stock_name_length)))

        return BriefContext(
            stock_id=MarketScope.WORLD.value,
            stock_name="",
            window_first=since.date(),
            window_last=now.date(),
            price_change=None,
            facts=keyed_facts(found.values()),
        )
