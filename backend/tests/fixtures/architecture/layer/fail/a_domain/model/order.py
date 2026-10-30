from dataclasses import dataclass

import sqlalchemy
from b_application.schemas.pipeline_status import PipelineStatus
from src.c_infrastructure.database.connector import Database


@dataclass
class Order:
    total: int
