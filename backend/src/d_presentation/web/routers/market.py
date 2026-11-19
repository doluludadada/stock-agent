from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, status

from a_domain.rules.fundamentals.stock_analysis import StockAnalysis
from a_domain.rules.market.breadth import MarketBreadth
from a_domain.types.enums import Feature, MarketIndex
from b_application.config.sources_config import OpenDataAttribution
from d_presentation.web.schemas import (
    ArchiveStatusResponse,
    AudienceResponse,
    Confirmed,
    IndexHistoryResponse,
    ListedStockResponse,
    PageQuotesResponse,
    StockBriefResponse,
    StockCompanyResponse,
    StockFinancialsResponse,
    StockHistoryResponse,
    StockId,
    StockNewsItemResponse,
    StockNewsResponse,
    StockRankingResponse,
    StockTechnicalResponse,
)
from d_presentation.web.session import (
    NotFound,
    PrivateAccess,
    RuntimeDependency,
    RuntimeSwitchDependency,
    SignedOutPipeline,
    UserPipeline,
    shows,
)

router = APIRouter(prefix="/market", tags=["Market data"])

StockIdPath = Annotated[StockId, Path()]
BarCount = Annotated[int, Query(ge=20, le=500)]
QuotedStockIds = Annotated[list[StockId], Query(min_length=1)]
QuotedIndexes = Annotated[list[MarketIndex], Query(min_length=1)]

UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "The exchange listing could not be loaded."}
}
NOT_LISTED: dict[int | str, dict[str, Any]] = {status.HTTP_404_NOT_FOUND: {"description": "Not a listed stock."}}
BRIEF_REFUSED: dict[int | str, dict[str, Any]] = {
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "description": "brief_limit_reached: today's new briefs are spent. ai_allowance_spent: today's paid AI calls are spent."
    }
}
RANKING_UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": "ranking_unavailable: the site's daily history holds no decision session yet. invalid_request: a bad code."
    }
}


@router.get("/stocks", responses=UNAVAILABLE)
async def search_stocks(
    pipeline: SignedOutPipeline, query: Annotated[str, Query(min_length=1, max_length=40)]
) -> list[ListedStockResponse]:
    """Listed and OTC stocks whose code or name matches, best first, each with its latest official close. Public."""
    return [ListedStockResponse.model_validate(stock) for stock in await pipeline.search_stocks(query)]


@router.get("/most-traded", responses=UNAVAILABLE, dependencies=[shows(Feature.MARKET_OVERVIEW)])
async def get_most_traded(pipeline: SignedOutPipeline) -> list[ListedStockResponse]:
    """The latest session's most traded stocks in the TWSE and TPEX daily listings, with that session's bar. Public."""
    return [ListedStockResponse.model_validate(stock) for stock in await pipeline.load_most_traded()]


@router.get("/breadth", responses=UNAVAILABLE, dependencies=[shows(Feature.MARKET_OVERVIEW)])
async def get_market_breadth(pipeline: SignedOutPipeline) -> MarketBreadth:
    """
    The latest session's advancers, decliners and unchanged stocks in the TWSE and TPEX daily listings, each with the
    exchange's own change, and the same per industry with the average change in percent. Public.
    """
    return await pipeline.load_market_breadth()


@router.get("/indexes/{index}")
async def get_index_history(index: MarketIndex, pipeline: SignedOutPipeline, bars: BarCount = 250) -> IndexHistoryResponse:
    """
    One market index's completed daily bars, oldest first, from the daily history the stock pages share: the history
    cache of the exchanges' own reports on a personal site, else the open-data archive. Public. Like a stock's history, it
    fetches no realtime quote.
    """
    history = await pipeline.load_index_history(index, bars)

    return IndexHistoryResponse(index=index, bars=history)


@router.get(
    "/quotes",
    dependencies=[
        PrivateAccess,
        shows(Feature.HOLDINGS, Feature.MOCK_ACCOUNT, Feature.RANKING, Feature.STOCK_PAGES, Feature.WATCHLIST),
    ],
)
async def get_page_quotes(runtime: RuntimeDependency, pipeline: SignedOutPipeline, ids: QuotedStockIds) -> PageQuotesResponse:
    """
    The realtime quotes the ranking, the watchlist and a stock's page show beside their settled closes, and the ones
    My holdings and the mock account are valued at by their own endpoints. Every page and user read one board, which
    asks Shioaji once for all of them at most every market_data.page_quote_refresh_seconds while a session trades, and
    after the close until one request was answered; outside that it only answers what it holds of today. `refresh`
    says when a page asks again. Of a request that names more stocks than market_data.quote_batch_size, what the board
    reads at once, the first ones are read and the rest are answered null. A site without a Shioaji login now answers
    so and asks nothing. Private: a visitor never makes the site ask the broker. It reads quotes alone, on nobody's
    Pipeline: it holds no account and prices no order.
    """
    available = runtime.realtime_quotes
    answer = await pipeline.load_page_quotes(ids, []) if available else None
    quotes = answer.quotes if answer is not None else {}

    return PageQuotesResponse(
        realtime_quotes=available,
        refresh=answer.refresh if answer is not None else None,
        quotes={stock_id: quotes.get(stock_id) for stock_id in ids},
        indexes={},
    )


