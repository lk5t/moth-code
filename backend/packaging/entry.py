"""Frozen-executable entry point (PyInstaller).

``moth-backend``              → run the local API server (what the desktop shell launches)
``moth-backend serve …``      → same, with server options
``moth-backend <subcommand>`` → the ``moth`` CLI (used for isolated training/data jobs)
"""

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    args = sys.argv[1:]
    if not args or args[0] == "serve" or args[0].startswith("--port") or args[0].startswith("--home"):
        from moth.server.__main__ import main as serve

        serve(args[1:] if args and args[0] == "serve" else args)
        return 0
    from moth.cli import main as cli

    return cli(args)


if __name__ == "__main__":
    sys.exit(main())
