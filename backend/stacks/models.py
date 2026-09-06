"""The first usable path through the domain: Work → Edition → Representation → Asset."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def identity() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Work(Base):
    __tablename__ = "work"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[str] = mapped_column(default=now, index=True)
    editions: Mapped[list["Edition"]] = relationship(cascade="all, delete-orphan")
    credits: Mapped[list["Credit"]] = relationship(
        cascade="all, delete-orphan", order_by="Credit.position"
    )


class Contributor(Base):
    __tablename__ = "contributor"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    name: Mapped[str] = mapped_column(Text)


class Credit(Base):
    __tablename__ = "credit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    work_id: Mapped[str] = mapped_column(ForeignKey("work.id"), index=True)
    contributor_id: Mapped[str] = mapped_column(ForeignKey("contributor.id"))
    role: Mapped[str] = mapped_column(default="author")
    position: Mapped[int]
    contributor: Mapped[Contributor] = relationship()


class Edition(Base):
    __tablename__ = "edition"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    work_id: Mapped[str] = mapped_column(ForeignKey("work.id"), index=True)
    medium: Mapped[str] = mapped_column(default="ebook")
    language: Mapped[str] = mapped_column(default="")
    publisher: Mapped[str] = mapped_column(Text, default="")
    identifier: Mapped[str] = mapped_column(Text, default="")
    representations: Mapped[list["Representation"]] = relationship(cascade="all, delete-orphan")


class Representation(Base):
    __tablename__ = "representation"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    edition_id: Mapped[str] = mapped_column(ForeignKey("edition.id"), index=True)
    format: Mapped[str] = mapped_column(default="epub")
    cover_path: Mapped[str | None] = mapped_column(Text)
    # Raw embedded facts stay available after accepted metadata is edited.
    extracted_json: Mapped[str] = mapped_column(Text, default="{}")
    assets: Mapped[list["Asset"]] = relationship(
        cascade="all, delete-orphan", order_by="Asset.position"
    )


class Asset(Base):
    __tablename__ = "asset"
    __table_args__ = (UniqueConstraint("representation_id", "position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identity)
    representation_id: Mapped[str] = mapped_column(ForeignKey("representation.id"), index=True)
    position: Mapped[int] = mapped_column(default=0)
    root: Mapped[str] = mapped_column(default="managed")
    relative_path: Mapped[str] = mapped_column(Text, unique=True)
    original_name: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(BigInteger)


class ImportOperation(Base):
    __tablename__ = "import_operation"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state: Mapped[str] = mapped_column(default="staged", index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(BigInteger)
    original_name: Mapped[str] = mapped_column(Text)
    extracted_json: Mapped[str] = mapped_column(Text)
    work_id: Mapped[str | None] = mapped_column(String(36))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(default=now)


class LoginSession(Base):
    __tablename__ = "login_session"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[int]