@router.get("/index-quotes", dependencies=[PrivateAccess, shows(Feature.MARKET_OVERVIEW)])
async def get_index_quotes(runtime: RuntimeDependency, pipeline: SignedOutPipeline, indexes: QuotedIndexes) -> PageQuotesResponse:
    """
    The realtime quote of each market index named, which the market overview shows in place of the settled close once
    a session opened: from the same board and by the same pace as /v1/market/quotes, in one Shioaji request of its own
    beside the stocks', so at most one per market_data.page_quote_refresh_seconds for every tab together. Before the
    session opens an index has no value of today and is answered null. A site without a Shioaji login now answers so
    and asks nothing. Private: a visitor never makes the site ask the broker. It reads quotes alone, on nobody's
    Pipeline.
    """
    available = runtime.realtime_quotes
    answer = await pipeline.load_page_quotes([], indexes) if available else None
    quotes = answer.indexes if answer is not None else {}

    return PageQuotesResponse(
        realtime_quotes=available,
        refresh=answer.refresh if answer is not None else None,
        quotes={},
        indexes={index: quotes.get(index) for index in indexes},
    )


@router.get("/archive-status")
async def get_archive_status(runtime: RuntimeDependency, pipeline: SignedOutPipeline) -> ArchiveStatusResponse:
    """
    How many sessions of TWSE and TPEX closes the server's open-data archive holds, and how many the built-in strategies
    need. A public site's runs read their daily history from it, so they find no candidate until it holds enough. Public.
    """
    return ArchiveStatusResponse(sessions=await pipeline.count_archived_sessions(), needed=runtime.config.technical.required_bars)


@router.get("/audience")
async def get_audience(runtime: RuntimeDependency) -> AudienceResponse:
    """
    Whom the site serves, personal or public, and what that allows, from the one table of each audience's capabilities.
    Realtime quotes also need this runtime's Shioaji login, which a personal site may lack. The web app shows only what
    the site can do by it; the server still refuses the rest. Public.
    """
    audience = runtime.config.audience

    return AudienceResponse(
        audience=audience,
        open_data_only=audience.open_data_only,
        realtime_quotes=audience.realtime_quotes and runtime.realtime_quotes,
        news_articles=audience.news_articles,
        mops=audience.mops,
        annual_reports=audience.annual_reports,
        order_pricing=audience.order_pricing,
    )


@router.get("/attribution")
async def get_attribution(runtime: RuntimeDependency) -> OpenDataAttribution:
    """
    The credit the Open Government Data License v1 requires wherever the site shows the TWSE and TPEX open data or what
    it computes from it: each providing agency with the datasets the site reads, the license's notice, and the
    license's name and address. Public.
    """
    return runtime.config.sources.attribution


@router.get("/stocks/{stock_id}", responses=NOT_LISTED)
async def get_stock_history(stock_id: StockIdPath, pipeline: SignedOutPipeline, bars: BarCount = 250) -> StockHistoryResponse:
    """
    One stock's completed daily bars, oldest first, from the history cache the workflows share. Public. It fetches
    no realtime quote: the latest bar is the last settled session's close.
    """
    result = await pipeline.load_stock_history(stock_id, bars)

    if not result.manual_stocks:
        raise NotFound(f"{stock_id} is not a listed stock, or the exchange listing is unavailable.")

    stock = result.manual_stocks[0]

    return StockHistoryResponse(
        stock=ListedStockResponse.model_validate(stock), bars=stock.ohlcv, notes=[*result.stats.errors, *result.stats.execution_log]
    )


@router.get("/stocks/{stock_id}/financials", dependencies=[shows(Feature.STOCK_PAGES)])
async def get_stock_financials(stock_id: StockIdPath, pipeline: SignedOutPipeline) -> StockFinancialsResponse:
    """
    One stock's financials from the server's open-data archive: each archived quarter's revenue, gross profit,
    operating income, net income and EPS of the year to the quarter's end, its total assets, liabilities and equity at
    the quarter's end and its book value per share, and each archived month's revenue with its changes. Amounts are in
    thousands of TWD, per-share figures in TWD and changes in percent; a figure the company's industry format does not
    report is null. Both lists are empty for a stock the archive holds nothing of. Public.
    """
    financials = await pipeline.load_financials(stock_id)

    return StockFinancialsResponse(stock_id=stock_id, quarters=financials.quarters, monthly_revenues=financials.monthly_revenues)


