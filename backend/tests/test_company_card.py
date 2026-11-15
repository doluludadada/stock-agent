"""
The company card: the AI's description of a company from its profile and its annual report's sections, written once
with the brief's machinery, kept, and written again only when what it rests on changed.
"""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest
from support.harness import MARKET_OPEN, MEMBER, MEMBER_PASSWORD, CliHarness
from support.web import serve
from test_ranking_rule import revenue
from test_stock_brief import CONFIRM, INSTRUCTIONS, BriefAi, brief_config, brief_harness, writing

from a_domain.model.market.article import Article
from a_domain.model.market.company_profile import CompanyProfile
from a_domain.model.market.stock import Stock
from a_domain.ports.market.annual_report_provider import AnnualReport
from a_domain.ports.market.company_basics_provider import CompanyBasics
from a_domain.rules.ai.stock_brief import BriefContext
from a_domain.rules.fundamentals.stock_analysis import EarningsTrendRule, StockAnalysisRule
from a_domain.types.enums import Audience, BriefKind, BriefSourceKind, BriefStatus, ContentType, InformationSource, MarketType
from a_domain.types.errors import AiAllowanceSpentError
from b_application.config.app_config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.stock_brief_dto import CompanyCardDTO, StockBriefDTO
from c_infrastructure.database.repositories.stock_brief_repository import SqlStockBriefRepository

pytestmark = pytest.mark.asyncio

TODAY = MARKET_OPEN.date()
CARD_PROMPT: str = INSTRUCTIONS["company_card_prompt"]
MOPS_PAGE = "https://mops.example/2330"
INDEX_PAGE = "https://doc.example/2330/114"
CARD_REPLY = json.dumps({"company": [{"text": "It makes wafers for chip designers.", "sources": ["S1", "S2"]}]})
BRIEF_REPLY = json.dumps({"movement": [{"text": "The close rose over the window.", "sources": ["S2"]}]})
PROFILE = CompanyProfile(
    stock_id="2330",
    market=MarketType.TWSE,
    full_name="Taiwan Semiconductor Manufacturing",
    short_name="TSMC",
    industry_code="24",
    founded_on=date(1987, 2, 21),
    listed_on=date(1994, 9, 5),
    paid_in_capital=259_303_804_580,
    issued_shares=25_930_380_458,
    chairman="C.C. Wei",
    website="https://www.tsmc.com",
    reported_on=date(2026, 10, 16),
    fetched_at=MARKET_OPEN - timedelta(days=1),
    main_business="Wafer manufacturing for customers' designs",
    main_business_url=MOPS_PAGE,
    main_business_fetched_at=MARKET_OPEN - timedelta(days=3),
)


def section(name: str, text: str, fiscal_year: int = 2025) -> Article:
    return Article(
        stock_id="2330",
        source=InformationSource.ANNUAL_REPORT,
        content_type=ContentType.REPORT,
        title=f"Annual report {fiscal_year}: {name}",
        content=text,
        url=f"{INDEX_PAGE}#{name}",
        published_at=MARKET_OPEN - timedelta(days=150),
        fetched_at=MARKET_OPEN - timedelta(days=3),
        fact_date=date(fiscal_year, 12, 31),
    )


MIX = section("product_mix", "Wafers 87%, other 13% of 2025 revenue")


def card_config(**card: object) -> AppConfig:
    config = brief_config()
    stock_page = config.stock_page.model_copy(update={"card": config.stock_page.card.model_copy(update=card)})
    return config.model_copy(
        update={"stock_page": stock_page, "prompts": config.prompts.model_copy(update={"company_card": CARD_PROMPT})}
    )


def card_context(
    config: AppConfig,
    profile: CompanyProfile | None = PROFILE,
    sections: tuple[Article, ...] = (MIX,),
    day: date = TODAY,
    months: int = 0,
) -> BriefContext:
    analysis_rule = StockAnalysisRule(
        revenue_rule=config.ranking.revenue_trend_rule(),
        earnings_rule=EarningsTrendRule(),
        valuation_rule=config.stock_page.valuation_rule(),
    )
    held = [replace(revenue("2330", 2025, month, 1000.0), served_date=date(2026, 1, 10)) for month in range(1, months + 1)]
    analysis = analysis_rule.apply("2330", [], held, [], [])
    stock = Stock(stock_id="2330", name="TSMC")
    return config.company_card_context_rule().apply(stock, profile, list(sections), analysis.revenue, day)


