"""Exactly two CLI commands: download and load."""

import argparse
import sys

from .settings import get_settings


def main(argv=None):
    """Validate configuration before starting either operation."""
    parser = argparse.ArgumentParser(prog="python -m comext")
    parser.add_argument("command", choices=("download", "load"))
    args = parser.parse_args(argv)
    try:
        get_settings()
        if args.command == "download":
            from .download import run_download

            failures = run_download()
        else:
            from .load import run_load

            failures = run_load()
        return 1 if failures else 0
    except KeyboardInterrupt:
        print("Interrupted; incomplete work can be retried.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"comext: {exc}", file=sys.stderr)
        return 1
