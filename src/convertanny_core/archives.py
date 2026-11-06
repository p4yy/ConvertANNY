"""ConvertANNY archive creation, repacking, and guarded extraction."""

from __future__ import annotations

import bz2
import gzip
import lzma
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .model import CancelToken, ConversionError
from .paths import OutputPolicy, atomic_write


_TAR_MODES = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}
_TAR_READ = {"tar", "tar.gz", "tar.bz2", "tar.xz"}


def archive_format(path: str | Path) -> str:
    name = Path(path).name.lower()
    for extension in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if name.endswith(extension):
            return extension[1:]
    extension = Path(name).suffix.lstrip(".")
    return {"tgz": "tar.gz", "tbz2": "tar.bz2", "txz": "tar.xz"}.get(extension, extension)


def _safe_member(root: Path, member: str) -> Path:
    normalized = str(member).replace("\\", "/")
    if (not normalized or "\x00" in normalized or normalized.startswith("/")
            or normalized.startswith("//") or (len(normalized) >= 2 and normalized[1] == ":")):
        raise ConversionError("Archive contains an unsafe path")
    parts = PurePosixPath(normalized).parts
    if any(part in ("..", "") for part in parts):
        raise ConversionError("Archive contains an unsafe path")
    destination = (root / Path(*parts)).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise ConversionError("Archive contains an unsafe path")
    return destination


def _unique_folder(parent: Path, name: str) -> Path:
    candidate = parent / name
    index = 2
    while candidate.exists():
        candidate = parent / f"{name} ({index})"
        index += 1
    candidate.mkdir(parents=True)
    return candidate


def _walk_sources(paths, root: Path, token: CancelToken | None):
    """Yield regular files with archive paths rooted at the selected inputs."""
    for source in paths:
        source = Path(source)
        entries = [source] if source.is_file() else [source, *sorted(source.rglob("*"))]
        for item in entries:
            if token:
                token.check()
            if item.is_symlink():
                continue
            try:
                relative = item.relative_to(root)
            except ValueError:
                relative = Path(source.name) / item.relative_to(source) if source.is_dir() and item != source else Path(source.name)
            if item.is_dir():
                yield item, relative
                continue
            if not item.is_file():
                continue
            yield item, relative


def _source_root(paths) -> Path:
    first = Path(paths[0])
    parents = [path.parent for path in map(Path, paths)]
    try:
        return Path(os.path.commonpath([str(path.resolve()) for path in parents]))
    except (ValueError, OSError):
        return first.parent


def _rar_executable() -> str | None:
    executable = shutil.which("rar") or shutil.which("Rar")
    if executable:
        return executable
    if os.name == "nt":
        roots = (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("ProgramW6432"))
        for root in roots:
            if root:
                candidate = Path(root) / "WinRAR" / "Rar.exe"
                if candidate.is_file():
                    return str(candidate)
    return None


def _seven_zip_executable() -> str | None:
    executable = shutil.which("7z") or shutil.which("7za")
    if executable:
        return executable
    if os.name == "nt":
        roots = (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("ProgramW6432"))
        for root in roots:
            if root:
                candidate = Path(root) / "7-Zip" / "7z.exe"
                if candidate.is_file():
                    return str(candidate)
    return None


def _unrar_executable() -> str | None:
    executable = shutil.which("unrar") or shutil.which("unrar.exe")
    if executable:
        return executable
    if os.name == "nt":
        roots = (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("ProgramW6432"))
        for root in roots:
            if root:
                candidate = Path(root) / "WinRAR" / "UnRAR.exe"
                if candidate.is_file():
                    return str(candidate)
    return None


def _windows_tar_executable() -> str | None:
    if os.name == "nt":
        candidate = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def can_write_rar() -> bool:
    return _rar_executable() is not None


def _run_external(command, cwd: Path, token: CancelToken | None) -> None:
    flags = 0x08000000 if os.name == "nt" else 0
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=flags)
    try:
        while process.poll() is None:
            if token:
                token.check()
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass
        if process.returncode not in (0, 1):
            raise ConversionError("The external archive utility reported a failure")
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise


def _extract_external(source: Path, folder: Path, fmt: str, token: CancelToken | None) -> None:
    """Use installed archive tools in a private staging tree, then copy checked members."""
    seven_zip = _seven_zip_executable()
    unrar = _unrar_executable() if fmt == "rar" else None
    windows_tar = _windows_tar_executable()
    source = source.resolve()
    with tempfile.TemporaryDirectory(prefix="convertanny-extract-") as temporary:
        stage = Path(temporary) / "stage"
        stage.mkdir()
        if seven_zip:
            command = [seven_zip, "x", "-y", f"-o{stage}", str(source)]
        elif unrar:
            command = [unrar, "x", "-y", "-inul", str(source), str(stage) + os.sep]
        elif windows_tar:
            command = [windows_tar, "-xf", str(source), "-C", str(stage)]
        else:
            raise ConversionError("Install 7-Zip or WinRAR to open this archive")
        _run_external(command, stage, token)

        members = []
        for item in stage.rglob("*"):
            if token:
                token.check()
            if item.is_symlink():
                raise ConversionError("Archive contains a symbolic link")
            relative = item.relative_to(stage)
            target = _safe_member(folder, relative.as_posix())
            if not item.is_file() and not item.is_dir():
                raise ConversionError("Archive contains an unsupported filesystem entry")
            members.append((item, target))
        for item, target in members:
            if token:
                token.check()
            if target.exists():
                raise ConversionError(f"Archive output already exists: {target.name}")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)