class CardAi(BriefAi):
    """The AI behind both texts: it answers a card's prompt with a card and a brief's with a brief."""

    async def __call__(self, messages):
        self.reply = CARD_REPLY if "card about one Taiwan-listed company" in messages[-1].content else BRIEF_REPLY
        return await super().__call__(messages)


def card_harness(config: AppConfig | None = None) -> tuple[CliHarness, CardAi]:
    harness, _ = brief_harness(config or card_config())
    ai = CardAi()
    harness.ai.generate_reply = ai  # pyright: ignore[reportAttributeAccessIssue]
    return harness, ai


async def ask(harness: CliHarness, stock_id: str = "2330"):
    async with serve(harness, user=(MEMBER.username, MEMBER_PASSWORD)) as member:
        return await member.post(f"/v1/market/stocks/{stock_id}/brief", json=CONFIRM)


async def company(harness: CliHarness, stock_id: str = "2330"):
    async with serve(harness, authorized=False) as visitor:
        return await visitor.get(f"/v1/market/stocks/{stock_id}/company")


# ------------------------------------------------- what a card rests on ------------------------------------------------- #


async def test_a_card_rests_on_the_open_data_the_filed_business_the_last_full_year_and_the_newest_report() -> None:
    config = card_config()
    older = section("product_mix", "Wafers 85% of 2024 revenue", fiscal_year=2024)

    context = card_context(config, sections=(older, MIX, section("employees", "76,000 employees")), months=12)

    assert [(fact.source.key, fact.source.kind, fact.source.dated, fact.source.url) for fact in context.facts] == [
        ("S1", BriefSourceKind.COMPANY, date(2026, 10, 16), None),
        ("S2", BriefSourceKind.PROFILE, (MARKET_OPEN - timedelta(days=3)).date(), MOPS_PAGE),
        ("S3", BriefSourceKind.REVENUE, date(2026, 1, 10), None),
        ("S4", BriefSourceKind.ANNUAL_REPORT, (MARKET_OPEN - timedelta(days=150)).date(), f"{INDEX_PAGE}#employees"),
        ("S5", BriefSourceKind.ANNUAL_REPORT, (MARKET_OPEN - timedelta(days=150)).date(), f"{INDEX_PAGE}#product_mix"),
    ]
    listing, business, year, _, mix = [fact.text for fact in context.facts]
    assert listing == (
        "2330 TSMC, listed on twse; industry in the exchange's listing: 半導體業; full name Taiwan Semiconductor Manufacturing; "
        "founded 1987-02-21; listed 1994-09-05; paid-in capital 259,303,804,580 TWD; 25,930,380,458 shares issued; chairman C.C. Wei"
    )
    assert business == "main business as the company filed it with MOPS: Wafer manufacturing for customers' designs"
    assert year == "revenue of 2025, twelve months: 12,000 thousand TWD"
    assert mix == "Annual report 2025: product_mix | Wafers 87%, other 13% of 2025 revenue"
    assert context.facts[4].source.title == "Annual report 2025: product_mix"
    assert (context.window_first, context.window_last, context.price_change) == (None, None, None)


async def test_a_company_with_nothing_held_still_has_its_listing_and_an_incomplete_year_gives_no_revenue() -> None:
    context = card_context(card_config(), profile=None, sections=(), months=11)

    assert [(fact.source.kind, fact.source.dated) for fact in context.facts] == [(BriefSourceKind.COMPANY, TODAY)]
    assert context.facts[0].text == "2330 TSMC, listed on twse; industry in the exchange's listing: not held"


async def test_a_section_is_cut_at_the_cards_length() -> None:
    context = card_context(card_config(section_length=200), sections=(section("business_scope", "晶圓" * 500),))

    assert context.facts[-1].text == "Annual report 2025: business_scope | " + "晶圓" * 100


