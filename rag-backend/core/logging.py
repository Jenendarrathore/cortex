import logging

from core.config import settings

_configured = False


def configure_logging() -> None:
    """Configure root logging once. Idempotent."""
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