def _write_archive(paths, fmt: str, destination: Path, token: CancelToken | None) -> Path:
    paths = [Path(path) for path in paths]
    root = _source_root(paths)

    def writer(temporary: Path):
        if fmt == "zip":
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED,
                                 compresslevel=6, allowZip64=True) as archive:
                for item, relative in _walk_sources(paths, root, token):
                    archive.write(item, relative.as_posix() + ("/" if item.is_dir() else ""))
        elif fmt == "7z":
            import py7zr
            with py7zr.SevenZipFile(temporary, "w") as archive:
                for item, relative in _walk_sources(paths, root, token):
                    archive.write(item, relative.as_posix())
        elif fmt in _TAR_MODES:
            with tarfile.open(temporary, _TAR_MODES[fmt]) as archive:
                for item, relative in _walk_sources(paths, root, token):
                    archive.add(item, arcname=relative.as_posix(), recursive=False)
        elif fmt == "rar":
            executable = _rar_executable()
            if not executable:
                raise ConversionError("Creating RAR files requires WinRAR")
            staging = temporary.with_name(f".{temporary.stem}.{uuid4().hex}.rar")
            try:
                relative_files = [relative.as_posix() for _, relative in _walk_sources(paths, root, token)
                                  if not _.is_dir()]
                if not relative_files:
                    raise ConversionError("There are no supported files to archive")
                _run_external([executable, "a", "-r", "-inul", "-y", str(staging), *relative_files], root, token)
                shutil.copyfile(staging, temporary)
            finally:
                staging.unlink(missing_ok=True)
        else:
            raise ConversionError(f"Unsupported archive format: {fmt}")

    return atomic_write(destination, writer, token)


def create_archive(paths, fmt: str, *, directory: str | Path | None = None,
                   token: CancelToken | None = None) -> Path:
    sources = [Path(path) for path in paths]
    if not sources or any(not path.exists() for path in sources):
        raise ConversionError("Choose existing files or folders to archive")
    fmt = fmt.lower().lstrip(".")
    first = sources[0]
    if len(sources) == 1:
        stem = first.name if first.is_dir() else first.stem
    else:
        stem = first.parent.name or "Archive"
    parent = Path(directory) if directory else first.parent
    destination = OutputPolicy(directory=parent).destination(Path(stem), fmt)
    return _write_archive(sources, fmt, destination, token)


def create_zip(paths, *, directory=None, token: CancelToken | None = None) -> Path:
    """Compatibility entry point while callers migrate to create_archive."""
    return create_archive(paths, "zip", directory=directory, token=token)


def create_protected_archive(paths, format: str, password: str, *, directory=None,
                             token: CancelToken | None = None) -> Path:
    """Create an AES-encrypted ZIP or a 7z archive with encrypted headers."""
    sources = [Path(path) for path in paths]
    if not sources or any(not source.exists() for source in sources):
        raise ConversionError("Choose existing files or folders to archive")
    if not password:
        raise ConversionError("Password cannot be empty")
    format = format.lower().split("(", 1)[0].strip()
    extension = "7z" if format.startswith("7z") else "zip"
    first = sources[0]
    name = first.name if len(sources) == 1 and first.is_dir() else first.stem if len(sources) == 1 else first.parent.name or "Archive"
    output = OutputPolicy(directory=directory or first.parent, suffix=" (protected)").destination(name, extension)
    root = _source_root(sources)

    def write(temporary: Path):
        files = [(item, relative) for item, relative in _walk_sources(sources, root, token) if item.is_file()]
        if not files:
            raise ConversionError("There are no files to protect")
        if extension == "7z":
            import py7zr
            with py7zr.SevenZipFile(temporary, "w", password=password, header_encryption=True) as archive:
                for item, relative in files:
                    if token: token.check()
                    archive.write(item, relative.as_posix())
        else:
            import pyzipper
            with pyzipper.AESZipFile(temporary, "w", compression=pyzipper.ZIP_DEFLATED,
                                     compresslevel=6, encryption=pyzipper.WZ_AES) as archive:
                archive.setpassword(password.encode("utf-8"))
                for item, relative in files:
                    if token: token.check()
                    archive.write(item, relative.as_posix())

    return atomic_write(output, write, token)