async def test_the_fingerprint_changes_with_what_the_card_rests_on_and_with_nothing_else() -> None:
    config = card_config()
    base = card_context(config).fingerprint
    later = replace(PROFILE, reported_on=date(2026, 11, 20), fetched_at=MARKET_OPEN + timedelta(days=30))
    asked_again = replace(PROFILE, main_business_fetched_at=MARKET_OPEN + timedelta(days=90))
    other_prompt = config.model_copy(update={"prompts": config.prompts.model_copy(update={"company_card": CARD_PROMPT + " "})})

    assert base is not None and len(base) == 64
    assert card_context(config, day=TODAY + timedelta(days=40)).fingerprint == base
    assert card_context(config, profile=later).fingerprint == base
    assert card_context(config, profile=asked_again).fingerprint == base
    assert card_context(config, profile=replace(PROFILE, main_business="Wafers and packaging")).fingerprint != base
    assert card_context(config, profile=replace(PROFILE, chairman="Mark Liu")).fingerprint != base
    assert card_context(config, sections=(replace(MIX, content="Wafers 88%"),)).fingerprint != base
    assert card_context(config, sections=()).fingerprint != base
    assert card_context(other_prompt).fingerprint != base
    assert card_context(config, months=12).fingerprint != base


# ---------------------------------------------------- the reply ---------------------------------------------------- #


async def test_a_card_keeps_cited_company_sentences_and_nothing_else() -> None:
    config = card_config(sentences=2)
    rule = config.stock_page.card.reply_rule(config.prompts.advice_phrases(), config.stock_page.brief.link_pattern)
    reply = json.dumps(
        {
            "company": [
                {"text": "It makes wafers; see https://invented.example/x for more.", "sources": ["S2", "S9"]},
                {"text": "建議持有，目標價 2000。", "sources": ["S1"]},
                {"text": "It was founded in 1987.", "sources": []},
                {"text": "Wafers were 87% of 2025 revenue.", "sources": ["S3"]},
                {"text": "A third kept sentence would pass the limit.", "sources": ["S1"]},
            ],
            "movement": [{"text": "It rose.", "sources": ["S1"]}],
        }
    )

    kept = rule.apply(reply, card_context(config))

    assert kept is not None and kept.movement == []
    assert [(sentence.text, sentence.sources) for sentence in kept.company] == [
        ("It makes wafers; see for more.", ["S2"]),
        ("Wafers were 87% of 2025 revenue.", ["S3"]),
    ]
    assert [source.key for source in kept.sources] == ["S2", "S3"]


@pytest.mark.parametrize(
    "reply",
    [BRIEF_REPLY, "I'm sorry, I cannot help with that.", json.dumps({"company": [{"text": "It makes wafers.", "sources": ["S9"]}]})],
)
async def test_a_reply_without_a_cited_company_sentence_is_no_card(reply: str) -> None:
    config = card_config()
    rule = config.stock_page.card.reply_rule(config.prompts.advice_phrases(), config.stock_page.brief.link_pattern)

    assert rule.apply(reply, card_context(config)) is None


async def test_the_daily_brief_keeps_a_company_part_an_older_prompt_asks_for() -> None:
    config = card_config()
    both = json.dumps(
        {"company": [{"text": "A chip maker.", "sources": ["S1"]}], "movement": [{"text": "It rose.", "sources": ["S1"]}]}
    )

    kept = config.stock_page.brief.reply_rule(config.prompts.advice_phrases()).apply(both, card_context(config))
    movement_alone = config.stock_page.brief.reply_rule(config.prompts.advice_phrases()).apply(
        BRIEF_REPLY.replace("S2", "S1"), card_context(config)
    )

    assert kept is not None and [sentence.text for sentence in kept.company] == ["A chip maker."]
    assert movement_alone is not None and movement_alone.company == [] and len(movement_alone.movement) == 1


async def test_the_two_kinds_differ_in_when_they_are_written() -> None:
    assert (BriefKind.MOVEMENT.daily, BriefKind.COMPANY.daily) == (True, False)
    assert {kind.value for kind in BriefKind} == {"movement", "company", "world"}


# ---------------------------------------------------- the tables ---------------------------------------------------- #


async def test_cards_and_briefs_are_kept_apart_and_a_card_keeps_its_fingerprint(database: DatabaseConnector) -> None:
    briefs, cards = SqlStockBriefRepository(database, StockBriefDTO), SqlStockBriefRepository(database, CompanyCardDTO)
    card = replace(writing("2330"), fingerprint="a" * 64)

    assert await cards.claim(card, 5, MARKET_OPEN - timedelta(minutes=5))
    assert not await cards.claim(card, 5, MARKET_OPEN - timedelta(minutes=5))
    assert await briefs.claim(writing("2330"), 5, MARKET_OPEN - timedelta(minutes=5))

    held = await cards.find("2330", TODAY)
    assert held is not None and (held.fingerprint, held.status) == ("a" * 64, BriefStatus.WRITING)
    assert (await briefs.find("2330", TODAY)).fingerprint is None  # type: ignore[union-attr]
    assert (await cards.claimed_stocks(TODAY), await briefs.claimed_stocks(TODAY)) == (1, 1)


