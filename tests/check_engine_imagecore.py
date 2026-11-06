"""Characterization checks for the engine's image core: opening, flattening, saving, stitching, animated GIFs."""
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine
from PIL import Image


def _png(path, size=(40, 30), color=(200, 50, 20, 255), mode="RGBA"):
    Image.new(mode, size, color).save(path)
    return str(path)


def check_open_respects_exif_and_svg():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        img = Image.new("RGB", (40, 20), (1, 2, 3))
        exif = Image.Exif()
        exif[0x0112] = 6                                    # stored rotated: must come back upright (20 wide, 40 tall)
        img.save(d / "r.jpg", exif=exif)
        assert engine.open_image(d / "r.jpg").size == (20, 40)
        plain = engine.open_image(_png(d / "p.png", (12, 7)))
        assert plain.size == (12, 7)
        (d / "s.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="50" height="30">'
                                 '<rect width="50" height="30" fill="red"/></svg>')
        svg = engine.open_image(d / "s.svg")
        assert svg.mode == "RGBA" and svg.size == (134, 80), (svg.mode, svg.size)     # 192 dpi over a 72 dpi page


def check_flatten():
    red = (255, 0, 0)
    rgba = Image.new("RGBA", (2, 1), (0, 255, 0, 255))
    rgba.putpixel((1, 0), (0, 0, 255, 0))
    flat = engine._flatten(rgba)
    assert flat.mode == "RGB" and flat.getpixel((0, 0)) == (0, 255, 0) and flat.getpixel((1, 0)) == (255, 255, 255)
    assert engine._flatten(rgba, red).getpixel((1, 0)) == red
    la = Image.new("LA", (1, 1), (100, 0))
    assert engine._flatten(la, red).getpixel((0, 0)) == red
    pal = Image.new("P", (1, 1))
    pal.info["transparency"] = 0
    assert engine._flatten(pal, red).mode == "RGB"
    assert engine._flatten(Image.new("L", (1, 1), 9)).getpixel((0, 0)) == (9, 9, 9)
    solid = Image.new("RGB", (1, 1), (5, 6, 7))
    assert engine._flatten(solid) is not solid and engine._flatten(solid).getpixel((0, 0)) == (5, 6, 7)


def check_save_formats():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        art = Image.new("RGBA", (30, 20), (255, 0, 0, 0))
        art.putpixel((0, 0), (0, 0, 255, 255))
        for fmt in ("jpg", "png", "webp", "tiff", "bmp", "gif", "pdf", "tga"):
            out = engine.save_image(art, d / f"o.{fmt}", fmt)
            assert out == d / f"o.{fmt}" and out.stat().st_size > 0, fmt
        assert Image.open(d / "o.jpg").mode == "RGB"
        assert Image.open(d / "o.jpg").getpixel((10, 10))[0] > 240                 # transparent became white-ish
        assert Image.open(d / "o.png").mode == "RGBA"
        assert Image.open(d / "o.bmp").mode == "RGB"
        assert (d / "o.pdf").read_bytes()[:4] == b"%PDF"
        weird = Image.new("CMYK", (8, 8))
        engine.save_image(weird, d / "w.png", "png")
        assert Image.open(d / "w.png").mode == "RGBA"
        engine.save_image(Image.new("I;16", (4, 4)), d / "w2.webp", "webp")
        # override replaces defaults
        engine.save_image(Image.new("RGB", (64, 64), (9, 9, 9)), d / "q.jpg", "jpg", quality=5)
        low = (d / "q.jpg").stat().st_size
        engine.save_image(Image.new("RGB", (64, 64), (9, 9, 9)), d / "q2.jpg", "jpg")
        assert low <= (d / "q2.jpg").stat().st_size


def check_icons_are_squared():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        wide = Image.new("RGBA", (60, 20), (255, 0, 0, 255))
        engine.save_image(wide, d / "w.ico", "ico")
        ico = Image.open(d / "w.ico")
        sizes = ico.info["sizes"]
        assert (16, 16) in sizes and max(sizes)[0] <= 64, sizes                     # canvas is 60 wide: bigger sizes are skipped
        ico.close()
        big = Image.new("RGBA", (1200, 600), (0, 255, 0, 255))
        engine.save_image(big, d / "b.icns", "icns")
        assert Image.open(d / "b.icns").size[0] <= 1024


def check_jpeg_name_and_format():
    with tempfile.TemporaryDirectory() as d:
        src = _png(Path(d) / "pic.png", (10, 10))
        out = engine.image_to_jpeg(src, {})
        assert out.name == "pic.jpeg" and Image.open(out).format == "JPEG"


def check_stitch():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        a = _png(d / "a.png", (40, 20), (255, 0, 0, 255))
        b = _png(d / "b.png", (30, 10), (0, 255, 0, 255))
        out = engine.images_stitch("h")([a, b], {})
        assert out.name == "a stitched.jpg", out.name                               # opaque inputs -> JPEG
        w, h = Image.open(out).size
        assert h == 10 and w == 20 + 30, (w, h)                                      # shortest height wins, widths scale
        out2 = engine.images_stitch("v")([a, b], {})
        assert Image.open(out2).size == (30, 15 + 10), Image.open(out2).size         # narrowest width wins
        clear = d / "c.png"
        Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(clear)
        out3 = engine.images_stitch("h")([a, str(clear)], {})
        assert out3.suffix == ".png" and Image.open(out3).mode == "RGBA"             # any transparency -> PNG
        again = engine.images_stitch("h")([a, b], {})
        assert again != out and again.exists()                                       # never overwrites


def check_gif():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        a = _png(d / "a.png", (60, 30), (255, 0, 0, 255))
        b = _png(d / "b.png", (20, 40), (0, 0, 255, 255))
        out = engine.images_to_gif([a, b], {"Seconds per image": "0,25"})
        assert out.name == "a animated.gif"
        gif = Image.open(out)
        assert gif.size == (60, 30) and gif.n_frames == 2 and gif.info["duration"] == 250 and gif.info["loop"] == 0
        gif.seek(1)
        assert gif.size == (60, 30)                                                  # every frame padded to the first's box
        gif.close()
        big = _png(d / "big.png", (2400, 1200))
        assert Image.open(engine.images_to_gif([big], {})).size == (1200, 600)       # capped at 1200 on the long side
        for text, want in (("0", 20), ("99", 30000), ("0.5", 500)):
            g = Image.open(engine.images_to_gif([a], {"Seconds per image": text}))
            assert g.info["duration"] == want, (text, g.info["duration"])
            g.close()
        try:
            engine.images_to_gif([a], {"Seconds per image": "abc"})
        except engine.ConversionError as exc:
            assert str(exc) == "Seconds per image must be a number"
        else:
            raise AssertionError("expected an error")


def check_gif_cancellation():
    # check_cancel() is a no-op without a token; this pins that the loop calls it per frame
    calls = []
    saved = engine.check_cancel
    try:
        engine.check_cancel = lambda: calls.append(1)
        with tempfile.TemporaryDirectory() as d:
            p = _png(Path(d) / "a.png", (8, 8))
            engine.images_to_gif([p, p, p], {})
    finally:
        engine.check_cancel = saved
    assert len(calls) == 3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("check_") and callable(fn):
            fn()
    print("Engine image core passed")
