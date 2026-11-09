"""Applies database migrations from inside the app. A single-container host has no separate
step that runs before the app starts, so the app brings its own schema up to date."""

from alembic.config import Config

from alembic import command
from app.core.config import BACKEND_DIR


def upgrade_to_head(configure_logging: bool = True) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["configure_logging"] = configure_logging
    command.upgrade(config, "head")
