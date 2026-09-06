from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AssetOut(BaseModel):
    id: str
    original_name: str
    size: int
    sha256: str


class RepresentationOut(BaseModel):
    id: str
    format: str
    has_cover: bool
    facts: dict
    capabilities: list[str]
    assets: list[AssetOut]


class EditionOut(BaseModel):
    id: str
    medium: str
    language: str
    publisher: str
    identifier: str
    narrator: str
    abridgement: str
    representations: list[RepresentationOut]


class SeriesEdit(BaseModel):
    revision: int = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=1024)
    run: str = Field(default="", max_length=1024)

    @field_validator("name")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("A series name is required.")
        return value.strip()


class SeriesOut(SeriesEdit):
    id: str


class MembershipEdit(BaseModel):
    series_id: str
    designation: str = Field(default="", max_length=128)
    position: float = Field(allow_inf_nan=False, ge=-1e9, le=1e9)


class MembershipOut(MembershipEdit):
    series: SeriesOut


class EditionEdit(BaseModel):
    id: str
    language: str = Field(max_length=64)
    publisher: str = Field(max_length=1024)
    identifier: str = Field(max_length=1024)
    narrator: str = Field(default="", max_length=1024)
    abridgement: Literal["unknown", "unabridged", "abridged"] = "unknown"


class WorkOut(BaseModel):
    id: str
    title: str
    authors: list[str]
    description: str
    revision: int
    created_at: str
    editions: list[EditionOut]
    memberships: list[MembershipOut]


class CatalogPage(BaseModel):
    items: list[WorkOut]
    total: int
    limit: int
    offset: int


class ImportResult(BaseModel):
    work: WorkOut
    duplicate: bool


class WorkEdit(BaseModel):
    editions: list[EditionEdit] | None = Field(default=None, max_length=100)
    memberships: list[MembershipEdit] | None = Field(default=None, max_length=100)
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=1024)
    authors: list[str] = Field(max_length=20)
    description: str = Field(max_length=20000)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("A title is required.")
        return value.strip()

    @field_validator("authors")
    @classmethod
    def author_names(cls, value):
        names = [v.strip() for v in value if v.strip()]
        if any(len(v) > 512 for v in names):
            raise ValueError("Author names must be 512 characters or fewer.")
        return names


class Login(BaseModel):
    password: str = Field(max_length=1024)


class StatusOut(BaseModel):
    books: int
    import_errors: int
    version: str = "0.1.0"
