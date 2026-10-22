"""Command line: ``python -m tak <command>``.

Commands:

* ``studio [--port N] [--no-open]``  launch the local Studio
* ``setup ...``                       install MPFB and asset packs (avatar pipeline)
* ``build ...``                       build avatars from their specifications (avatar pipeline)
* ``check``                           report tool availability as JSON (avatar pipeline)
* ``demo [--port N] [--no-open]``     launch the talking-avatar demo page (``/talk/``)
* ``speech setup|status|voices|say``  optional Kokoro speech (``tak.speech``)

The pipeline commands are dispatched lazily to ``tak.pipeline.cli`` so the
Studio starts even when the pipeline is not present.
"""

from __future__ import annotations

import argparse
import importlib
import sys

from . import __version__

PIPELINE_COMMANDS = {"setup": "setup_main", "build": "build_main", "check": "check_main"}
PIPELINE_MODULES = ("tak.pipeline", "tak.pipeline.cli")

USAGE = """usage: python -m tak <command> [options]

commands:
  studio    launch the local Studio web app (--port N, --no-open)
  setup     install MPFB and the CC0 asset packs for headless builds
  build     build avatars (<slug> or --all) with headless Blender
  check     print tool availability (Python, Blender, MPFB, packs) as JSON
  demo      launch the talking-avatar demo (same server, opens /talk/)
  speech    optional Kokoro speech: setup, status, voices, say

Run 'python -m tak <command> --help' for command options.
"""


def studio_main(argv: list[str]) -> int:
    from .server import DEFAULT_PORT, serve

    parser = argparse.ArgumentParser(prog="python -m tak studio", description="Launch the local Studio web app.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port on 127.0.0.1 (default {DEFAULT_PORT}; 0 picks a free port)")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    return serve(port=args.port, open_browser=not args.no_open)


def demo_main(argv: list[str]) -> int:
    from .server import DEFAULT_PORT, serve

    parser = argparse.ArgumentParser(prog="python -m tak demo",
                                     description="Launch the talking-avatar demo (the Studio server, opening /talk/).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port on 127.0.0.1 (default {DEFAULT_PORT}; 0 picks a free port)")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    return serve(port=args.port, open_browser=not args.no_open, page="/talk/", label="talking demo")


def pipeline_main(command: str, argv: list[str]) -> int:
    try:
        module = importlib.import_module("tak.pipeline.cli")
    except ModuleNotFoundError as exc:
        if exc.name not in PIPELINE_MODULES:
            raise
        print(f"'python -m tak {command}' needs the avatar pipeline (tak/pipeline/cli.py), "
              "which is not present in this checkout.", file=sys.stderr)
        return 2
    func = getattr(module, PIPELINE_COMMANDS[command], None)
    if func is None:
        print(f"tak.pipeline.cli has no {PIPELINE_COMMANDS[command]}(); cannot run '{command}'.", file=sys.stderr)
        return 2
    result = func(argv)
    return int(result or 0)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE, end="")
        return 0 if argv else 1
    if argv[0] in ("-V", "--version"):
        print(f"talking-avatar-kit {__version__}")
        return 0
    command, rest = argv[0], argv[1:]
    if command == "studio":
        return studio_main(rest)
    if command == "demo":
        return demo_main(rest)
    if command == "speech":
        from .speech.cli import speech_main
        return speech_main(rest)
    if command in PIPELINE_COMMANDS:
        return pipeline_main(command, rest)
    print(f"unknown command: {command}\n", file=sys.stderr)
    print(USAGE, end="", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
