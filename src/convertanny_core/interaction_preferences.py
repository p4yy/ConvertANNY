"""Read and normalize the settings that control ConvertANNY's file orbit."""
from __future__ import annotations


class InteractionPreferences:
    """A small boundary between persisted settings and keyboard/mouse behavior."""

    MODES = ("convert", "tool", "action")
    DEFAULT_KEYS = {"convert": "Shift", "tool": "Ctrl", "action": "Alt"}
    TRIGGERS = frozenset(("drag", "hover", "select"))

    def __init__(self, read_value):
        self._read = read_value

    def mode_keys(self) -> dict[str, str]:
        return {mode: self._read(f"keys/{mode}", self.DEFAULT_KEYS[mode]) for mode in self.MODES}

    def trigger(self) -> str:
        value = self._read("trigger_mode", "drag")
        return value if value in self.TRIGGERS else "drag"

    def preview_key(self) -> str:
        value = self._read("keys/peek", None)
        if value is None:
            value = "Space" if self._read("peek", "true") == "true" else "None"
        return value

    def preview_held(self) -> bool:
        return self._read("peek_hold", "false") == "true"

    @staticmethod
    def label(spec: str, translate) -> str:
        parts = (part for part in (spec or "None").split("+") if part)
        return " + ".join(translate(part) for part in parts) or translate("None")
