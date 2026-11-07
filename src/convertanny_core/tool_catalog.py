"""Build the context-sensitive ConvertANNY file-tools catalogue."""
from __future__ import annotations

from pathlib import Path


def _make(api, identifier, label, function, **options):
    return api["Op"](identifier, label, function, group="tool", **options)


def _image_tools(api, paths):
    n = len(paths)
    tool = lambda *args, **kwargs: _make(api, *args, **kwargs)
    entries = [
        tool("compress", "Compress", api["image_compress"]),
        tool("edit", "Crop & Resize…", api["image_crop_resize"], ui="crop"),
        tool("scan", "Fix alignment…", api["image_scan"],
             ask=[("Corners", "@corners")] if n == 1 else [("Look", api["SCAN_LOOKS"])]),
        tool("rotate", "Rotate 90°", api["image_tool"]("rotated", lambda image, params: image.rotate(-90, expand=True))),
        tool("flip", "Flip", api["image_tool"]("flipped", lambda image, params: image.transpose(0))),
        tool("gray", "Grayscale", api["image_tool"]("gray", lambda image, params:
             image.convert("LA") if image.mode in ("RGBA", "LA") else image.convert("L"))),
        tool("strip", "Strip metadata", api["image_tool"]("clean", api["_strip"])),
        tool("resize", "Resize…", api["image_resize_preset"], ask=[("Output size", api["RESIZE_PRESETS"])]),
        tool("removebg", "Remove background", api["image_remove_bg"], model="isnet"),
        tool("ocr", "Copy text", api["image_ocr"]),
        tool("upscale", "Upscale 2×", api["image_upscale"]),
        tool("sharpen", "Sharpen", api["image_sharpen"]),
        tool("watermark", "Watermark…", api["image_watermark"],
             ask=[("Text", "© " + api["_user_name"]()), ("Position", api["WATERMARK_POSITIONS"])]),
        tool("blurfaces", "Blur faces", api["image_blur_faces"]),
    ]
    if n > 1:
        entries.extend((
            tool("combine_pdf", "Combine PDF", api["images_to_pdf"], multi=True),
            tool("stitch_h", "Stitch side by side", api["images_stitch"]("h"), multi=True),
            tool("stitch_v", "Stitch top to bottom", api["images_stitch"]("v"), multi=True),
            tool("gif", "Make GIF…", api["images_to_gif"], multi=True, ask=[("Seconds per image", "0.5")]),
            tool("cbz", "Make comic (CBZ)", api["images_to_cbz"], multi=True),
        ))
    return entries


def _video_tools(api, paths):
    tool = lambda *args, **kwargs: _make(api, *args, **kwargs)
    entries = [
        tool("compress", "Compress…", api["video_compress"], ask=[("Target size", ["Automatic"] + api["TARGET_SIZES"])]),
        tool("720p", "720p", api["video_scale"](720)),
        tool("trim", "Trim…", api["media_trim"], ask=api["TRIM"]),
        tool("mute", "Mute", api["video_mute"]),
        tool("rotate", "Rotate 90°", api["video_rotate"]),
        tool("snapshot", "Snapshot…", api["video_snapshot"], ask=[("At time", "0:01")]),
        tool("speed", "Speed 2×", api["video_speed2x"]),
        tool("gif", "Make GIF…", api["video_gif_clip"], ask=[("Start", "0:00"), ("End", "0:05")]),
        tool("social", "Crop for social…", api["video_social_crop"], ask=[("Shape", api["SOCIAL_SHAPES"])]),
        tool("ringtone", "Ringtone…", api["ringtone"], ask=[("Clip", "@trim"), ("Format", api["RINGTONE_FORMATS"])]),
        tool("transcribe", "Transcribe…", api["transcribe"], ask=[("Language", api["TRANSCRIBE_MODES"])], model="whisper-small"),
    ]
    path = paths[0] if len(paths) == 1 else None
    if path and api["_side_subtitles"](path):
        subtitles = api["_side_subtitles"](path)
        entries.extend((
            tool("burn", "Burn subtitles", api["burn_subtitles"], multi=True, hint=Path(subtitles[0]).name),
            tool("muxsubs", "Add subtitles to MKV", api["mux_subtitles"], multi=True,
                 hint=", ".join(Path(item).name for item in subtitles)),
        ))
    if path:
        tracks = [track for track in api["subtitle_streams"](path) if track["text"]]
        if tracks:
            languages = ", ".join(track["lang"] or "?" for track in tracks)
            entries.append(tool("extractsubs", "Extract subtitles (SRT)", api["extract_subtitles"], hint=languages))
    if len(paths) > 1:
        entries.append(tool("merge", "Merge", api["media_merge"], multi=True))
    return entries


