"""Process-wide configuration sourced from the environment and ``.env``.

Values are read once from the environment, falling back to the ``.env``
file at the repository root. A missing required setting raises a Pydantic
``ValidationError`` at load time rather than failing later mid-run.
"""

from functools import cache
from pathlib import Path

from pydantic import EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Runtime configuration for Avelorn tooling.

    Attributes:
        attribution_email: Contact e-mail advertised to external services
            (e.g. the tow.whfb.app importer's User-Agent). Required.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    attribution_email: EmailStr


@cache
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once.

    Constructing :class:`Settings` raises ``pydantic.ValidationError`` if a
    required setting is missing from both the environment and ``.env``.

    Returns:
        The validated settings.
    """
    # Fields are populated from the environment and .env by pydantic-settings,
    # which ty's type checker does not model.
    return Settings()  # ty: ignore[missing-argument]
