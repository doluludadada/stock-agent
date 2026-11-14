from datetime import date, datetime
from typing import Annotated

from pydantic import ConfigDict, Field, FiniteFloat, validate_call
from pydantic.dataclasses import dataclass

from a_domain.types.enums import BriefLanguage, BriefSourceKind, BriefStatus
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


@dataclass(frozen=True, kw_only=True)
class BriefSentence:
    """One sentence of a brief and the held items it rests on. A sentence that cites none is never kept."""

    text: NonEmptyText
    sources: Annotated[list[str], Field(min_length=1)]
    """Keys of the brief's sources."""


@dataclass(config=ConfigDict(validate_assignment=True), kw_only=True)
class StockBrief:
    """
    The AI's short description of one stock on one Taipei calendar day, shared by every viewer of the site: what the
    company is, and how the held facts of a recent window of sessions relate to the stock's move over it. It describes
    and never advises. One exists per stock and day; its status says whether the AI is still asked.
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
    """How the held facts of the window relate to the stock's move."""

    sources: list[BriefSource] = Field(default_factory=list)
    """The held items the sentences cite."""

    @validate_call
    def write(self, company: list[BriefSentence], movement: list[BriefSentence], sources: list[BriefSource], now: datetime) -> None:
        self._move(BriefStatus.WRITTEN)
        self.company, self.movement, self.sources, self.written_at = company, movement, sources, now

    def fail(self) -> None:
        self._move(BriefStatus.FAILED)

    def _move(self, status: BriefStatus) -> None:
        if status not in self.status.next_statuses:
            raise IllegalBriefTransition(f"A brief cannot go from {self.status} to {status}.")

        self.status = status
