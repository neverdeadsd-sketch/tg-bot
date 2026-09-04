#!/usr/bin/env python3
"""Entry point: python run.py <command> ..."""

import sys

# Checked before importing the package: config.py uses tomllib (3.11+), and a
# bare ModuleNotFoundError from three imports deep is a confusing way to learn
# your interpreter is too old.
if sys.version_info < (3, 11):
    raise SystemExit(
        f"tgnames needs Python 3.11 or newer, this one is "
        f"{sys.version.split()[0]} ({sys.executable}).\n"
        f"Install a newer Python from https://www.python.org/downloads/ and "
        f"create the virtualenv with it."
    )

from tgnames.cli import main  # noqa: E402  (must follow the version check)

if __name__ == "__main__":
    sys.exit(main())
