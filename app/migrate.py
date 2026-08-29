"""Apply database migrations once before starting horizontally scaled services."""
from __future__ import annotations

from .database import Database
from .settings import get_settings


def main() -> None:
    settings = get_settings()
    database = Database(
        settings.database_url,
        min_size=1,
        max_size=1,
        timeout=settings.db_pool_timeout_seconds,
    )
    try:
        database.initialize(run_migrations=True)
    finally:
        database.close()


if __name__ == "__main__":
    main()
