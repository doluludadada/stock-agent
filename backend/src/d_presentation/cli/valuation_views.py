"""
Menus 5 and 6: P/E valuation of chosen stocks and the undervalued scan. They read only the Pipeline's valuation
workflows, which decide what to value and reach no order, signal or watchlist write. The order-gate check reads this module.
"""

import math
from collections.abc import Callable, Mapping, Sequence

from pydantic import TypeAdapter, ValidationError
from rich.panel import Panel
from rich.table import Table

from a_domain.model.fundamentals.eps import Eps
from a_domain.model.valuation.scan import MarketValuation, ScanCriteria, ValuationScan
from a_domain.model.valuation.valuation import ReportSection, StockValuation, ValuationReport
from a_domain.types.enums import EliminationReason, ScanStep
from a_domain.types.values import PositiveFiniteFloat
from b_application.config.app_config import AppConfig
from b_application.pipeline import Pipeline
from d_presentation.cli import terminal
from d_presentation.dependencies import Runtime


async def value_specific_stocks(runtime: Runtime, session: terminal.CliSession) -> None:
    """Menu 5. It uses no technical strategy, so the session's built-in strategy does not apply."""
    stock_ids = terminal.ask_stock_ids()

    if stock_ids is None:
        return

    market = await load_market(runtime.pipeline)
    valuations = find_valuations(market, stock_ids)

    if not valuations:
        terminal.console.print("[yellow]No stocks loaded.[/yellow]")
        return

    print_valuation_facts(valuations, market, runtime.config)
    needs_target = any(valuation.needs_target_pe for valuation in valuations)
    target_pe = ask_target_pe() if needs_target else None

    if needs_target and target_pe is None:
        terminal.console.print("[yellow]Target P/E cancelled. No fair price or AI explanation was produced.[/yellow]")
        return

    terminal.console.print(f"Asking the AI to explain: {', '.join(item.stock.stock_id for item in valuations)}")

    for report in runtime.pipeline.appraise_valuations(valuations, target_pe):
        print_valuation_explanation(report, await runtime.pipeline.explain_valuation(report))


async def scan_undervalued_stocks(runtime: Runtime, session: terminal.CliSession) -> None:
    market = await load_market(runtime.pipeline)

    if not market.valuations:
        terminal.console.print("[yellow]No stocks loaded.[/yellow]")
        return

    print_market_reference(market, runtime.config)
    criteria = ask_scan_criteria()

    if criteria is None:
        terminal.console.print("[yellow]Scan cancelled.[/yellow]")
        return

    scan = runtime.pipeline.screen_valuation(market, criteria)
    print_valuation_step(scan, runtime.config)

    if not scan.survivors:
        return

    if terminal.confirm(f"Confirm {len(scan.survivors)} matches with the technical strategy?"):
        terminal.console.print("Loading daily history for the matches...")
        scan = await runtime.pipeline.confirm_valuation_technical(scan, session.built_in_strategy_id)
        print_technical_step(scan)

    candidates = scan.explanation_candidates

    if candidates and terminal.confirm(f"Explain the top {len(candidates)} stocks with AI ({len(candidates)} AI calls)?"):
        for report in candidates:
            print_valuation_explanation(report, await runtime.pipeline.explain_valuation(report))


async def load_market(pipeline: Pipeline) -> MarketValuation:
    terminal.console.print("Loading listed stocks, official closes and EPS filings (TWSE, TPEX, MOPS)...")
    market = await pipeline.load_market_valuation()

    for warning in market.source_warnings:
        terminal.console.print(f"[yellow]{warning}[/yellow]")

    return market


def find_valuations(market: MarketValuation, stock_ids: list[str]) -> list[StockValuation]:
    valuations: list[StockValuation] = []

    for stock_id in dict.fromkeys(stock_ids):
        item = market.find(stock_id)

        if item is None:
            terminal.console.print(f"[yellow]Stock not found: {stock_id}[/yellow]")
            continue

        valuations.append(item)

    return valuations


def ask_target_pe() -> PositiveFiniteFloat | None:
    return ask_number("Target P/E (a finite number > 0; blank cancels)", TypeAdapter(PositiveFiniteFloat).validate_python)


def ask_scan_criteria() -> ScanCriteria | None:
    target_pe = ask_target_pe()

    if target_pe is None:
        return None

    return ask_number(
        "Minimum undervaluation % (a finite number >= 0, e.g. 20; blank cancels)",
        lambda percent: ScanCriteria(target_pe=target_pe, min_undervaluation=percent / 100),
    )


def ask_number[Value](question: str, parse: Callable[[float], Value]) -> Value | None:
    """
    Asks until `parse` accepts the number typed, printing what was wrong in one line for each refusal; blank cancels.
    Text that is not a number reaches `parse` as NaN, which the target P/E and ScanCriteria refuse as not finite.
    """
    while True:
        raw_value = terminal.ask_user(question)

        if raw_value is None or not raw_value.strip():
            return None

        try:
            return parse(parse_number(raw_value))
        except ValidationError as error:
            reasons = "; ".join(detail["msg"] for detail in error.errors())
            terminal.console.print(reasons, style="red", markup=False, highlight=False)


