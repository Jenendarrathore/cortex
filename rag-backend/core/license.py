import asyncio
import hashlib
import os
import sys

import httpx

from core.logging import get_logger

logger = get_logger(__name__)


def _machine_id() -> str:
    """LICENSE_MACHINE_ID env (set in docker-compose) or hostname hash."""
    raw = os.getenv("LICENSE_MACHINE_ID") or os.uname().nodename
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def validate_license(license_key: str, license_server: str) -> None:
    """Boot check — called once at startup. Exits process if invalid."""
    if not license_key:
        logger.error("LICENSE_KEY not set — cannot start")
        sys.exit(1)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{license_server}/validate",
                json={"license_key": license_key, "machine_id": _machine_id()},
            )
        data = resp.json()
    except Exception as e:
        logger.error("License server unreachable at boot: %s — cannot start", e)
        sys.exit(1)

    if not data.get("valid"):
        logger.error("License invalid: %s — cannot start", data.get("reason", "unknown"))
        sys.exit(1)

    logger.info("License valid — expires %s", data.get("expires", "unknown"))


async def periodic_license_check(
    license_key: str,
    license_server: str,
    interval_hours: int = 24,
) -> None:
    """Background task — re-validates every interval_hours.
    Unreachable server: warns and retries next interval (network blip shouldn't kill prod).
    Explicit invalid/revoked response: shuts down immediately.
    """
    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{license_server}/validate",
                    json={"license_key": license_key, "machine_id": _machine_id()},
                )
            data = resp.json()
            if not data.get("valid"):
                logger.error(
                    "License expired or revoked: %s — shutting down",
                    data.get("reason", "unknown"),
                )
                sys.exit(1)
            logger.info("License re-validated — expires %s", data.get("expires", "unknown"))
        except httpx.HTTPError as e:
            logger.warning("License server unreachable: %s — retrying in %sh", e, interval_hours)
        except Exception as e:
            logger.warning("License re-check failed: %s — retrying in %sh", e, interval_hours)
