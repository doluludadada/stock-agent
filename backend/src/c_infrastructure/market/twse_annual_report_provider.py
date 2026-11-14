import asyncio
import json
import re
import sys
import tempfile
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import IO, override

import httpx
from bs4 import BeautifulSoup

from a_domain.model.market.article import Article
from a_domain.ports.market.annual_report_provider import AnnualReport, IAnnualReportProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import AnnualReportSection, ContentType, InformationSource
from b_application.config.sources_config import AnnualReportSources
from c_infrastructure.market import annual_report_text
from c_infrastructure.market.exchange_text import ROC_YEAR_OFFSET
from c_infrastructure.market.request_pace import HostPace


class TwseAnnualReportProvider(IAnnualReportProvider):
    """
    A company's annual report from the exchange's document site in three requests, each after its turn on the site's
    pace (`pace`, which the wiring keeps in the database): the page that lists the meeting year's files, the request
    that answers the newest file's time-stamped address, and the file, fetched at once and streamed to a temporary
    file with no name, so nothing is left behind however the server stops. The text is read by a worker process
    (annual_report_text.read_report) that is killed past read_timeout_seconds. A file the site served and the worker
    could not read is answered as not readable, and logged. A request names a browser and nothing about this
    installation.
    """

    def __init__(self, reports: AnnualReportSources, pace: HostPace, market_clock: IMarketClock, logger: ILoggingProvider) -> None:
        self._reports = reports
        self._pace = pace
        self._clock = market_clock
        self._logger = logger

    @override
    async def fetch(self, stock_id: str, fiscal_year: int) -> AnnualReport | None:
        reports = self._reports
        index_url = reports.index_url.format(stock_id=stock_id, roc_year=fiscal_year + 1 - ROC_YEAR_OFFSET)

        try:
            async with httpx.AsyncClient(timeout=reports.timeout_seconds, headers={"User-Agent": reports.user_agent}) as client:
                await self._pace.wait(reports.request_interval_seconds)
                listing = await client.get(index_url)
                listing.raise_for_status()
                listed = newest_file(listing.content.decode(reports.encoding, errors="replace"), stock_id, reports)

                if listed is None:
                    return AnnualReport(fiscal_year=fiscal_year, file=None)

                windows = await fetched_sections(client, stock_id, listed[0], reports, self._pace, self._logger)
        except Exception as error:
            self._logger.warning(f"Annual report {stock_id} {fiscal_year}: could not be read: {type(error).__name__}: {error}")
            return None

        if windows is None:
            return AnnualReport(fiscal_year=fiscal_year, file=listed[0], readable=False)

        published_at, fetched_at = self._clock.session_close(listed[1] or self._clock.today()), self._clock.now()
        sections = [
            section_article(stock_id, fiscal_year, section, windows[section.value], index_url, published_at, fetched_at, reports)
            for section in AnnualReportSection
            if section.value in windows
        ]
        return AnnualReport(fiscal_year=fiscal_year, file=listed[0], sections=sections)


def section_article(
    stock_id: str,
    fiscal_year: int,
    section: AnnualReportSection,
    text: str,
    index_url: str,
    published_at: datetime,
    fetched_at: datetime,
    reports: AnnualReportSources,
) -> Article:
    """
    One section as the article store keeps it: titled by the report's ROC fiscal year and the section's heading as the
    settings write them, under the listing page's address with the section's name after it, so each section of a
    report has an address of its own, and published when the report was uploaded.
    """
    heading = reports.section_titles.get(section, section.value)
    return Article(
        stock_id=stock_id,
        source=InformationSource.ANNUAL_REPORT,
        content_type=ContentType.REPORT,
        title=reports.title.format(roc_year=fiscal_year - ROC_YEAR_OFFSET, section=heading),
        content=text,
        url=f"{index_url}#{section.value}",
        published_at=published_at,
        fetched_at=fetched_at,
        fact_date=date(fiscal_year, 12, 31),
    )


def newest_file(page: str, stock_id: str, reports: AnnualReportSources) -> tuple[str, date | None] | None:
    """
    The annual report's file name in the listing page and the day its row says it was uploaded, of the row uploaded
    last when the page lists several, as after a correction. None when the page lists none; the day is None when the
    row names none.
    """
    named = re.compile(reports.file_pattern.format(stock_id=re.escape(stock_id)))
    listed: list[tuple[date, str, date | None]] = []

    for row in BeautifulSoup(page, "lxml").find_all("tr"):
        text = row.get_text(" ")
        file = named.search(text)

        if file is None:
            continue

        uploaded = re.search(reports.upload_pattern, text[file.end() :])
        day = None

        if uploaded is not None:
            year, month, of_month = (int(part) for part in uploaded.groups())
            day = date(year + ROC_YEAR_OFFSET, month, of_month)

        listed.append((day or date.min, file.group(0), day))

    return max(listed)[1:] if listed else None


async def fetched_sections(
    client: httpx.AsyncClient, stock_id: str, file: str, reports: AnnualReportSources, pace: HostPace, logger: ILoggingProvider
) -> Mapping[str, str] | None:
    """
    The sections of the listed file: its time-stamped address asked for, then the file streamed at once into a
    temporary file that has no name, never held in memory, and read by the worker process. None, and a warning, for a
    file past max_bytes and for one the worker could not read. ValueError when the site answers no address.
    """
    await pace.wait(reports.request_interval_seconds)
    form = {**reports.file_form_fields, reports.stock_id_form_field: stock_id, reports.file_form_field: file}
    answer = await client.post(reports.file_url, data=form)
    answer.raise_for_status()
    link = re.search(reports.link_pattern, answer.content.decode(reports.encoding, errors="replace"))

    if link is None:
        raise ValueError(f"no address for {file} in the site's answer ({len(answer.content)} bytes)")

    await pace.wait(reports.request_interval_seconds)

    with tempfile.TemporaryFile() as report:
        async with client.stream("GET", f"{reports.site_url}{link.group(0)}") as response:
            response.raise_for_status()

            async for chunk in response.aiter_bytes():
                if report.tell() + len(chunk) > reports.max_bytes:
                    logger.warning(f"Annual report {file}: larger than {reports.max_bytes} bytes, so it is not read.")
                    return None

                report.write(chunk)

        report.seek(0)
        return await read_sections(report, file, reports, logger)


async def read_sections(
    report: IO[bytes], file: str, reports: AnnualReportSources, logger: ILoggingProvider
) -> Mapping[str, str] | None:
    """
    What the worker process reads of the PDF `report`, which it takes as its standard input: each section's window by
    the section's name, none for a file with no text. The worker is killed past read_timeout_seconds, and whenever
    this call is cancelled. None, and a warning, when it fails, is killed, runs out of time or answers that the file
    is no PDF it can read.
    """
    worker = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        str(Path(annual_report_text.__file__)),
        json.dumps(reports.reader_request()),
        stdin=report,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    answer = b""

    try:
        answer, _ = await asyncio.wait_for(worker.communicate(), reports.read_timeout_seconds)
    except TimeoutError:
        pass
    finally:
        if worker.returncode is None:
            worker.kill()
            await worker.wait()

    windows = json.loads(answer) if worker.returncode == 0 and answer else None

    if not isinstance(windows, dict):
        logger.warning(f"Annual report {file}: could not be read as a PDF (worker exit {worker.returncode}).")
        return None

    return windows