@router.get("/stocks/{stock_id}/analysis", dependencies=[shows(Feature.STOCK_PAGES)])
async def get_stock_analysis(stock_id: StockIdPath, pipeline: SignedOutPipeline) -> StockAnalysis:
    """
    One stock's financial analysis from the data the server holds, with no fetch and no AI call: each held month's
    revenue with its change from a year before and the monthly ranking's acceleration (the mean of the latest
    ranking.revenue_short_months months over that of the latest ranking.revenue_long_months), each held quarter's
    year-to-date EPS, its own EPS, its change from a year before, its margins and debt ratio, and the latest session's
    P/E, P/B and dividend yield against each ratio's median over the sessions held. `readings` says what the figures
    say by fixed rules, each a kind and a count the web app turns into a sentence. A figure whose history is too short
    is null, and its reading says how much is held instead. Changes, margins and the debt ratio are ratios; revenue is
    in thousands of TWD. A stock the server holds nothing of answers empty lists. Public.
    """
    return await pipeline.load_stock_analysis(stock_id)


@router.get("/stocks/{stock_id}/news", responses=NOT_LISTED | UNAVAILABLE, dependencies=[PrivateAccess, shows(Feature.STOCK_PAGES)])
async def get_stock_news(stock_id: StockIdPath, pipeline: SignedOutPipeline) -> StockNewsResponse:
    """
    What is said about one listed stock, newest first, from the site's article store, at most
    stock_page.article_store.shown: the material information its company announced and the TWSE news naming it, with
    their text; and on a site whose audience may read them (`news_articles` of /v1/market/audience) the news sites'
    articles and the stock board's posts, by title and address. A request first reads what there is to read now into
    the store: the open-data archive's items of the last analysis.material_information_days, and the sites' and the
    board's, which are fetched when a page asks and then held for stock_page.news_freshness_minutes, one fetch per
    stock at a time; a source that fails keeps what was held of it. So the list also holds what the sources no longer
    serve, for stock_page.article_store.retention_days. Every text is a third party's: show it as text, never as
    markup. Private: a visitor never makes the site ask a news site or the board.
    """
    articles = await pipeline.load_stock_news(stock_id)

    if articles is None:
        raise NotFound(f"{stock_id} is not a listed stock.")

    return StockNewsResponse(stock_id=stock_id, items=[StockNewsItemResponse.model_validate(article) for article in articles])


@router.get("/stocks/{stock_id}/company", responses=NOT_LISTED | UNAVAILABLE, dependencies=[shows(Feature.STOCK_PAGES)])
async def get_stock_company(stock_id: StockIdPath, pipeline: SignedOutPipeline) -> StockCompanyResponse:
    """
    What the site holds about one listed stock's company, with no fetch and no AI call: its `profile`, the names,
    founding and listing dates, paid-in capital, chairman and website of the exchanges' open data and, on a personal
    site, its main business as filed with MOPS with the page it is from; the `sources` a company card rests on, each
    with its address; and the company card, `today` if one was claimed today in Taipei and `previous` the newest
    written one of an earlier day. A card is written when a signed-in viewer asks for the stock's brief, or by the
    site for the monthly ranking's stocks, and again only when what it rests on changed. Every text is the AI's or a
    third party's: show it as text, never as markup. 404 for a code that is not listed. Public.
    """
    company = await pipeline.load_company(stock_id)

    if company is None:
        raise NotFound(f"{stock_id} is not a listed stock.")

    return StockCompanyResponse(
        stock_id=stock_id, profile=company.profile, sources=company.sources, today=company.today, previous=company.previous
    )


@router.get("/stocks/{stock_id}/brief", dependencies=[shows(Feature.STOCK_PAGES)])
async def get_stock_brief(stock_id: StockIdPath, pipeline: SignedOutPipeline) -> StockBriefResponse:
    """
    The AI brief the site holds of one stock, with no AI call: `today` is the brief of today in Taipei if a viewer
    asked for one (`status` writing, written or failed), `previous` the newest written brief of an earlier day, and
    `stocks_left` how many more stocks may get a new brief today. A written brief has the part `movement`, and
    `company` where it was written before the company card took that part over, each a list of sentences with the
    keys of the `sources` it rests on: the held figures and the
    announcements, news and posts the page shows, by kind, date, title and address. It names the model that wrote it,
    when, in which language, and the window of sessions with the close's change over it. Every text is the AI's or a
    third party's: show it as text, never as markup. It describes and gives no advice. Public.
    """
    briefs = await pipeline.load_stock_brief(stock_id)

    return StockBriefResponse(stock_id=stock_id, today=briefs.today, previous=briefs.previous, stocks_left=briefs.stocks_left)


