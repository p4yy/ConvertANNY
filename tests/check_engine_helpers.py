"""Behavioural checks for engine helpers: links, natural sort, sizes, text decoding, formats, models, comics, packing, catalogue."""
import hashlib
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import engine


def check_links_and_sorting():
    for good in ("http://a.b", "HTTPS://x.y/z?q=1", "  https://x.y  "):
        assert engine.is_link(good), good
    for bad in ("", None, "ftp://x", "https://x y", "https://x\ny", "example.com", "see https://x"):
        assert not engine.is_link(bad), bad
    names = ["p10.png", "p2.png", "P1.png", "p1b.png"]
    assert sorted(names, key=engine._natural) == ["P1.png", "p1b.png", "p2.png", "p10.png"]
    assert engine._natural("a12b") == ["a", 12, "b"]
    assert engine._natural(5) == ["", 5, ""]


def check_sizes_and_archive_names():
    assert engine._size_bytes("25 MB") == 25 * 1024 ** 2
    assert engine._size_bytes("1.5 GB (large)") == int(1.5 * 1024 ** 3)
    assert engine._size_bytes("8 mb") == 8 * 1024 ** 2
    saved = engine.ARCHIVE_OUT, engine.can_write_rar
    try:
        engine.ARCHIVE_OUT = ["zip", "7z", "rar"]
        assert engine.archive_targets() == ["zip", "7z", "rar"]
        assert engine.archive_targets("7z") == ["zip", "rar"]
        engine.can_write_rar = lambda: False
        assert engine._rar_hint("rar") == "needs WinRAR" and engine._rar_hint("zip") == ""
        engine.can_write_rar = lambda: True
        assert engine._rar_hint("rar") == ""
    finally:
        engine.ARCHIVE_OUT, engine.can_write_rar = saved


def check_text_decoding_and_formats():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        samples = {"bom.txt": "\ufeffhello".encode("utf-8"), "u16.txt": "hi there".encode("utf-16"),
                   "ar.txt": "مرحبا".encode("cp1256"), "plain.txt": b"caf\xe9s"}
        (root / "bom.txt").write_bytes(samples["bom.txt"]); assert engine._read_text(root / "bom.txt") == "hello"
        (root / "u16.txt").write_bytes(samples["u16.txt"]); assert engine._read_text(root / "u16.txt") == "hi there"
        (root / "ar.txt").write_bytes(samples["ar.txt"]); assert engine._read_text(root / "ar.txt") == "مرحبا"
        (root / "plain.txt").write_bytes(samples["plain.txt"]); assert engine._read_text(root / "plain.txt") == "cafés"
    assert [engine._same_fmt(n) for n in ("a.jpeg", "a.TIF", "a.heif", "a.pdf", "a.xyz", "a.webp", "a.ico")] == \
           ["jpg", "tiff", "heic", "png", "png", "webp", "png"]
    assert engine._fake_path("video") == "C:/example/file.mp4"
    assert engine._fake_path("", "zip") == "C:/example/file.zip"
    assert engine._fake_path("nope") == "C:/example/file.bin"
    assert engine._fake_path("image", "heic") == "C:/example/file.heic"
    assert engine._asset("brand", "x.svg") == Path(engine.__file__).resolve().parent / "assets" / "brand" / "x.svg"
    assert engine._asset().name == "assets"
    steps = [("convert", "to_png", "jpg", "png"), ("convert", "to_zip", "jpg", "zip"), ("tool", "zip", "jpg", "zip"),
             ("tool", "protect_zip", "pdf", "zip"), ("tool", "removebg", "jpg", "png"), ("tool", "rotate", "mp4", "mp4"),
             ("convert", "split", "pdf", "pdf")]
    for group, op_id, ext, want in steps:
        assert engine._step_ext(ext, SimpleNamespace(group=group, id=op_id)) == want, (group, op_id)


def check_models():
    saved_paths, saved_models = engine.model_path, engine.MODELS
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        engine.model_path = lambda name: root / name
        engine.MODELS = {"sized": {"size": 4}, "open": {"size": 0}}
        try:
            assert not engine.model_ready("sized")
            (root / "sized").write_bytes(b"abc"); assert not engine.model_ready("sized")
            (root / "sized").write_bytes(b"abcd"); assert engine.model_ready("sized")
            engine.mark_model_ready("sized"); assert not (root / "sized.ok").exists()
            assert not engine.model_ready("open")
            (root / "open").write_bytes(b"x"); assert not engine.model_ready("open")
            engine.mark_model_ready("open"); assert (root / "open.ok").read_text() == "ok" and engine.model_ready("open")
        finally:
            engine.model_path, engine.MODELS = saved_paths, saved_models


