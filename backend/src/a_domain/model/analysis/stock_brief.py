from datetime import date, datetime
from typing import Annotated

from pydantic import ConfigDict, Field, FiniteFloat, validate_call
from pydantic.dataclasses import dataclass

from a_domain.types.enums import BriefLanguage, BriefSourceKind, BriefStatus, InformationSource
from a_domain.types.errors import IllegalBriefTransition
from a_domain.types.values import NonEmptyText


@dataclass(frozen=True, kw_only=True)
class BriefSource:
    """One held item a brief was written from, which the brief's sentences cite by its key."""

    key: NonEmptyText
    """The item's name in the prompt and in a sentence's citations, such as S3."""

    kind: BriefSourceKind
    dated: date
    """The day the item is of: a session, the day a month's revenue was served, a quarter's last day, the day of an article."""

    title: str | None = None
    """An article's title as its source gave it: a third party's text. None for a figure the site computed."""

    url: str | None = None
    """The article's address as held. None for an item the stock page shows itself."""

    origin: InformationSource | None = None
    """The publisher of a world news item, which the page names beside its title. None for every other item."""


@dataclass(frozen=True, kw_only=True)
class BriefSentence:
    """One sentence of a brief and the held items it rests on. A sentence that cites none is never kept."""

    text: NonEmptyText
    sources: Annotated[list[str], Field(min_length=1)]
    """Keys of the brief's sources."""

    stocks: list[str] = Field(default_factory=list)
    """
    The listed stocks a world brief's sentence links to, by id: only those whose id or name one of the held items the
    sentence cites holds itself (BriefReplyRule). Empty in a stock's brief and card.
    """


def move_to(brief: StockBrief, status: BriefStatus) -> None:
    if status not in brief.status.next_statuses:
        raise IllegalBriefTransition(f"A brief cannot go from {brief.status} to {status}.")

    brief.status = status


@dataclass(config=ConfigDict(validate_assignment=True), kw_only=True)
class StockBrief:
    """
    The AI's short description of one stock on one Taipei calendar day, shared by every viewer of the site: what the
    company is, and how the held facts of a recent window of sessions relate to the stock's move over it. It describes
    and never advises. One exists per stock and day; its status says whether the AI is still asked. A company card is
    one too (BriefKind): it holds the `company` part alone, under the day it was claimed on, and the newest written one
    is the company's card. So is the day's world brief, whose `stock_id` is MarketScope.WORLD: it holds the `movement`
    part alone, what moved in the held world indicators and which held world news may bear on Taiwan's market.
    """

    stock_id: NonEmptyText
    day: date
    """The Taipei calendar day the brief is of."""

    status: BriefStatus
    language: BriefLanguage
    model: NonEmptyText
    """The id of the AI model that was asked."""

    claimed_at: datetime
    """When a viewer's request claimed the day's brief."""

    written_at: datetime | None = None
    """When the AI's reply was kept. None until the brief is written."""

    window_first: date | None = None
    window_last: date | None = None
    """The first and the last session of the window the brief covers. None when the site holds no daily history of the stock."""

    price_change: FiniteFloat | None = None
    """The change of the close from the window's first session to its last: 0.12 is 12% more."""

    company: list[BriefSentence] = Field(default_factory=list)
    """What the company is."""

    movement: list[BriefSentence] = Field(default_factory=list)
    """How the held facts of the window relate to the stock's move; in the world brief, what moved and happened in the world."""

    sources: list[BriefSource] = Field(default_factory=list)
    """The held items the sentences cite."""

    fingerprint: str | None = None
    """
    What a company card was written from, as a digest: the card is written again only when it changes. None for a
    daily brief, which is written once a day whatever it rests on.
    """

    @validate_call
    def write(self, company: list[BriefSentence], movement: list[BriefSentence], sources: list[BriefSource], now: datetime) -> None:
        move_to(self, BriefStatus.WRITTEN)
        self.company, self.movement, self.sources, self.written_at = company, movement, sources, now

    def abandoned(self, stale_before: datetime) -> bool:
        """Whether its writer claimed it before `stale_before` and never wrote or failed it: a stopped server left it behind."""
        return self.status == BriefStatus.WRITING and self.claimed_at < stale_before

    def fail(self) -> None:
        move_to(self, BriefStatus.FAILED)
