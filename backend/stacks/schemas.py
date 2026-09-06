from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class AssetOut(BaseModel):
    id: str
    root: str
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


SeriesPosition = Annotated[float, Field(allow_inf_nan=False, ge=-1e9, le=1e9)]


class MembershipEdit(BaseModel):
    series_id: str
    designation: str = Field(default="", max_length=128)
    position: SeriesPosition


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
    selected_cover_id: str | None
    updated_at: str
    trashed_at: str | None
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
    representation_id: str
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


class CollectionEdit(BaseModel):
    revision: int = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=1024)
    home: bool = False

    @field_validator("name")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("A collection name is required.")
        return value.strip()


class CollectionOut(CollectionEdit):
    id: str
    count: int


class CollectionPage(BaseModel):
    items: list[CollectionOut]
    total: int
    limit: int
    offset: int


class CollectionChange(BaseModel):
    revision: int = Field(ge=1)
    action: Literal["add", "remove", "up", "down", "add_series"]
    work_id: str | None = None
    series_id: str | None = None


class CollectionEntryOut(BaseModel):
    id: str
    position: int
    work: WorkOut
    finished: bool


class CollectionWorksPage(BaseModel):
    collection: CollectionOut
    items: list[CollectionEntryOut]
    total: int
    limit: int
    offset: int


class CollectionNextOut(BaseModel):
    collection: CollectionOut
    work: WorkOut


class CollectionNextPage(BaseModel):
    items: list[CollectionNextOut]
    total: int
    limit: int
    offset: int


class SourceOut(BaseModel):
    alias: str
    configured: bool
    available: bool
    registered_assets: int


class SourceRegistration(BaseModel):
    root: str = Field(max_length=64)
    paths: list[str] = Field(min_length=1, max_length=2000)

    @field_validator("paths")
    @classmethod
    def bounded_paths(cls, paths):
        if any(not path or len(path) > 1024 for path in paths):
            raise ValueError("Each relative path must be between 1 and 1024 characters.")
        return paths


class AssetAvailability(BaseModel):
    asset_id: str
    available: bool
    detail: str


class ScanRequest(BaseModel):
    root: str = Field(min_length=1, max_length=64)
    prefix: str = Field(default="", max_length=1024)


class JobChange(BaseModel):
    action: Literal["cancel", "retry", "confirm"]
    revision: int = Field(ge=1)


class JobOut(BaseModel):
    id: str
    kind: str
    root: str
    prefix: str
    state: str
    revision: int
    error: str | None
    created_at: str
    updated_at: str
    discovered: int
    completed: int
    remaining: int
    skipped: int
    failed: int
    directories_remaining: int


class JobPage(BaseModel):
    items: list[JobOut]
    total: int
    limit: int
    offset: int


class CandidateOut(BaseModel):
    id: str
    root: str
    relative_path: str
    state: str
    revision: int
    sha256: str | None
    facts: dict
    edits: dict
    work_id: str | None
    error: str | None
    updated_at: str


class CandidatePage(BaseModel):
    items: list[CandidateOut]
    total: int
    limit: int
    offset: int


class AcceptedMetadata(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=1024)
    authors: list[str] | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=20000)
    language: str | None = Field(default=None, max_length=64)
    publisher: str | None = Field(default=None, max_length=1024)
    identifier: str | None = Field(default=None, max_length=1024)
    narrator: str | None = Field(default=None, max_length=1024)
    shelf: Literal["default", "library", "archive"] = "default"
    series_id: str | None = None
    designation: str = Field(default="", max_length=100)
    position: SeriesPosition = 0

    @field_validator("title")
    @classmethod
    def accepted_title(cls, value):
        if value is not None and not value.strip():
            raise ValueError("A title is required.")
        return value.strip() if value is not None else None

    @field_validator("authors")
    @classmethod
    def accepted_authors(cls, value):
        return WorkEdit.author_names(value) if value is not None else None


class CandidateEdit(BaseModel):
    revision: int = Field(ge=1)
    metadata: AcceptedMetadata


class AcceptanceRequest(BaseModel):
    candidate_ids: list[str] | None = Field(default=None, min_length=1, max_length=2000)
    q: str = Field(default="", max_length=300)
    root: str = Field(default="", max_length=64)
    state: str = Field(default="ready", max_length=20)
    scan_id: str = Field(default="", max_length=36)
    mode: Literal["register", "copy"] = "register"
    metadata: AcceptedMetadata = Field(default_factory=AcceptedMetadata)
    group_audio: bool = False
    audio_singles_confirmed: bool = False


class AcceptanceItemOut(BaseModel):
    series: SeriesOut | None
    id: str
    group_id: str
    candidate: CandidateOut
    metadata: AcceptedMetadata
    state: str
    error: str | None
    work_id: str | None


class AcceptancePage(BaseModel):
    confirmed: bool
    job: JobOut
    mode: Literal["register", "copy"]
    grouped_audio: bool
    items: list[AcceptanceItemOut]
    total: int
    limit: int
    offset: int


class TrashRequest(BaseModel):
    revision: int = Field(ge=1)
    action: Literal["trash", "restore"]


class TrashRetry(BaseModel):
    revision: int = Field(ge=1)


class TrashOperationOut(BaseModel):
    id: str
    work_id: str
    action: str
    state: str
    revision: int
    error: str | None
    created_at: str
    completed: int
    total: int


class TrashEntryOut(BaseModel):
    work: WorkOut
    operation: TrashOperationOut


class TrashPage(BaseModel):
    items: list[TrashEntryOut]
    total: int
    limit: int
    offset: int


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scope: Literal["library", "all"] = "library"

    @field_validator("name")
    @classmethod
    def named_device(cls, value):
        if not value.strip():
            raise ValueError("Name this reader or device.")
        return value.strip()


class DeviceOut(BaseModel):
    id: str
    name: str
    scope: str
    created_at: str
    last_used_at: str | None


class DevicePage(BaseModel):
    items: list[DeviceOut]
    total: int
    limit: int
    offset: int


class DeviceIssued(BaseModel):
    device: DeviceOut
    username: str
    password: str
    catalog_url: str


class FieldOrigin(BaseModel):
    source: Literal["manual", "embedded", "openlibrary"]
    protected: bool
    selected_at: str | None = None
    provider_key: str | None = None
    source_url: str | None = None


class SuggestedValues(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=1024)
    authors: list[str] | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=20000)


class SuggestionOut(BaseModel):
    id: str
    provider_key: str
    source_url: str
    fetched_at: str
    detailed: bool
    values: SuggestedValues


class MetadataSearch(BaseModel):
    q: str = Field(min_length=1, max_length=300)
    offset: int = Field(default=0, ge=0, le=10000)


class SuggestionPage(BaseModel):
    items: list[SuggestionOut]
    total: int
    offset: int
    limit: int = 5


class MetadataState(BaseModel):
    work: WorkOut
    origins: dict[str, FieldOrigin]


class MetadataAccept(BaseModel):
    suggestion_fetched_at: str
    revision: int = Field(ge=1)
    fields: list[Literal["title", "authors", "description"]] = Field(min_length=1, max_length=3)
    replace_protected: list[Literal["title", "authors", "description"]] = Field(
        default_factory=list, max_length=3
    )
