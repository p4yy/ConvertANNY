"""ConvertANNY-authored image operations using Pillow as a codec backend."""

from __future__ import annotations

from pathlib import Path
import io
from contextlib import contextmanager

from PIL import Image, ImageOps

from .model import CancelToken, ConversionError
from .paths import OutputPolicy, atomic_write


FORMATS = {
    "jpg": ("JPEG", "jpg"),
    "jpeg": ("JPEG", "jpg"),
    "png": ("PNG", "png"),
    "webp": ("WEBP", "webp"),
    "bmp": ("BMP", "bmp"),
    "tif": ("TIFF", "tiff"),
    "tiff": ("TIFF", "tiff"),
    "gif": ("GIF", "gif"),
    "ico": ("ICO", "ico"),
    "avif": ("AVIF", "avif"),
    "heic": ("HEIF", "heic"),
    "heif": ("HEIF", "heic"),
}


def supported_formats() -> tuple[str, ...]:
    """Return codecs available in the installed Pillow build."""
    Image.init()
    return tuple(ext for ext, (fmt, _) in FORMATS.items() if fmt in Image.SAVE)


def _flatten(image: Image.Image, background=(255, 255, 255)) -> Image.Image:
    rgba = image.convert("RGBA")
    canvas = Image.new("RGB", rgba.size, background)
    canvas.paste(rgba, mask=rgba.getchannel("A"))
    return canvas