# --------------------------------------------------- the Web API --------------------------------------------------- #


async def held_company(harness: CliHarness) -> None:
    await harness.profiles.save(PROFILE)
    await harness.articles.save([MIX])


async def test_asking_for_a_brief_writes_the_card_first_and_the_brief_reads_the_card() -> None:
    harness, ai = card_harness()
    await held_company(harness)

    written = await ask(harness)
    seen = (await company(harness)).json()

    assert written.status_code == 200 and len(ai.prompts) == 2
    card_prompt, brief_prompt = ai.prompts
    assert "[S2] (profile, 2026-10-16) main business as the company filed it with MOPS: Wafer manufacturing" in card_prompt
    assert "[S3] (annual report, 2026-05-22) Annual report 2025: product_mix | Wafers 87%" in card_prompt
    assert "[S1] (company, 2026-10-19) 2330 Stock 2330: It makes wafers for chip designers." in brief_prompt
    assert "listed on twse" not in brief_prompt.split("Facts:")[1]
    card = seen["today"]
    assert (card["status"], card["model"], card["language"], card["day"]) == ("written", "claude-haiku-5-5", "zh-TW", "2026-10-19")
    assert card["company"] == [{"text": "It makes wafers for chip designers.", "sources": ["S1", "S2"], "stocks": []}]
    assert (card["movement"], seen["previous"]) == ([], None)
    assert [(source["key"], source["kind"], source["url"]) for source in card["sources"]] == [
        ("S1", "company", None),
        ("S2", "profile", MOPS_PAGE),
    ]
    assert written.json()["today"]["company"] == [] and len(written.json()["today"]["movement"]) == 1


async def test_a_card_is_written_once_and_again_only_when_what_it_rests_on_changed() -> None:
    harness, ai = card_harness()
    await held_company(harness)
    await ask(harness)

    harness.clock.current_time = MARKET_OPEN + timedelta(days=1)
    await ask(harness)
    next_day = (await company(harness)).json()
    assert len(ai.prompts) == 3 and "card about one" not in ai.prompts[2]
    assert (next_day["today"], next_day["previous"]["day"]) == (None, "2026-10-19")
    assert "It makes wafers for chip designers." in ai.prompts[2]

    await harness.profiles.save(replace(PROFILE, main_business="Wafers and advanced packaging"))
    harness.clock.current_time = MARKET_OPEN + timedelta(days=2)
    await ask(harness)
    rewritten = (await company(harness)).json()
    assert len(ai.prompts) == 5 and "Wafers and advanced packaging" in ai.prompts[3]
    assert (rewritten["today"]["day"], rewritten["previous"]["day"]) == ("2026-10-21", "2026-10-19")


async def test_a_visitor_reads_the_profile_the_sources_and_the_card_and_causes_no_fetch_and_no_call() -> None:
    harness, ai = card_harness()
    await held_company(harness)

    before = (await company(harness)).json()
    await ask(harness)
    asked_by_member = (list(harness.company_basics.asked), list(harness.annual_reports.asked))
    after = (await company(harness)).json()

    assert (before["today"], before["previous"]) == (None, None)
    assert (before["profile"]["chairman"], before["profile"]["website"], before["profile"]["founded_on"]) == (
        "C.C. Wei",
        "https://www.tsmc.com",
        "1987-02-21",
    )
    assert before["profile"]["main_business"] == "Wafer manufacturing for customers' designs"
    assert [(source["kind"], source["url"], source["title"]) for source in before["sources"]] == [
        ("company", None, None),
        ("profile", MOPS_PAGE, None),
        ("annual_report", f"{INDEX_PAGE}#product_mix", "Annual report 2025: product_mix"),
    ]
    assert after["today"]["status"] == "written" and len(ai.prompts) == 2
    assert (list(harness.company_basics.asked), list(harness.annual_reports.asked)) == asked_by_member


