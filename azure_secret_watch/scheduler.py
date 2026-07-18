"""Internal scheduler used when RUN_MODE=loop (the default).

For RUN_MODE=once, skip this entirely and call app.run_once() directly —
that mode is meant for callers that already have their own scheduler
(host cron, systemd timer, Kubernetes CronJob, etc.).
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone

from croniter import croniter

from .app import run_once
from .config import Config

logger = logging.getLogger(__name__)


class _Stop(Exception):
    pass


def _install_signal_handlers() -> None:
    def _handler(signum, _frame):
        raise _Stop()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def run_loop(config: Config) -> None:
    _install_signal_handlers()
    if not croniter.is_valid(config.cron_schedule):
        raise ValueError(f"CRON_SCHEDULE is not a valid cron expression: {config.cron_schedule!r}")

    logger.info("Starting azure-secret-watch in loop mode (schedule: %s)", config.cron_schedule)
    try:
        if config.run_scan_on_startup:
            logger.info("Running an initial scan on startup (RUN_SCAN_ON_STARTUP=true)")
            try:
                run_once(config)
            except Exception:
                logger.exception("Initial startup scan failed; will retry at next scheduled run")

        while True:
            now = datetime.now(timezone.utc)
            next_run = croniter(config.cron_schedule, now).get_next(datetime)
            sleep_seconds = max(0.0, (next_run - now).total_seconds())
            logger.info("Next scan scheduled at %s (in %.0fs)", next_run.isoformat(), sleep_seconds)
            _sleep_interruptibly(sleep_seconds)

            try:
                run_once(config)
            except Exception:
                logger.exception("Scan run failed; will retry at the next scheduled time")
    except _Stop:
        logger.info("Received stop signal, shutting down")


def _sleep_interruptibly(seconds: float) -> None:
    # Sleep in short increments so a signal is handled promptly rather than
    # waiting out a very long interval.
    remaining = seconds
    chunk = 5.0
    while remaining > 0:
        time.sleep(min(chunk, remaining))
        remaining -= chunk