@contextmanager
def _image_source(source: Path):
    """Open raster formats and render SVG input with explicit resource ownership."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    if source.suffix.lower() == ".svg":
        try:
            import pymupdf
        except ImportError as exc:
            raise ConversionError("SVG rendering requires the bundled PDF engine") from exc
        import io
        with pymupdf.open(str(source)) as document:
            if not document.page_count:
                raise ConversionError("The SVG has no drawable page")
            pixmap = document[0].get_pixmap(dpi=192, alpha=True)
        with Image.open(io.BytesIO(pixmap.tobytes("png"))) as raster:
            yield raster
    else:
        with Image.open(source) as raster:
            yield raster


def _open_image(source: Path) -> Image.Image:
    with _image_source(source) as raster:
        return ImageOps.exif_transpose(raster.copy())


def convert_image(
    source: str | Path,
    target_format: str,
    *,
    quality: int = 90,
    max_side: int = 0,
    strip_metadata: bool = True,
    strip_icc: bool = False,
    policy: OutputPolicy | None = None,
    token: CancelToken | None = None,
) -> Path:
    """Convert a raster image, correcting EXIF orientation and preserving animation where possible."""
    source = Path(source)
    target_format = target_format.lower().lstrip(".")
    Image.init()
    try:
        pil_format, extension = FORMATS[target_format]
    except KeyError as exc:
        raise ConversionError(f"Unsupported image output: {target_format}") from exc
    if pil_format not in Image.SAVE:
        raise ConversionError(f"This Pillow build cannot write {target_format.upper()} files")
    if not source.is_file():
        raise ConversionError(f"File not found: {source}")
    quality = max(1, min(100, int(quality)))
    max_side = max(0, int(max_side))
    destination = (policy or OutputPolicy()).destination(source, extension)

    def write(temp: Path) -> None:
        if token:
            token.check()
        try:
            with _image_source(source) as opened:
                def prepare(frame):
                    result = ImageOps.exif_transpose(frame.copy())
                    if max_side:
                        result.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
                    if pil_format == 'JPEG':
                        result = _flatten(result)
                    return result

                metadata = {}
                if not strip_metadata and pil_format in ('JPEG', 'PNG', 'WEBP', 'AVIF', 'HEIF'):
                    exif = ImageOps.exif_transpose(opened).getexif()
                    if exif:
                        metadata['exif'] = exif.tobytes()
                if not strip_icc and opened.info.get('icc_profile'):
                    metadata['icc_profile'] = opened.info['icc_profile']
                frame_count = int(getattr(opened, "n_frames", 1))
                is_animated = frame_count > 1 and pil_format in ("GIF", "WEBP", "AVIF", "PNG", "TIFF") and pil_format in Image.SAVE_ALL
                frames: list[Image.Image] = []
                durations: list[int] = []
                if is_animated:
                    for index in range(frame_count):
                        if token:
                            token.check()
                        opened.seek(index)
                        frame = prepare(opened)
                        frames.append(frame)
                        durations.append(int(opened.info.get("duration", 100)))
                        if token:
                            token.report((index + 1) / frame_count)
                    first, tail = frames[0], frames[1:]
                    options = {"save_all": True, "append_images": tail, "duration": durations,
                               "loop": int(opened.info.get("loop", 0))}
                    if pil_format == "WEBP":
                        options.update(lossless=False, quality=quality, method=4)
                    elif pil_format == "AVIF":
                        options.update(quality=quality)
                    first.save(temp, format=pil_format, **options, **metadata)
                else:
                    image = prepare(opened)
                    if pil_format == "JPEG":
                        image.save(temp, format=pil_format, quality=quality, optimize=True, **metadata)
                    elif pil_format == "WEBP":
                        image.save(temp, format=pil_format, quality=quality, method=4, **metadata)
                    elif pil_format in ('AVIF', 'HEIF'):
                        image.save(temp, format=pil_format, quality=quality, **metadata)
                    elif pil_format == "ICO":
                        image.thumbnail((256, 256), Image.Resampling.LANCZOS)
                        image.save(temp, format=pil_format, sizes=[image.size])
                    else:
                        image.save(temp, format=pil_format, **metadata)
                    if token:
                        token.report(1.0)
        except (OSError, ValueError) as exc:
            raise ConversionError(f"Could not convert {source.name}: {exc}") from exc
        finally:
            for frame in locals().get("frames", []):
                try:
                    frame.close()
                except Exception:
                    pass

    return atomic_write(destination, write, token)


def resize_image(
    source: str | Path,
    width: int,
    height: int,
    *,
    fit: str = "contain",
    policy: OutputPolicy | None = None,
    token: CancelToken | None = None,
) -> Path:
    """Resize within an explicit box while preserving the source format."""
    source = Path(source)
    width, height = int(width), int(height)
    if width < 1 or height < 1 or width > 32768 or height > 32768:
        raise ConversionError("Image dimensions must be between 1 and 32768 pixels")
    if fit not in ("contain", "cover", "stretch"):
        raise ConversionError("Fit must be contain, cover or stretch")
    image = _open_image(source)
    image_format = (Image.registered_extensions().get(source.suffix.lower()) or "PNG").upper()
    if fit == "contain":
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
    elif fit == "cover":
        image = ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS)
    else:
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    extension = Image.registered_extensions().get("." + source.suffix.lower().lstrip("."), "PNG")
    if extension not in Image.SAVE:
        extension = image_format
    ext = {"JPEG": "jpg", "TIFF": "tiff"}.get(extension, extension.lower())
    destination = (policy or OutputPolicy(suffix="-resized")).destination(source, ext)
    if token:
        token.check()
    return atomic_write(destination, lambda temp: image.save(temp, format=extension), token)


def resize_preset_image(source: str | Path, choice: str, *, policy: OutputPolicy | None = None,
                        token: CancelToken | None = None) -> Path:
    """Implement the workspace's named resize presets with bounded output sizing."""
    source = Path(source)
    choice = str(choice or "50%").strip()
    try:
        image = _open_image(source)
        if choice.startswith("<"):
            limit = (1024 if "MB" in choice.upper() else 500) * 1024
            alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
            output_format, extension = ("WEBP", "webp") if alpha else ("JPEG", "jpg")
            working = image.convert("RGBA") if alpha else _flatten(image)
            for _ in range(16):
                if token:
                    token.check()
                for quality in (90, 82, 74, 66, 58, 50, 42, 34):
                    buffer = io.BytesIO()
                    if output_format == "JPEG":
                        working.save(buffer, format=output_format, quality=quality, optimize=True, progressive=True)
                    else:
                        working.save(buffer, format=output_format, quality=quality, method=4)
                    if buffer.tell() <= limit:
                        destination = (policy or OutputPolicy(suffix=" resized")).destination(source, extension)
                        return atomic_write(destination, lambda temp: temp.write_bytes(buffer.getvalue()), token)
                if max(working.size) <= 1:
                    break
                working = working.resize((max(1, int(working.width * .8)), max(1, int(working.height * .8))), Image.Resampling.LANCZOS)
            raise ConversionError(f"Could not reduce {source.name} below the requested file size")
        if choice.endswith("%"):
            try:
                factor = float(choice[:-1]) / 100
            except ValueError as exc:
                raise ConversionError("Enter a valid resize percentage") from exc
            if not 0 < factor <= 10:
                raise ConversionError("Resize percentage must be greater than 0 and at most 1000")
            width, height = max(1, round(image.width * factor)), max(1, round(image.height * factor))
        elif "×" in choice:
            try:
                width, height = (int(value) for value in choice.replace(" ", "").split("×"))
            except ValueError as exc:
                raise ConversionError("Enter a valid width × height") from exc
            if not (1 <= width <= 32768 and 1 <= height <= 32768):
                raise ConversionError("Image dimensions must be between 1 and 32768 pixels")
            image = ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS)
        else:
            try:
                side = int(choice.split()[0])
            except (ValueError, IndexError) as exc:
                raise ConversionError("Choose a supported image size") from exc
            if not 1 <= side <= 32768:
                raise ConversionError("Image size must be between 1 and 32768 pixels")
            if max(image.size) > side:
                image.thumbnail((side, side), Image.Resampling.LANCZOS)
            width, height = image.size
        if "×" not in choice:
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        source_format = Image.registered_extensions().get(source.suffix.lower(), "PNG")
        extension = {"JPEG": "jpg", "TIFF": "tiff", "HEIF": "heic"}.get(source_format, source_format.lower())
        if source_format not in Image.SAVE or source_format in ("PDF", "ICO", "ICNS"):
            source_format, extension = "PNG", "png"
        if source_format == "JPEG" and image.mode not in ("RGB", "L"):
            image = _flatten(image)
        destination = (policy or OutputPolicy(suffix=" resized")).destination(source, extension)
        options = {"quality": 92, "optimize": True} if source_format == "JPEG" else {}
        return atomic_write(destination, lambda temp: image.save(temp, format=source_format, **options), token)
    except (OSError, ValueError) as exc:
        raise ConversionError(f"Could not resize {source.name}: {exc}") from exc