def check_comics_and_packing():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        pages = []
        for n in (1, 2, 10):
            f = root / f"pg{n}.JPG"; f.write_bytes(bytes([n]) * 5); pages.append(f)
        cbz = engine._pages_to_cbz(pages, root / "out.cbz")
        with zipfile.ZipFile(cbz) as z:
            assert z.namelist() == ["001.jpg", "002.jpg", "003.jpg"]
            assert all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist())
            assert z.read("003.jpg") == bytes([10]) * 5
        saved = engine.comic_pages
        engine.comic_pages = lambda src: pages
        try:
            out = engine.comic_extract(root / "book.cbz", None)
            assert sorted(p.name for p in out.iterdir()) == ["001.jpg", "002.jpg", "003.jpg"] and out.name == "book pages"
            out2 = engine.comic_extract(root / "book.cbz", None)
            assert out2.name == "book pages (2)"
            assert engine.comic_to_cbz(root / "book.cbz", None).name == "book.cbz"
        finally:
            engine.comic_pages = saved
        for n in ("a10.png", "a2.png", "a1.png"):
            (root / n).write_bytes(b"x")
        made = engine.images_to_cbz([str(root / n) for n in ("a10.png", "a2.png", "a1.png")], None)
        assert made.name == "a1 comic.cbz"
        with zipfile.ZipFile(made) as z:
            assert z.namelist() == ["001.png", "002.png", "003.png"]
    calls = []
    saved = engine.pack_paths
    engine.pack_paths = lambda items, fmt: calls.append((list(items), fmt)) or "packed"
    try:
        assert engine.compress_to("7z")(["a", "b"], None) == "packed"
        assert engine.to_zip(["a"], None) == "packed" and engine.to_targz(["a"], None) == "packed"
        assert engine.pack("single", "zip") == "packed" and engine.pack(["x", "y"], "tar.gz", Path("ignored")) == "packed"
        assert calls == [(["a", "b"], "7z"), (["a"], "zip"), (["a"], "tar.gz"), (["single"], "zip"), (["x", "y"], "tar.gz")], calls
    finally:
        engine.pack_paths = saved
    saved = engine.office_convert
    engine.office_convert = lambda src, fmt: ("office", src, fmt)
    try:
        assert engine.office_to("pdf")("f.docx", None) == ("office", "f.docx", "pdf")
    finally:
        engine.office_convert = saved


def check_images_and_pdf():
    Image, _ = engine._pil()
    rgba = Image.new("RGBA", (2, 1), (255, 0, 0, 0)); rgba.putpixel((1, 0), (0, 0, 255, 255))
    flat = engine._flatten(rgba)
    assert flat.mode == "RGB" and flat.getpixel((0, 0)) == (255, 255, 255) and flat.getpixel((1, 0)) == (0, 0, 255)
    assert engine._flatten(rgba, bg=(0, 0, 0)).getpixel((0, 0)) == (0, 0, 0)
    assert engine._flatten(Image.new("L", (1, 1), 7)).mode == "RGB"
    pal = Image.new("P", (2, 1)); pal.putpalette([0, 0, 0, 9, 8, 7] + [0] * 750); pal.putpixel((1, 0), 1)
    cleaned = engine._strip(pal, None)
    assert cleaned.mode == "P" and cleaned.getpixel((1, 0)) == 1 and cleaned.getpalette()[:6] == [0, 0, 0, 9, 8, 7]
    rgb = Image.new("RGB", (2, 2), (1, 2, 3)); rgb.info["exif"] = b"junk"
    assert engine._strip(rgb, None).info == {} and engine._strip(rgb, None).getpixel((0, 0)) == (1, 2, 3)
    import fitz
    with tempfile.TemporaryDirectory() as d:
        plain, locked = Path(d) / "p.pdf", Path(d) / "l.pdf"
        doc = fitz.open(); doc.new_page(); doc.save(plain)
        doc.save(locked, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw"); doc.close()
        assert engine.pdf_is_encrypted(plain) is False and engine.pdf_is_encrypted(locked) is True
        assert engine.pdf_is_encrypted(Path(d) / "missing.pdf") is False
        assert engine.pdf_is_encrypted(locked) is True      # cached answer


def check_pages_to_pdf():
    import fitz
    Image, _ = engine._pil()
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        pages = []
        for n, colour in enumerate(((255, 0, 0), (0, 255, 0))):
            f = root / f"p{n}.png"; Image.new("RGB", (30, 20 + n * 10), colour).save(f); pages.append(f)
        out = engine._pages_to_pdf(pages, root / "book.pdf")
        doc = fitz.open(out)
        assert out == root / "book.pdf" and doc.page_count == 2
        assert round(doc[1].rect.height / doc[0].rect.height, 2) == 1.5   # second picture is 1.5x taller
        doc.close()


def check_audio_probe_and_catalogue():
    saved = engine.subprocess.run
    try:
        engine.subprocess.run = lambda *a, **k: SimpleNamespace(stderr=b"Stream #0:0: Audio: mp3")
        assert engine.has_audio("x.mp4") is True
        engine.subprocess.run = lambda *a, **k: SimpleNamespace(stderr=b"Stream #0:0: Video: h264")
        assert engine.has_audio("x.mp4") is False
        def boom(*a, **k): raise OSError("no ffmpeg")
        engine.subprocess.run = boom
        assert engine.has_audio("x.mp4") is True            # unknown: assume sound rather than drop it
    finally:
        engine.subprocess.run = saved
    # This source tree currently exposes 93 sample conversions and 104 tools.
    assert engine.count_catalog() == (93, 104)
    fingerprint = {e: sorted(o.id for o in engine.chain_step_ops(e)) for e in ("jpg", "mp4", "pdf", "zip", "docx")}
    assert hashlib.md5(repr(fingerprint).encode()).hexdigest() == "c633f46cec9ea79bdc93bd10952aa229"
    for e, ids in fingerprint.items():
        assert not {"none", "count", "unlock"} & set(ids)


def main():
    for fn in (check_links_and_sorting, check_sizes_and_archive_names, check_text_decoding_and_formats, check_models,
               check_comics_and_packing, check_pages_to_pdf, check_images_and_pdf, check_audio_probe_and_catalogue):
        fn()
    print("Engine link, sort, size, text, format, model, comic, packing, image, PDF and catalogue helpers passed")


if __name__ == "__main__":
    main()
