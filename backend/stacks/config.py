import re
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STACKS_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    password: SecretStr = Field(min_length=12)
    sources: dict[str, Path] = Field(default_factory=dict)
    provider_contact: str = Field(default="", max_length=128)
    secure_cookie: bool = False
    max_upload_bytes: int = Field(default=100 * 1024 * 1024, ge=1024, le=1024**3)
    frontend_dir: Path = Path("frontend/build")

    @field_validator("provider_contact")
    @classmethod
    def valid_provider_contact(cls, value):
        if not value.isascii() or any(ord(c) < 32 for c in value):
            raise ValueError("Provider contact must be printable ASCII.")
        return value.strip()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "catalog.sqlite3"

    @field_validator("sources")
    @classmethod
    def source_names(cls, sources):
        for alias, path in sources.items():
            if alias == "managed" or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", alias):
                raise ValueError("Source aliases must be lowercase names; managed is reserved.")
            if not path.is_absolute():
                raise ValueError("Source directories must use absolute paths.")
        return sources
