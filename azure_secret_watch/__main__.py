from __future__ import annotations

import argparse
import logging
import sys
import threading

from . import settings
from .config import Config


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="azure-secret-watch")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan and exit, regardless of RUN_MODE.",
    )
    args = parser.parse_args(argv)

    config = Config.from_env()
    _configure_logging(config.log_level)
    settings.bootstrap(config)

    if args.once or config.run_mode == "once":
        from .app import run_once

        run_once(config)
        return 0

    if config.web_ui.enabled:
        from .web import start_server

        threading.Thread(target=start_server, args=(config,), daemon=True, name="web-ui").start()

    from .scheduler import run_loop

    run_loop(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
