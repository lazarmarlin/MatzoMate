"""
logconfig.py — one place that decides what reaches the terminal.

Debug ON  (DEBUG=1 in .env, or --debug on the command line):
    full step-by-step output (INFO and above) from every module.
Debug OFF (default):
    only warnings and errors.

Usage:
    from logconfig import setup_logging, debug_enabled
    setup_logging()
"""

import logging
import os
import sys

_TRUTHY = ("1", "true", "yes", "on")


def debug_enabled(argv=None):
    argv = sys.argv if argv is None else argv
    if "--debug" in argv:
        return True
    return os.getenv("DEBUG", "0").strip().lower() in _TRUTHY


def setup_logging(argv=None):
    debug = debug_enabled(argv)
    logging.basicConfig(
        level=logging.INFO if debug else logging.WARNING,
        format="%(asctime)s [%(threadName)s] %(name)s %(levelname)s — %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    # Third-party libraries log every HTTP request at INFO; keep them quiet.
    for noisy in ("httpx", "httpcore", "urllib3", "openai", "selenium", "asyncio",
                  "primp", "ddgs", "duckduckgo_search", "hpack", "h2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return debug