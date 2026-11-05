from typing import Annotated

from fastapi import APIRouter, Query, status

from a_domain.model.valuation.scan import MarketValuation, ScanCriteria
from a_domain.types.enums import ScanStep
from d_presentation.web.schemas import (
    ExplanationRequest,
    MarketValuationResponse,
    StockId,
    ValuationExplanationResponse,
    ValuationReportResponse,
    ValuationReportsResponse,
    ValuationScanResponse,
)
from d_presentation.web.session import MarketValuationDependency, NotFound, PrivateAccess, UserPipeline

router = APIRouter(prefix="/valuation", tags=["Valuation"], dependencies=[PrivateAccess])
"""
The valuation menus 5 and 6 over HTTP. Every endpoint is read-only: it records no run, writes no watchlist entry and
never reaches order execution. Only POST /explanation calls the AI, once per request.
"""

TargetPe = Annotated[float, Query(gt=0, le=1000, allow_inf_nan=False)]


def market_response(market: MarketValuation) -> MarketValuationResponse:
    return MarketValuationResponse(
        last_closed_session=market.last_closed_session,
        valued_stocks=len(market.valuations),
        median_pe=market.median_pe(),
        source_warnings=list(market.source_warnings),
    )


@router.get("/market")
async def get_market_valuation(cache: MarketValuationDependency) -> MarketValuationResponse:
    """The market reference: last closed session, the median P/E and the sources' warnings. The first load reads MOPS."""
    return market_response(await cache.get())


@router.get("/stocks")
async def value_stocks(
    pipeline: UserPipeline,
    cache: MarketValuationDependency,
    stock_ids: Annotated[list[StockId], Query(min_length=1, max_length=20)],
    target_pe: TargetPe | None = None,
) -> ValuationReportsResponse:
    """Menu 5: the stocks' valuation facts, and their three scenarios at the target P/E. An unknown id is left out."""
    market = await cache.get()
    valuations = [valuation for stock_id in dict.fromkeys(stock_ids) if (valuation := market.find(stock_id)) is not None]
    reports = pipeline.appraise_valuations(valuations, target_pe)

    return ValuationReportsResponse(reports=[ValuationReportResponse.model_validate(report) for report in reports])


@router.get("/scan")
async def scan_undervalued(
    pipeline: UserPipeline,
    cache: MarketValuationDependency,
    target_pe: TargetPe,
    min_undervaluation: Annotated[float, Query(ge=0, le=10, allow_inf_nan=False)],
    technical: bool = False,
) -> ValuationScanResponse:
    """
    Menu 6: every stock valued at the target P/E, kept when at least `min_undervaluation` (a ratio) below its base
    fair price. With `technical`, the survivors then go through the owner's active strategy, which loads their daily
    history. No AI call.
    """
    market = await cache.get()
    scan = pipeline.screen_valuation(market, ScanCriteria(target_pe=target_pe, min_undervaluation=min_undervaluation))

    if technical:
        scan = await pipeline.confirm_valuation_technical(scan)

    return ValuationScanResponse.model_validate(
        {
            "market": market_response(market),
            "criteria": scan.criteria,
            "technical_strategy_id": scan.technical_strategy_id,
            "survivors": [ValuationReportResponse.model_validate(report) for report in scan.survivors],
            "technical_failures": {stock_id: elimination.detail for stock_id, elimination in scan.technical_eliminations.items()},
            "eliminated": {step: dict(scan.elimination_counts(step)) for step in ScanStep},
            "explanation_candidates": [report.stock.stock_id for report in scan.explanation_candidates],
        }
    )


@router.post("/explanation", responses={status.HTTP_404_NOT_FOUND: {"description": "Not a valued stock."}})
async def explain_valuation(
    body: ExplanationRequest, pipeline: UserPipeline, cache: MarketValuationDependency
) -> ValuationExplanationResponse:
    """One paid AI call: the AI explains the domain's numbers for one stock with its news. It adds no number."""
    market = await cache.get()
    valuation = market.find(body.stock_id)

    if valuation is None:
        raise NotFound(f"No valuation for {body.stock_id}.")

    [report] = pipeline.appraise_valuations([valuation], body.target_pe)
    sections = await pipeline.explain_valuation(report)

    return ValuationExplanationResponse(report=ValuationReportResponse.model_validate(report), sections=sections)