def _pdf_tools(api, paths):
    n = len(paths)
    tool = lambda *args, **kwargs: _make(api, *args, **kwargs)
    entries = [
        tool("compress", "Compress", api["pdf_compress"]),
        tool("split", "Split pages", api["pdf_split"]),
        tool("pages", "Extract pages…", api["pdf_extract_pages"], ask=[("Pages (e.g. 1-3,5)", "1")]),
        tool("rotate", "Rotate 90°", api["pdf_rotate"]),
        tool("images", "Extract images", api["pdf_extract_images"]),
        tool("protect", "Password…", api["pdf_protect"], ask=[("Password", "")]),
        tool("arrange", "Arrange pages…", api["pdf_arrange"], multi=True, ask=[("Layout", "@pages")]),
        tool("numbers", "Page numbers…", api["pdf_page_numbers"],
             ask=[("Position", api["PAGE_NUMBER_POSITIONS"]), ("Style", api["PAGE_NUMBER_STYLES"])]),
        tool("watermark", "Watermark…", api["pdf_watermark"], multi=True, ask=[("Watermark", "@watermark")]),
        tool("sign", "Sign…", api["pdf_sign"], ask=[("Sign", "@sign")]),
        tool("gray", "Grayscale", api["pdf_grayscale"]),
        tool("count", "Word count", api["count_words"]),
    ]
    if n == 1 and api["pdf_is_encrypted"](paths[0]):
        entries.insert(0, tool("unlock", "Unlock…", api["pdf_unlock"], ask=[("Password", "")]))
    if n > 1:
        entries.append(tool("merge", "Merge", api["pdf_merge"], multi=True))
    return entries


def tools_for(paths, api):
    """Return tools valid for the selected inputs, preserving each operation's stable ID."""
    selected = list(paths)
    if not selected:
        return []
    category = api["category_of"](selected)
    count = len(selected)
    tool = lambda *args, **kwargs: _make(api, *args, **kwargs)
    operations = []

    if category == "image":
        operations = _image_tools(api, selected)
    elif category == "video":
        operations = _video_tools(api, selected)
    elif category == "audio":
        operations = [
            tool("compress", "Compress", api["audio_compress"]),
            tool("trim", "Trim…", api["media_trim"], ask=api["TRIM"]),
            tool("normalize", "Normalize", api["audio_normalize"]),
            tool("mono", "Mono", api["audio_mono"]),
            tool("fade", "Fade in/out", api["audio_fade"]),
            tool("ringtone", "Ringtone…", api["ringtone"], ask=[("Clip", "@trim"), ("Format", api["RINGTONE_FORMATS"])]),
            tool("transcribe", "Transcribe…", api["transcribe"], ask=[("Language", api["TRANSCRIBE_MODES"])], model="whisper-small"),
        ]
        if count > 1:
            operations.append(tool("merge", "Merge", api["media_merge"], multi=True))
    elif category == "pdf":
        operations = _pdf_tools(api, selected)
        if count > 1:
            operations.append(tool("merge", "Merge", api["pdf_merge"], multi=True))
    elif category == "mixed" and all(api["EXT_CATEGORY"].get(api["ext_of"](path)) in ("pdf", "image") for path in selected):
        category_names = sorted(api["EXT_CATEGORY"].get(api["ext_of"](path)) for path in selected)
        if count == 2 and category_names == ["image", "pdf"]:
            operations.extend((
                tool("sign", "Sign…", api["pdf_sign"], multi=True, ask=[("Sign", "@sign")]),
                tool("logo", "Watermark with logo…", api["pdf_watermark"], multi=True, ask=[("Watermark", "@watermark")]),
            ))
        if count > 1:
            operations.extend((tool("merge", "Merge", api["pdf_merge"], multi=True),
                               tool("arrange", "Arrange pages…", api["pdf_arrange"], multi=True,
                                    ask=[("Layout", "@pages")])) )
    elif category == "comic":
        operations.append(tool("pages", "Extract pages", api["comic_extract"]))
    elif category in {"document", "slides", "ebook"}:
        simple = {"txt", "md", "html", "htm", "docx", "odt", "pptx", "epub"}
        if all(api["ext_of"](path) in simple for path in selected):
            operations.append(tool("count", "Word count", api["count_words"]))
    elif category == "archive":
        operations.append(tool("extract", "Extract", api["archive_extract"]))
    elif category == "mixed":
        kinds = [api["EXT_CATEGORY"].get(api["ext_of"](path)) for path in selected]
        if kinds.count("video") == 1 and set(kinds) == {"video", "subtitle"}:
            operations.extend((tool("burn", "Burn subtitles", api["burn_subtitles"], multi=True),
                               tool("muxsubs", "Add subtitles to MKV", api["mux_subtitles"], multi=True)))

    if category == "font":
        operations.append(tool("install", "Install font", api["font_install"]))
    text_types = {"txt", "csv", "tsv", "srt", "ass", "ssa", "vtt", "md", "html", "htm"}
    if all(api["ext_of"](path) in text_types for path in selected):
        operations.append(tool("fixarabic", "Fix Arabic text", api["fix_arabic_text"]))

    if all(api["is_part_file"](path) for path in selected):
        return [tool("join", "Join parts", api["join_parts"], multi=True)]

    if category not in {"archive", "folder", "mixed", "other"}:
        operations.append(tool("zip", "Zip", api["to_zip"], multi=True))
    operations.append(tool("protect_zip", "Zip with password…", api["protect_archive"], multi=True,
                           ask=[("Password", ""), ("Format", api["PROTECT_FORMATS"])]))
    operations.append(tool("splitparts", "Split into parts…", api["split_parts"], multi=True,
                           ask=[("Part size", api["SPLIT_SIZES"])]))
    return operations
