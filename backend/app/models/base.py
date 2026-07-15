from pydantic import BaseModel


class BaseRecord(BaseModel):
    id: str | None = None