def transform_image(source: str | Path, operation: str, *, policy: OutputPolicy | None = None,
                    token: CancelToken | None = None) -> Path:
    """Apply a small, deterministic image edit without changing the UI contract."""
    source = Path(source)
    if operation not in ("rotate", "flip", "grayscale", "strip-metadata"):
        raise ConversionError(f"Unsupported image operation: {operation}")
    try:
        Image.init()
        with _image_source(source) as opened:
            image = ImageOps.exif_transpose(opened.copy())
            source_format = (opened.format or "PNG").upper()
            if operation == "rotate":
                image = image.rotate(-90, expand=True)
                suffix = " rotated"
            elif operation == "flip":
                image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                suffix = " flipped"
            elif operation == "grayscale":
                if image.mode in ("RGBA", "LA"):
                    alpha = image.getchannel("A")
                    image = ImageOps.grayscale(image).convert("RGBA")
                    image.putalpha(alpha)
                    alpha.close()
                else:
                    image = ImageOps.grayscale(image)
                suffix = " grayscale"
            else:
                clean = Image.new(image.mode, image.size)
                if image.mode == "P":
                    clean.putdata(list(image.getdata()))
                    palette = image.getpalette()
                    if palette:
                        clean.putpalette(palette)
                else:
                    clean.paste(image)
                image.close()
                image = clean
                suffix = " clean"
            if token:
                token.check()
            extension = {"JPEG": "jpg", "TIFF": "tiff", "HEIF": "heic"}.get(
                source_format, source_format.lower())
            if source_format not in Image.SAVE:
                raise ConversionError(f"Cannot write the original image format: {source_format}")
            destination = (policy or OutputPolicy(suffix=suffix)).destination(source, extension)
            options = {}
            if source_format == "JPEG":
                if image.mode not in ("RGB", "L"):
                    rgba = image.convert("RGBA")
                    flattened = Image.new("RGB", rgba.size, (255, 255, 255))
                    flattened.paste(rgba, mask=rgba.getchannel("A"))
                    rgba.close()
                    image.close()
                    image = flattened
                options.update(quality=92, optimize=True)
            elif source_format == "WEBP":
                options.update(quality=90, method=4)
            elif source_format == "TIFF":
                options.update(compression="tiff_lzw")
            return atomic_write(destination, lambda temp: image.save(temp, format=source_format, **options), token)
    except (OSError, ValueError) as exc:
        raise ConversionError(f"Could not edit {source.name}: {exc}") from exc


