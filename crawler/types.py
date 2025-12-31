from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional

class FamilyParsed(BaseModel):
    slug: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    downloads: Optional[int] = None
    catalog_updated_text: Optional[str] = None

class VariantParsed(BaseModel):
    family_slug: str
    tag: str
    tag_short: Optional[str] = None
    digest: Optional[str] = None
    size_bytes: int
    max_context: Optional[int] = None
    input_type: Optional[str] = None
    catalog_age_text: Optional[str] = None
