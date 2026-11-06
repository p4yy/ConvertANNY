"""Pins how user presets/chains become engine Ops (id, label, handler, group, multi, hint)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine


def check_kinds_map_to_handlers():
    for kind, fn, multi in (("image", engine.image_preset, False), ("video", engine.video_preset, False),
                            ("chain", engine.run_chain, True)):
        op = engine.custom_op({"kind": kind, "name": "Mine", "uid": "u1", "hint": "h"}, "Group")
        assert (op.id, op.label, op.fn, op.group, op.multi, op.hint) == \
            ("custom:u1", "★ Mine", fn, "Group", multi, "h"), op


def check_defaults():
    op = engine.custom_op({"kind": "image"}, "G")
    assert op.id == "custom:Preset" and op.label == "★ Preset" and op.hint == ""
    op = engine.custom_op({"kind": "video", "name": "", "uid": ""}, "G")
    assert op.id == "custom:" and op.label == "★ Preset"   # an explicit empty uid is kept as given
    op = engine.custom_op({"kind": "video", "name": None}, "G")
    assert op.id == "custom:Preset" and op.label == "★ Preset"   # missing uid falls back to the display name
    op = engine.custom_op({"kind": "chain", "name": "N"}, "G")
    assert op.id == "custom:N"


def check_unknown_kind():
    for spec in ({}, {"kind": "audio"}, {"kind": None}):
        try:
            engine.custom_op(spec, "G")
        except engine.ConversionError as exc:
            assert str(exc) == "Unknown custom slice"
        else:
            raise AssertionError(spec)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("check_"):
            f()
            print("ok", n)