def _extract_zip(source: Path, folder: Path, token: CancelToken | None):
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        total = max(1, sum(max(1, member.file_size) for member in members))
        completed = 0
        for member in members:
            if token:
                token.check()
            mode = member.external_attr >> 16
            if mode and (mode & 0o170000) in (0o120000, 0o060000, 0o020000):
                raise ConversionError("Archive contains a link or special file")
            destination = _safe_member(folder, member.filename)
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as incoming, destination.open("wb") as outgoing:
                while block := incoming.read(1024 * 1024):
                    if token:
                        token.check()
                    outgoing.write(block)
                    completed += len(block)
                    if token:
                        token.report(completed / total)


def _extract_tar(source: Path, folder: Path, token: CancelToken | None):
    with tarfile.open(source, "r:*") as archive:
        for member in archive.getmembers():
            if token:
                token.check()
            destination = _safe_member(folder, member.name)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ConversionError("Archive contains a link or special file")
            destination.parent.mkdir(parents=True, exist_ok=True)
            incoming = archive.extractfile(member)
            if incoming is None:
                continue
            with incoming, destination.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            if token:
                token.check()


def _extract_7z(source: Path, folder: Path, token: CancelToken | None):
    import py7zr
    with py7zr.SevenZipFile(source, "r") as archive:
        info_by_name = {info.filename: info for info in archive.list()}
        selected = []
        for name in archive.getnames():
            if token:
                token.check()
            info = info_by_name.get(name)
            if info is not None and info.is_symlink:
                raise ConversionError("Archive contains a symbolic link")
            _safe_member(folder, name)
            selected.append(name)
        archive.extract(path=folder, targets=selected)


def _extract_single_stream(source: Path, folder: Path, fmt: str, token: CancelToken | None):
    opener = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[fmt]
    output = _safe_member(folder, source.stem)
    with opener(source, "rb") as incoming, output.open("wb") as outgoing:
        while block := incoming.read(1024 * 1024):
            if token:
                token.check()
            outgoing.write(block)


def extract_archive_into(source: str | Path, folder: str | Path,
                         token: CancelToken | None = None) -> Path:
    """Extract supported formats into an existing private directory."""
    source, folder = Path(source), Path(folder)
    fmt = archive_format(source)
    with source.open("rb") as stream:
        signature = stream.read(8)
    if zipfile.is_zipfile(source) or fmt in {"cbz", "zip"}:
        _extract_zip(source, folder, token)
    elif signature.startswith(b"7z\xbc\xaf\x27\x1c") or fmt in {"7z", "cb7"}:
        _extract_7z(source, folder, token)
    elif fmt in {"tar", "tar.gz", "tar.bz2", "tar.xz", "cbt"}:
        _extract_tar(source, folder, token)
    elif fmt in {"gz", "bz2", "xz"}:
        if fmt == "gz" and tarfile.is_tarfile(source):
            _extract_tar(source, folder, token)
        else:
            _extract_single_stream(source, folder, fmt, token)
    elif fmt in {"rar", "iso", "cab", "cbr"}:
        _extract_external(source, folder, fmt, token)
    else:
        raise ConversionError("This archive format is not supported")
    return folder


def extract_archive(source: str | Path, *, directory: str | Path | None = None,
                    token: CancelToken | None = None, on_temporary=None) -> Path:
    source = Path(source)
    fmt = archive_format(source)
    parent = Path(directory) if directory else source.parent
    name = source.name
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if name.lower().endswith(suffix):
            name = name[:-len(suffix)]
            break
    else:
        name = source.stem
    folder = _unique_folder(parent, name)
    try:
        extract_archive_into(source, folder, token)
        return folder
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def repack_archive(source: str | Path, fmt: str, *, directory: str | Path | None = None,
                   token: CancelToken | None = None, on_temporary=None) -> Path:
    source = Path(source)
    with tempfile.TemporaryDirectory(prefix="convertanny-archive-") as temporary:
        root = Path(temporary)
        if on_temporary:
            on_temporary(root)
        try:
            extract_archive_into(source, root, token)
        except ConversionError as error:
            raise ConversionError("Converting this archive needs 7-Zip or WinRAR") from error

        destination_root = Path(directory) if directory else source.parent
        parent_name = source.name
        for suffix in (".tar.gz", ".tar.bz2", ".tar.xz"):
            if parent_name.lower().endswith(suffix):
                parent_name = parent_name[:-len(suffix)]
                break
        else:
            parent_name = source.stem
        items = sorted(root.iterdir())
        if not items:
            raise ConversionError("The archive is empty")
        destination = OutputPolicy(directory=destination_root).destination(Path(parent_name), fmt)
        return _write_archive(items, fmt, destination, token)


def gzip_file(source: str | Path, *, directory: str | Path | None = None,
              token: CancelToken | None = None) -> Path:
    source = Path(source)
    parent = Path(directory) if directory else source.parent
    destination = OutputPolicy(directory=parent, suffix="").destination(Path(source.name), "gz")

    def writer(temporary: Path):
        with source.open("rb") as incoming, gzip.open(temporary, "wb", compresslevel=9) as outgoing:
            while block := incoming.read(1024 * 1024):
                if token:
                    token.check()
                outgoing.write(block)

    return atomic_write(destination, writer, token)