async def test_a_members_request_reads_mops_and_the_annual_report_when_they_are_missing_and_only_once() -> None:
    harness, ai = card_harness()
    harness.company_basics.served["2330"] = CompanyBasics(main_business="Wafer manufacturing", english_name="TSMC", url=MOPS_PAGE)
    harness.annual_reports.listed[("2330", 2024)] = AnnualReport(fiscal_year=2024, file="2024_2330.pdf", sections=[MIX])

    await ask(harness)
    await ask(harness)

    assert harness.company_basics.asked == ["2330"]
    assert harness.annual_reports.asked == [("2330", 2025), ("2330", 2024)]
    assert "main business as the company filed it with MOPS: Wafer manufacturing" in ai.prompts[0]
    assert "product_mix | Wafers 87%" in ai.prompts[0] and len(ai.prompts) == 2
    assert (await company(harness)).json()["profile"]["annual_report_file"] == "2024_2330.pdf"


async def test_a_public_site_writes_the_card_from_open_data_and_reads_neither_source() -> None:
    config = card_config()
    harness, ai = card_harness(config.model_copy(update={"audience": Audience.PUBLIC}))
    await harness.profiles.save_listings([replace(PROFILE, main_business=None, main_business_url=None, main_business_fetched_at=None)])

    written = await ask(harness)

    assert written.status_code == 200 and len(ai.prompts) == 2
    assert (harness.company_basics.asked, harness.annual_reports.asked) == ([], [])
    assert "(profile," not in ai.prompts[0] and "(annual report," not in ai.prompts[0]
    assert "founded 1987-02-21" in ai.prompts[0]


async def test_without_the_cards_prompt_no_card_is_written_and_the_brief_describes_the_listing() -> None:
    harness, ai = card_harness(brief_config())
    await held_company(harness)

    written = await ask(harness)
    seen = (await company(harness)).json()

    assert written.status_code == 200 and len(ai.prompts) == 1
    assert "[S1] (company, 2026-10-19) 2330 Stock 2330, listed on twse" in ai.prompts[0]
    assert (seen["today"], seen["previous"], seen["profile"]["chairman"]) == (None, None, "C.C. Wei")
    assert harness.cards.rows == {}


async def test_a_card_that_fails_is_asked_again_and_the_brief_is_still_written() -> None:
    harness, ai = card_harness()
    await held_company(harness)
    answer = ai.__call__

    async def refuse_the_card(messages):
        if "card about one" in messages[-1].content:
            ai.prompts.append(messages[-1].content)
            raise RuntimeError("vendor down")
        return await answer(messages)

    harness.ai.generate_reply = refuse_the_card  # pyright: ignore[reportAttributeAccessIssue]
    first = await ask(harness)
    failed = (await company(harness)).json()

    harness.ai.generate_reply = ai  # pyright: ignore[reportAttributeAccessIssue]
    harness.clock.current_time = MARKET_OPEN + timedelta(days=1)
    await ask(harness)
    retried = (await company(harness)).json()

    assert first.status_code == 200 and first.json()["today"]["status"] == "written"
    assert (failed["today"]["status"], failed["previous"]) == ("failed", None)
    assert "listed on twse" in ai.prompts[1]
    assert retried["today"]["status"] == "written" and len(ai.prompts) == 4


async def test_a_spent_allowance_at_the_card_refuses_the_request_and_keeps_no_claim() -> None:
    harness, ai = card_harness()
    await held_company(harness)
    ai.failure = AiAllowanceSpentError("Today's paid AI calls are spent.")

    refused = await ask(harness)

    assert (refused.status_code, refused.json()["code"]) == (429, "ai_allowance_spent")
    assert harness.cards.rows == {} and harness.briefs.rows == {}


async def test_a_code_that_is_not_listed_has_no_company() -> None:
    harness, _ = card_harness()

    assert (await company(harness, "9999")).status_code == 404


async def test_the_shipped_prompts_name_what_each_text_is_written_from() -> None:
    assert "{facts}" in CARD_PROMPT and '"company"' in CARD_PROMPT and '"movement"' not in CARD_PROMPT
    assert '"movement"' in INSTRUCTIONS["stock_brief_prompt"] and '"company"' not in INSTRUCTIONS["stock_brief_prompt"]
    assert datetime.now().year >= 2026
