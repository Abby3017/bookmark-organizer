from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ArticleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str]
    bullets: List[str] = Field(
        min_length=1,
        max_length=3,
        description="One to three concise key points from the article."
    )
    tags: List[str] = Field(
        min_length=5,
        max_length=5,
        description="Exactly five relevant tags."
    )

class ProcessedArticleSummary(BaseModel):
    id: str #summary-14b294f42b846d3f
    summary: ArticleSummary 
    url: Optional[str] = Field(
        default=None,
        description="The URL of the article."
    )
    content: Optional[str] = Field(
        default=None,
        description="The content of the article."
    )
