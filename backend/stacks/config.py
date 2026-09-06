from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STACKS_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    password: SecretStr = Field(min_length=12)
    secure_cookie: bool = False
    max_upload_bytes: int = Field(default=100 * 1024 * 1024, ge=1024, le=1024**3)
    frontend_dir: Path = Path("frontend/build")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "catalog.sqlite3"