def parse_number(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return math.nan


def print_market_reference(market: MarketValuation, config: AppConfig) -> None:
    median = market.median_pe()
    median_text = f"{median.value:.2f} (over {median.sample_size} stocks with EPS > 0 and a fresh close)" if median else "-"

    terminal.console.print(f"Market median P/E for reference: {median_text}")
    terminal.console.print(
        f"Last closed session: {market.last_closed_session}. "
        f"A close is stale once {config.freshness.daily_close_max_missed_sessions + 1} or more "
        "weekday sessions have closed after it; stale closes are excluded from the scan."
    )


def print_valuation_facts(valuations: list[StockValuation], market: MarketValuation, config: AppConfig) -> None:
    table = Table(title="Valuation Facts")

    for column in ("Stock", "Name", "Industry", "Close (session)", "EPS", "Current P/E", "Industry median P/E"):
        table.add_column(column)

    for item in valuations:
        stock = item.stock
        industry_median = item.industry_median_pe

        table.add_row(
            stock.stock_id,
            stock.name or "",
            stock.industry or "-",
            item.price_text,
            item.eps.describe(),
            item.pe_text,
            f"{industry_median.value:.2f} ({industry_median.sample_size} stocks)" if industry_median else "-",
        )

    terminal.console.print(table)
    print_market_reference(market, config)

    for item in valuations:
        for warning in item.warnings:
            terminal.console.print(f"[yellow]{item.stock.stock_id}: {warning}[/yellow]")


def print_valuation_explanation(report: ValuationReport, sections: Sequence[ReportSection]) -> None:
    stock = report.stock
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", no_wrap=True)
    grid.add_column(overflow="fold")

    for section in sections:
        grid.add_row(section.title, "\n".join(section.lines))

    title = f"{stock.stock_id} {stock.name or ''} · Valuation based on a specified P/E"
    terminal.console.print(Panel(grid, title=title, title_align="left"))


def print_valuation_step(scan: ValuationScan, config: AppConfig) -> None:
    criteria = scan.criteria
    eliminated = scan.elimination_counts(ScanStep.VALUATION)
    scanned = len(scan.survivors) + sum(eliminated.values())

    terminal.console.print(f"Valuation step: target P/E {criteria.target_pe:.2f}, undervaluation >= {criteria.min_undervaluation:.1%}")
    terminal.console.print(f"({config.valuation.undervaluation_formula})")
    terminal.console.print(f"Scanned {scanned} -> passed {len(scan.survivors)}")
    terminal.console.print(f"Eliminated at valuation: {format_eliminations(eliminated)}")
    terminal.console.print(undervalued_table(scan))
    terminal.console.print(config.valuation.low_pe_caveat)


def undervalued_table(scan: ValuationScan) -> Table:
    target = scan.criteria.target_pe
    table = Table(title=f"Undervalued at target P/E {target:.2f} · Valuation based on a specified P/E · not a BUY signal")

    for column in ("#", "Stock", "Name", "Close (session)", "EPS", "Current P/E", "Target P/E", "Fair price", "Undervalued"):
        table.add_column(column)

    table.add_column("EPS period")
    table.add_column("Source")

    for index, report in enumerate(scan.survivors, 1):
        stock = report.stock
        eps = stock.eps if isinstance(stock.eps, Eps) else None
        base = report.base

        table.add_row(
            str(index),
            stock.stock_id,
            stock.name or "",
            report.valuation.price_text,
            f"{eps.value:.2f}" if eps else "-",
            report.valuation.pe_text,
            f"{base.target_pe:.2f}" if base else "-",
            f"{base.fair_price:,.2f}" if base else "-",
            f"{base.undervaluation:.1%}" if base else "-",
            f"{eps.kind.label} {eps.period_label}" if eps else "-",
            eps.source.label if eps else "-",
        )

    return table


def print_technical_step(scan: ValuationScan) -> None:
    technical_eliminations = scan.technical_eliminations
    table = Table(title=f"Two-step screen: valuation -> technical ({scan.technical_strategy_id})")

    for column in ("Stock", "Name", "Undervalued", "Valuation", "Technical", "Tech score", "Eliminated at", "Reason"):
        table.add_column(column)

    for report in scan.valuation_survivors:
        stock = report.stock
        elimination = technical_eliminations.get(stock.stock_id)

        table.add_row(
            stock.stock_id,
            stock.name or "",
            f"{report.undervaluation:.1%}" if report.undervaluation is not None else "-",
            "passed",
            "eliminated" if elimination else "passed",
            terminal.format_optional_int(stock.technical_score),
            elimination.reason.step.label if elimination else "-",
            (elimination.detail or elimination.reason.label) if elimination else "passed both steps",
        )

    terminal.console.print(table)
    terminal.console.print(
        f"Passed both steps: {len(scan.survivors)}. "
        f"Eliminated at technical: {format_eliminations(scan.elimination_counts(ScanStep.TECHNICAL))}"
    )
    terminal.console.print("No trading signal, watchlist entry or order is created. A low P/E is not a BUY signal.")


def format_eliminations(counts: Mapping[EliminationReason, int]) -> str:
    return " | ".join(f"{reason.label} {count}" for reason, count in counts.items()) or "none"
