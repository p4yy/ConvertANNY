"""Locate and invoke a requested Windows Explorer context-menu command."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path


def _normalize(label: str) -> str:
    return " ".join(str(label or "").replace("&", "").casefold().split())


def invoke(paths, preferred=(), exact=(), *, windows: bool, shell_factory=None,
           initialize=None, log=lambda message: None) -> bool:
    if not windows:
        return False
    items = [Path(value) for value in paths if value]
    if not items:
        return False
    if shell_factory is None or initialize is None:
        import pythoncom
        import win32com.client
        initialize = initialize or pythoncom.CoInitialize
        shell_factory = shell_factory or (lambda: win32com.client.Dispatch("Shell.Application"))
    try:
        initialize()
    except Exception:
        pass
    groups = defaultdict(list)
    for item in items:
        groups[str(item.parent)].append(item.name)
    shell = shell_factory()
    started = False
    for folder, names in groups.items():
        namespace = shell.Namespace(folder)
        if namespace is None:
            continue
        if len(names) == 1:
            item = namespace.ParseName(names[0])
            verbs = item.Verbs() if item is not None else None
        else:
            selection = namespace.Items()
            selection.Filter(0xE0, ";".join(names))
            verbs = selection.Verbs()
        if verbs is None:
            continue
        choices = []
        for index in range(verbs.Count):
            command = verbs.Item(index)
            choices.append((command, _normalize(command.Name)))
        command = None
        for phrase in preferred:
            normalized = _normalize(phrase)
            command = next((candidate for candidate, label in choices if normalized in label), None)
            if command is not None:
                break
        if command is None:
            accepted = {_normalize(label) for label in exact}
            command = next((candidate for candidate, label in choices if label in accepted), None)
        if command is None:
            log("shell verbs: " + ", ".join(label for _, label in choices if label))
            continue
        log(f"shell verb: {command.Name} on {len(names)} item(s)")
        command.DoIt()
        started = True
    return started
