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
    assets: list[AssetOut]


class EditionOut(BaseModel):
    id: str
    medium: str
    language: str
    publisher: str
    identifier: str
    representations: list[RepresentationOut]


class WorkOut(BaseModel):
    id: str
    title: str
    authors: list[str]
    description: str
    revision: int
    created_at: str
    editions: list[EditionOut]


class CatalogPage(BaseModel):
    items: list[WorkOut]
    total: int
    limit: int
    offset: int


class ImportResult(BaseModel):
    work: WorkOut
    duplicate: bool


class WorkEdit(BaseModel):
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
