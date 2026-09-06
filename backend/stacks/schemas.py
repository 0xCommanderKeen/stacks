from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    following: bool


class SeriesPage(BaseModel):
    items: list[SeriesOut]
    total: int
    limit: int
    offset: int


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


class PersonalValues(BaseModel):
    shelf_override: Literal["library", "archive"] | None = None
    notes: str = Field(default="", max_length=20000)
    rating: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values):
        tags = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(len(tag) > 100 for tag in tags):
            raise ValueError("Tags must be 100 characters or fewer.")
        return tags


class PersonalEdit(PersonalValues):
    revision: int = Field(ge=1)


class PersonalOut(PersonalValues):
    default_shelf: Literal["library", "archive"] = "library"
    shelf: Literal["library", "archive"] = "library"


class RecordEdit(BaseModel):
    revision: int = Field(default=1, ge=1)
    representation_id: str | None = None
    kind: Literal["read", "listen"]
    started: date
    finished: date | None = None

    @model_validator(mode="after")
    def chronological(self):
        if self.finished is not None and self.finished < self.started:
            raise ValueError("Finish date cannot precede start date.")
        return self


class RecordOut(RecordEdit):
    id: str
    work_id: str
    created_at: str


class RecordPage(BaseModel):
    items: list[RecordOut]
    total: int
    limit: int
    offset: int


class WorkOut(BaseModel):
    id: str
    title: str
    authors: list[str]
    description: str
    revision: int
    created_at: str
    editions: list[EditionOut]
    memberships: list[MembershipOut]
    personal: PersonalOut


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


class GroupRequest(BaseModel):
    mode: Literal["editions", "representation", "split"]
    source_work_id: str
    target_work_id: str | None = None
    representation_id: str | None = None
    target_edition_id: str | None = None


class ConflictOut(BaseModel):
    field: str
    source: str
    target: str


class GroupPreview(BaseModel):
    id: str
    mode: str
    source: WorkOut
    target: WorkOut | None
    conflicts: list[ConflictOut]
    explanation: str


class GroupCommit(BaseModel):
    resolutions: dict[str, Literal["source", "target"]] = Field(default_factory=dict)


class OperationOut(BaseModel):
    id: str
    state: str
    work_ids: list[str]
    created_at: str


class OperationPage(BaseModel):
    items: list[OperationOut]
    total: int
    limit: int
    offset: int


class ChapterOut(BaseModel):
    title: str
    start: float


class AudioTrackOut(BaseModel):
    asset_id: str
    title: str
    original_name: str
    duration: float
    chapters: list[ChapterOut]


class ProgressEdit(BaseModel):
    revision: int = Field(ge=0)
    asset_id: str
    position: float = Field(ge=0, le=1e9, allow_inf_nan=False)
    speed: float = Field(default=1, ge=0.5, le=3, allow_inf_nan=False)
    completed: bool = False


class ProgressOut(ProgressEdit):
    representation_id: str
    updated_at: str | None


class PlaybackOut(BaseModel):
    representation_id: str
    work_id: str
    title: str
    tracks: list[AudioTrackOut]
    progress: ProgressOut


class ContinueOut(BaseModel):
    work: WorkOut
    representation_id: str
    progress: ProgressOut


class ContinuePage(BaseModel):
    items: list[ContinueOut]
    total: int
    limit: int
    offset: int


class FollowEdit(BaseModel):
    revision: int = Field(ge=1)
    following: bool


class RunOut(BaseModel):
    series: SeriesOut
    owned: int
    finished: int


class RunPage(BaseModel):
    items: list[RunOut]
    total: int
    limit: int
    offset: int


class NextOut(BaseModel):
    series: SeriesOut
    work: WorkOut
    designation: str


class NextPage(BaseModel):
    items: list[NextOut]
    total: int
    limit: int
    offset: int


class RunWorksPage(CatalogPage):
    finished_work_ids: list[str]
