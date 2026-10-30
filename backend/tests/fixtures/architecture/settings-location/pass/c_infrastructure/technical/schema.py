from pydantic import BaseModel


class TechnicalSchema(BaseModel):
    window: int = 14
