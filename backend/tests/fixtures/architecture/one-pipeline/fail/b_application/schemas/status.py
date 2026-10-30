from dataclasses import dataclass


@dataclass
class PipelineStatus:
    order_id: str | None = None