def compress_image(source: str | Path, *, policy: OutputPolicy | None = None,
                   token: CancelToken | None = None) -> Path:
    """Reduce image size with format-aware settings and an atomic output publish."""
    source = Path(source)
    Image.init()
    try:
        with _image_source(source) as opened:
            image = ImageOps.exif_transpose(opened.copy())
            source_format = (opened.format or "PNG").upper()
            has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
            if source_format in ("PNG", "GIF", "BMP", "TIFF") and has_alpha:
                rgba = image.convert("RGBA")
                image.close()
                image = rgba.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
                target_format, extension, options = "PNG", "png", {"optimize": True}
            elif source_format == "WEBP":
                target_format, extension, options = "WEBP", "webp", {"quality": 72, "method": 4}
            else:
                if max(image.size) > 3000:
                    image.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
                image = _flatten(image)
                target_format, extension, options = "JPEG", "jpg", {"quality": 72, "optimize": True, "progressive": True}
            if token:
                token.check()
            destination = (policy or OutputPolicy(suffix=" compressed")).destination(source, extension)
            return atomic_write(destination, lambda temp: image.save(temp, format=target_format, **options), token)
    except (OSError, ValueError) as exc:
        raise ConversionError(f"Could not compress {source.name}: {exc}") from exc


def crop_resize_image(source: str | Path, parameters: dict, *, policy: OutputPolicy | None = None,
                      token: CancelToken | None = None, background_remover=None) -> Path:
    """Apply the crop-editor's normalized transform payload to a raster image."""
    source = Path(source)
    Image.init()
    try:
        image = _open_image(source)
        if parameters.get("remove_bg"):
            if background_remover is None:
                raise ConversionError("Background removal is unavailable")
            image = background_remover(image)
        rotation = int(parameters.get("rotate", 0)) % 360
        if rotation not in (0, 90, 180, 270):
            raise ConversionError("Rotation must be 0, 90, 180 or 270 degrees")
        if rotation:
            image = image.rotate(-rotation, expand=True)
        if parameters.get("flip_h"):
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if parameters.get("flip_v"):
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        box = parameters.get("box")
        if box:
            left, top, right, bottom = [int(round(value)) for value in box]
            left, top = max(0, left), max(0, top)
            right, bottom = min(image.width, right), min(image.height, bottom)
            if right <= left or bottom <= top:
                raise ConversionError("Crop rectangle has no area")
            image = image.crop((left, top, right, bottom))
        output_size = parameters.get("size")
        if output_size:
            width, height = [int(value) for value in output_size]
            if not 1 <= width <= 32768 or not 1 <= height <= 32768:
                raise ConversionError("Image dimensions must be between 1 and 32768 pixels")
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        if token:
            token.check()
        extension = str(parameters.get("format") or source.suffix.lower().lstrip("."))
        extension = {"jpeg": "jpg", "tif": "tiff", "heif": "heic"}.get(extension.lower(), extension.lower())
        if extension not in FORMATS or extension not in supported_formats():
            extension = "png"
        image_format, output_extension = FORMATS[extension]
        if image_format == "JPEG" and image.mode not in ("RGB", "L"):
            image = _flatten(image)
        destination = (policy or OutputPolicy(suffix=" edited")).destination(source, output_extension)
        options = {"quality": 92, "optimize": True} if image_format == "JPEG" else {}
        return atomic_write(destination, lambda temp: image.save(temp, format=image_format, **options), token)
    except (OSError, ValueError) as exc:
        raise ConversionError(f"Could not edit {source.name}: {exc}") from exc


