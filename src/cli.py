"""ConvertANNY command interface for conversion and unattended tools."""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path


def _attach_console():
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        if kernel.AttachConsole(0xFFFFFFFF):
            kernel.SetConsoleOutputCP(65001)
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    except (OSError, AttributeError):
        pass


def _parser():
    parser = argparse.ArgumentParser(prog="convertanny", description="Convert files locally with ConvertANNY.")
    commands = parser.add_subparsers(dest="command")
    listing = commands.add_parser("list", help="Show supported formats and tools for a file")
    listing.add_argument("files", nargs="+")
    conversion = commands.add_parser("convert", help="Convert files to a format")
    conversion.add_argument("files", nargs="+")
    conversion.add_argument("--to", required=True, dest="format")
    tool = commands.add_parser("tool", help="Run a tool by its identifier")
    tool.add_argument("operation")
    tool.add_argument("files", nargs="+")
    for command in (conversion, tool):
        command.add_argument("--out", help="Output directory; defaults to beside each source")
        command.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="Tool parameter; repeat for additional parameters")
    return parser


def _files(patterns):
    result = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern)) if glob.has_magic(pattern) else [pattern]
        if not matches:
            raise ValueError(f"No files matched: {pattern}")
        for match in matches:
            path = Path(match)
            if not path.exists():
                raise ValueError(f"File not found: {match}")
            value = str(path.resolve())
            if value not in result:
                result.append(value)
    return result


def _parameters(operation, assignments):
    parameters = {}
    for name, default in operation.ask or []:
        parameters[name] = default[0] if isinstance(default, (list, tuple)) and default else default
    for assignment in assignments:
        key, separator, value = assignment.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"Expected NAME=VALUE after --set: {assignment}")
        parameters[key.strip()] = value.strip()
    return parameters


def _display_results(outputs):
    for output in outputs:
        if output is None:
            continue
        value = str(output)
        print(value[5:] if value.startswith("info:") else f"Saved: {value}")


def _execute(engine, operation, files, parameters, directory):
    if operation.ui or operation.group == "action":
        raise ValueError(f"{operation.label} requires the application window")
    if operation.model and not engine.model_ready(operation.model):
        raise ValueError(f"Download the required component for {operation.label} in the application first")
    previous_directory = engine.OUTPUT_DIR
    try:
        if directory:
            target = Path(directory).expanduser().resolve()
            target.mkdir(parents=True, exist_ok=True)
            engine.OUTPUT_DIR = str(target)
        else:
            engine.OUTPUT_DIR = None
        token = engine.CancelToken()
        errors = []
        def event(kind, value):
            if kind == "failed":
                errors.append(value)
                print(f"Failed: {value}", file=sys.stderr)
        token.on_path = event
        # Preserve whole selections for merge, archive and other multi-file tools.
        try:
            outputs = engine.run_op(operation, files, parameters, token=token)
        except KeyboardInterrupt:
            token.cancel()
            print("Cancelled", file=sys.stderr)
            return 130
        _display_results(outputs)
        return 1 if errors else 0
    finally:
        engine.OUTPUT_DIR = previous_directory


def main(argv) -> int:
    _attach_console()
    parser = _parser()
    argv = list(argv)
    if argv and argv[0] in ("help", "/?"):
        argv = ["--help"]
    try:
        options = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    if not options.command:
        parser.print_help()
        return 2
    import engine
    try:
        files = _files(options.files)
        if options.command == "list":
            for file in files:
                print(Path(file).name)
                print("Formats: " + ", ".join(operation.id.removeprefix("to_") for operation in engine.conversions([file])))
                print("Tools:")
                for operation in engine.tools([file]):
                    print(f"  {operation.id}: {operation.label}")
            return 0
        if options.command == "convert":
            requested = options.format.lower().lstrip(".")
            operation = next((item for item in engine.conversions(files) if item.id in (requested, "to_" + requested)), None)
        else:
            requested = options.operation.casefold()
            operation = next((item for item in engine.tools(files) if requested in (item.id.casefold(), item.label.rstrip("…").casefold())), None)
        if operation is None:
            raise ValueError(f"Operation unavailable for this selection: {requested}. Use convertanny list to see supported operations.")
        parameters = _parameters(operation, options.set)
        return _execute(engine, operation, files, parameters, options.out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