@router.post(
    "/stocks/{stock_id}/brief",
    responses=NOT_LISTED | UNAVAILABLE | BRIEF_REFUSED,
    dependencies=[PrivateAccess, shows(Feature.STOCK_PAGES)],
)
async def write_stock_brief(
    stock_id: StockIdPath, body: Confirmed, pipeline: UserPipeline, switch: RuntimeSwitchDependency
) -> StockBriefResponse:
    """
    Asks for the stock's AI brief of today in Taipei, then answers what GET answers. The site writes one brief per
    stock and day for every viewer: the first request claims it and makes one paid AI call on the user's allowance,
    waiting for the reply; a request made meanwhile, or after it is written, calls nothing and answers what is held. A
    failed brief may be asked again. Before the brief, a personal site reads the company's main business and annual
    report when they are due, which can take a minute the first time, and the company's card is written when it has
    none or what it rests on changed, a second paid call. GET /stocks/{stock_id}/company answers each of them as it is
    held, so a page that asks it meanwhile can say how far the request has come. One request at a time works for a
    stock: a second one waits for the first and then answers what is held, with no second fetch and no second call. 429
    brief_limit_reached when the stock has none today and stock_page.brief.daily_stocks stocks have one; 429
    ai_allowance_spent when the user's or the site's paid AI calls of the day are spent. It reads held data only, records no run and
    never orders. Private: a visitor never causes a call.
    """
    async with switch.brief_turns.of(stock_id):
        briefs = await pipeline.write_stock_brief(stock_id)

    if briefs is None:
        raise NotFound(f"{stock_id} is not a listed stock.")

    return StockBriefResponse(stock_id=stock_id, today=briefs.today, previous=briefs.previous, stocks_left=briefs.stocks_left)


@router.get(
    "/stocks/{stock_id}/ranking", responses=RANKING_UNAVAILABLE, dependencies=[shows(Feature.STOCK_PAGES), shows(Feature.RANKING)]
)
async def get_stock_ranking(stock_id: StockIdPath, pipeline: SignedOutPipeline) -> StockRankingResponse:
    """
    One stock's score: where it stands in the monthly ranking at the latest decision session the site's daily history
    holds, from the same ranking /v1/rankings/latest answers, by the active formula (`formula`), with no cut at its
    `top`. `score` is its place among the scored stocks as a percentile, 100 for the best combined rank; `stock` holds
    the formula's factors in order, each with its rank from 0 to 1; `in_top` says whether the ranking holds it. While
    the formula holds cash (`holds_cash`) the score is measured all the same and no stock is in the top. A stock the
    ranking leaves out has no score and `exclusion` says why: no held history, an ETF, no trade that session, a close
    under the formula's min_close, too little traded value, a month of revenue a factor reads not held, or a price
    history shorter than a factor reads. The score ranks measured factors; it is no forecast. One stock's standing,
    not the ranking's list: it needs no sign-in, and a viewer sees it only where the site shows them both the stock
    pages and the ranking (403 feature_hidden otherwise).
    """
    return StockRankingResponse.model_validate(await pipeline.load_ranking_standing(stock_id))


@router.get("/stocks/{stock_id}/technical", responses=NOT_LISTED, dependencies=[PrivateAccess, shows(Feature.STOCK_PAGES)])
async def get_stock_technical(stock_id: StockIdPath, pipeline: UserPipeline) -> StockTechnicalResponse:
    """
    The owner's active strategy applied to the stock exactly as a run applies it, with each indicator's value at every
    bar it read. Private: it reads the owner's saved strategy.
    """
    evaluation = await pipeline.evaluate_stock(stock_id)
    result = evaluation.status

    if not result.manual_stocks:
        raise NotFound(f"{stock_id} is not a listed stock, or the exchange listing is unavailable.")

    stock = result.manual_stocks[0]

    return StockTechnicalResponse(
        stock_id=stock.stock_id,
        strategy=evaluation.strategy,
        required_bars=evaluation.strategy.required_bars,
        bar_times=[bar.ts for bar in stock.ohlcv],
        latest_price=stock.current_price,
        report=stock.technical_report,
        readings=result.indicator_readings,
        notes=[*result.stats.errors, *result.stats.execution_log],
    )
