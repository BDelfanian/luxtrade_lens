"""The sole configuration boundary for the Comext package."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
Month = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class StrictModel(BaseModel):
    """Reject misspelled or unsupported configuration keys."""

    model_config = ConfigDict(extra="forbid")


class Sources(StrictModel):
    """Official directory URLs."""

    products: HttpUrl
    metadata: HttpUrl

    @field_validator("products", "metadata")
    @classmethod
    def official_url(cls, value: HttpUrl) -> HttpUrl:
        """Require official HTTPS Eurostat sources."""
        if value.scheme != "https" or value.host != "ec.europa.eu":
            raise ValueError("source must be an HTTPS URL on ec.europa.eu")
        if value.username or value.password:
            raise ValueError("credentials must not be embedded in source URLs")
        return value


class DownloadConfig(StrictModel):
    """Reference months, wildcard selection, and download destination."""

    start_date: Month
    end_date: Month
    include: list[str] = Field(min_length=1)
    exclude: list[str] = Field(default_factory=list)
    directory: Path
    timeout_seconds: int = Field(default=120, ge=1)

    @model_validator(mode="after")
    def date_range(self):
        """Validate the inclusive month range and wildcard patterns."""
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if int(self.start_date[:4]) < 1988:
            raise ValueError("CN classifications start in 1988; Nimexe is unsupported")
        if any(not pattern for pattern in self.include + self.exclude):
            raise ValueError("include/exclude patterns must not be empty")
        return self


class ImportConfig(StrictModel):
    """The Luxembourg-only import selection."""

    reporter: Literal["LU"] = "LU"


class DatabaseConfig(StrictModel):
    """Local DuckDB connection and resource limits; DuckDB needs no credentials."""

    driver: Literal["duckdb"]
    path: Path
    memory_limit: str = Field(default="1GB", pattern=r"^[1-9]\d*(MB|GB)$")
    threads: int = Field(default=1, ge=1, le=64)


def yaml_configuration() -> dict:
    """Read required YAML files; credentials cannot be supplied through YAML."""
    result = {}
    for path in (ROOT / "config/download.yaml", ROOT / "database.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"Cannot read configuration {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
        forbidden = {"password", "username", "credentials", "secret", "token", "api_key"}

        def check_secrets(node, forbidden=forbidden, path=path):
            if isinstance(node, dict):
                for key, value in node.items():
                    if str(key).lower() in forbidden:
                        raise ValueError(f"{path}: {key} belongs in environment/.env only")
                    check_secrets(value)
            elif isinstance(node, list):
                for value in node:
                    check_secrets(value)

        check_secrets(data)
        unknown = data.keys() - {"sources", "download", "import", "database"}
        if unknown:
            raise ValueError(f"{path}: unknown configuration sections {sorted(unknown)}")
        if result.keys() & data.keys():
            raise ValueError(f"{path}: duplicated configuration sections")
        result.update(data)
    # Settings sources must merge under the Python field name so nested environment
    # overrides cannot be shadowed by the YAML spelling of the reserved word "import".
    if "import" in result:
        result["import_"] = result.pop("import")
    return result


class Settings(BaseSettings):
    """Central configuration with environment and .env overrides."""

    model_config = SettingsConfigDict(
        env_prefix="COMEXT_",
        env_nested_delimiter="__",
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
    sources: Sources
    download: DownloadConfig
    import_: ImportConfig = Field(validation_alias=AliasChoices("COMEXT_IMPORT", "import"))
    database: DatabaseConfig

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Environment overrides .env, which overrides validated YAML defaults."""
        return init_settings, env_settings, dotenv_settings, yaml_configuration

    @model_validator(mode="after")
    def resolve_paths(self):
        """Resolve relative paths against the repository, independent of working directory."""
        for config, attr in ((self.download, "directory"), (self.database, "path")):
            path = getattr(config, attr)
            if not path.is_absolute():
                setattr(config, attr, (ROOT / path).resolve())
        if self.database.path.is_dir():
            raise ValueError("database.path must be a file, not a directory")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the shared, validated settings instance."""
    return Settings()
