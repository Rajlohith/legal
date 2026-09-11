"""Request/response models for the FastAPI backend."""

from typing import List, Optional

from pydantic import BaseModel, Field


class AiFillRequest(BaseModel):
    text: str = Field(..., description="Natural-language description of the desired search")


class AiFillResponse(BaseModel):
    fields: dict
    notes: Optional[str] = None

class ChatMessage(BaseModel):
    role: str = Field(..., description='"user" or "assistant"')
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., description="Full conversation so far, oldest first")


class ChatResponse(BaseModel):
    reply: str


class AssistantRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., description="Full conversation so far, oldest first")
    fields: dict = Field(default_factory=dict, description="Validated fields from the previous turn")


class AssistantResponse(BaseModel):
    reply: str
    fields: dict
    display: List[dict] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)
    ready: bool = False
    mode: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class AssistantRunRequest(BaseModel):
    fields: dict
    output_filename: Optional[str] = None


class AssistantRunResponse(BaseModel):
    started: bool
    message: str
    mode: Optional[str] = None

class JudgeLookupRequest(BaseModel):
    db_bench: str = Field(..., description='"B" | "D" | "K"')


class SearchCriteria(BaseModel):
    # Registry bench (#db_bench) -- required, same as the site.
    db_bench: str = Field(..., description='"B" | "D" | "K"')

    # Multi-entity alias search (loops the scraper, as before).
    aliases: List[str] = Field(default_factory=list)
    alias_field: str = Field(default="respondname", description='"respondname" | "petname"')

    # Date of Order range. Both omitted only valid alongside a full
    # Case Type + Case Number + Case Year search.
    from_date: Optional[str] = Field(default=None, description="DD-MM-YYYY")
    to_date: Optional[str] = Field(default=None, description="DD-MM-YYYY")

    # Every other optional field on the real form.
    judge: Optional[str] = None
    author_judge: Optional[str] = None
    coram: Optional[str] = None
    case_type: Optional[str] = None
    case_no: Optional[str] = None
    case_year: Optional[str] = None
    petitioner_name: Optional[str] = None
    respondent_name: Optional[str] = None
    petitioner_adv: Optional[str] = None
    respondent_adv: Optional[str] = None
    report_type: Optional[str] = None

    included_sections: Optional[List[str]] = Field(
        default=None,
        description="Which sections to extract/include (see /api/form-options' "
                    "'sections' list). Omit or null = include everything.",
    )

    output_filename: Optional[str] = None


class SearchStartResponse(BaseModel):
    started: bool
    message: str


class CaseNumberSearchCriteria(BaseModel):
    """Fields for the site's separate 'Quick Search by Case No.' page --
    just Bench + Case Type + Case Number + Case Year, all required."""

    db_bench: str = Field(..., description='"B" | "D" | "K"')
    case_type: str = Field(..., description="Case type code, e.g. 156")
    case_no: str = Field(..., description="Digits only, max 6")
    case_year: str = Field(..., description="e.g. 2024")

    included_sections: Optional[List[str]] = Field(
        default=None,
        description="Which sections to extract/include. Omit or null = everything.",
    )

    output_filename: Optional[str] = None
