from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    keyword: str
    text: str
    image_paths: list[str] | None = None