def watermark_image(source: str | Path, text: str, position: str = "Bottom right", *,
                    policy: OutputPolicy | None = None, token: CancelToken | None = None) -> Path:
    """Add a readable text mark to a raster image without changing its dimensions."""
    source = Path(source)
    text = str(text or "").strip()
    if not text:
        raise ConversionError("Type the watermark text")
    if position not in ("Bottom right", "Bottom left", "Center", "Tiled"):
        raise ConversionError("Choose a watermark position")
    try:
        from PIL import ImageDraw, ImageFont
        Image.init()
        with _image_source(source) as opened:
            image = ImageOps.exif_transpose(opened.convert("RGBA"))
        width, height = image.size
        size = max(12, int(min(width, height) * (0.045 if position == "Tiled" else 0.05)))
        font_path = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "Inter-Regular.ttf"
        font = ImageFont.truetype(str(font_path), size) if font_path.is_file() else ImageFont.load_default()
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=max(1, size // 16))
        text_width, text_height = right - left, bottom - top
        if position == "Tiled":
            tile = Image.new("RGBA", (text_width + size * 3, text_height + size * 3), (0, 0, 0, 0))
            ImageDraw.Draw(tile).text((size, size), text, font=font, fill=(255, 255, 255, 95),
                                      stroke_width=max(1, size // 18), stroke_fill=(0, 0, 0, 50))
            tile = tile.rotate(30, expand=True, resample=Image.Resampling.BICUBIC)
            for y in range(-tile.height // 2, height, tile.height):
                for x in range(-tile.width // 2, width, tile.width):
                    layer.paste(tile, (x, y), tile)
        else:
            margin = int(min(width, height) * 0.03)
            x = (width - text_width) // 2 - left if position == "Center" else (margin - left if position == "Bottom left" else width - text_width - margin - left)
            y = (height - text_height) // 2 - top if position == "Center" else height - text_height - margin - top
            draw.text((x, y), text, font=font, fill=(255, 255, 255, 170),
                      stroke_width=max(1, size // 16), stroke_fill=(0, 0, 0, 110))
        image.alpha_composite(layer)
        if token:
            token.check()
        format_name = Image.registered_extensions().get(source.suffix.lower(), "PNG")
        extension = {"JPEG": "jpg", "TIFF": "tiff"}.get(format_name, format_name.lower())
        if format_name not in Image.SAVE or format_name in ("PDF", "ICO", "ICNS"):
            format_name, extension = "PNG", "png"
        if format_name == "JPEG":
            flattened = Image.new("RGB", image.size, "white")
            flattened.paste(image, mask=image.getchannel("A"))
            image = flattened
        destination = (policy or OutputPolicy(suffix=" watermarked")).destination(source, extension)
        return atomic_write(destination, lambda temp: image.save(temp, format=format_name, quality=92, optimize=True)
                            if format_name == "JPEG" else image.save(temp, format=format_name), token)
    except (OSError, ValueError) as exc:
        raise ConversionError(f"Could not watermark {source.name}: {exc}") from exc


def enhance_image(source: str | Path, operation: str, *, policy: OutputPolicy | None = None,
                  token: CancelToken | None = None) -> Path:
    """Upscale or sharpen an image with bounded memory use and preserved format."""
    source = Path(source)
    try:
        from PIL import ImageFilter
        Image.init()
        with _image_source(source) as opened:
            image = ImageOps.exif_transpose(opened.copy())
            if image.mode not in ("RGB", "RGBA", "L", "LA"):
                image = image.convert("RGBA")
        if operation == "upscale":
            if image.width * image.height > 40_000_000:
                raise ConversionError("This image is already very large")
            image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
            image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
            suffix = " 2x"
        elif operation == "sharpen":
            image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))
            suffix = " sharpened"
        else:
            raise ConversionError(f"Unsupported image enhancement: {operation}")
        if token:
            token.check()
        format_name = Image.registered_extensions().get(source.suffix.lower(), "PNG")
        extension = {"JPEG": "jpg", "TIFF": "tiff", "HEIF": "heic"}.get(format_name, format_name.lower())
        if format_name not in Image.SAVE or format_name in ("PDF", "ICO", "ICNS"):
            format_name, extension = "PNG", "png"
        if format_name == "JPEG" and image.mode not in ("RGB", "L"):
            rgba = image.convert("RGBA")
            flattened = Image.new("RGB", rgba.size, "white")
            flattened.paste(rgba, mask=rgba.getchannel("A"))
            image = flattened
        destination = (policy or OutputPolicy(suffix=suffix)).destination(source, extension)
        return atomic_write(destination, lambda temp: image.save(temp, format=format_name, quality=92, optimize=True)
                            if format_name == "JPEG" else image.save(temp, format=format_name), token)
    except (OSError, ValueError) as exc:
        raise ConversionError(f"Could not enhance {source.name}: {exc}") from exc
