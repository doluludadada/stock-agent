from fastapi import APIRouter

from a_domain.types.enums import Feature
from d_presentation.web.schemas import StockNewsItemResponse, WorldResponse
from d_presentation.web.session import PrivateAccess, SignedOutPipeline, shows

router = APIRouter(prefix="/world", tags=["World"], dependencies=[PrivateAccess, shows(Feature.WORLD)])


@router.get("")
async def get_world(pipeline: SignedOutPipeline) -> WorldResponse:
    """
    What the site holds of the world outside Taiwan's exchanges, with no fetch and no AI call. `indicators`: each held
    world indicator's newest reading, the one before it and its change. `briefs`: the written world briefs of the
    latest world.brief.shown_days days that have one, newest first; the site writes one per Taipei day from
    world.brief.write_at on, and each sentence is the AI's wording of held readings and held news items and names
    those it rests on, with the listed stocks a cited item names itself. `news`: the newest world.shown kept items of
    the world news feeds, each with its publisher, its time, its address and the feed's own summary. `write_at` is
    the Taipei time from which the site writes the day's brief, null on a site that writes none. Every title and
    summary is a third party's: show it as text, never as markup. Private.
    """
    world = await pipeline.load_world()
    items = [StockNewsItemResponse.model_validate(item) for item in world.news]

    return WorldResponse(indicators=world.readings, briefs=world.briefs, news=items, write_at=world.write_at)
