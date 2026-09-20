# WORKER_CORE_V1
from __future__ import annotations

from procrastinate import App, PsycopgConnector

from config import Config

QUEUE_SCHEMA = "worker_queue"

MAINTENANCE_QUEUE = "maintenance"
NOTIFICATIONS_QUEUE = "notifications"
REPORTS_QUEUE = "reports"


def _to_psycopg_conninfo(raw_url: str) -> str:
    """Normalize the application's PostgreSQL URL for psycopg 3."""
    url = str(raw_url or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for background workers.")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://"):]
    return url


connector = PsycopgConnector(
    conninfo=_to_psycopg_conninfo(Config.SQLALCHEMY_DATABASE_URI),
    # Queue SQL is intentionally isolated from public tenant tables.
    kwargs={"options": f"-c search_path={QUEUE_SCHEMA}"},
    min_size=1,
    max_size=5,
)

app = App(
    connector=connector,
    import_paths=[
        "workers.tasks.core",
        "workers.tasks.handshake",
        "workers.tasks.session_monitor",
        "workers.tasks.integrity",
        "workers.tasks.reports",
        "workers.tasks.maintenance",
        "workers.tasks.live_stock",
    ],
    worker_defaults={
        "concurrency": 4,
        "delete_jobs": "never",
        "shutdown_graceful_timeout": 60,
    },
)
