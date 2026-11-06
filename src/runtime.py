"""
ConvertANNY — drag a file, tap a key, drop on the wheel. Offline file converter for Windows.

Drag a file, tap Shift  -> conversion wheel
                 tap Ctrl   -> file tools (compress, trim, resize, merge…)
                 tap Alt    -> file actions (copy, move, terminal, float…)
Drop on a slice to apply it. Everything runs locally.

Also: select files in Explorer and press Ctrl+Alt+Space, or right-click > "ConvertANNY".
"""
from __future__ import annotations
from preset_editor import PresetDialog, CustomSliceDialog
from chain_editor import ChainDialog
from wheel_editor import WheelLayoutDialog
from settings_backup import export_settings, import_settings
from user_actions import (_jload, custom_slices, save_custom_slices, my_slices_file, load_my_slices,
                          save_my_slices, slice_app, run_my_slice, wheel_layout, apply_wheel_layout,
                          custom_ops_for, MY_SLICES_TEMPLATE)

import getpass
import json
import math
import os
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPointF, QPropertyAnimation, QRectF, QRunnable, QSizeF, QVariantAnimation,
                            QRect, QSettings, QSize, Qt, QThreadPool, QTimer, QUrl, Signal, QMimeData, QPoint)
from PySide6.QtGui import (QTextDocumentFragment, QAction, QBrush, QColor, QCursor, QDesktopServices, QDrag, QFont, QFontMetrics,
                           QGuiApplication, QIcon, QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QRadialGradient)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QTabWidget,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget)

from settings_controls import ToggleSwitch,SwitchBox,setting_row,KeyCapture,qt_key_name,combo_text
from preferences import Preferences as SettingsDialog
from media_editors import WaveView,TrimWidget,CropPreview
from scan_editor import CornerPicker
from live_relay import LiveRelay
from stream_cache import StreamCache
from onboarding import TourCanvas,TourDialog
from orbit_base import Wheel
from notifications import Toast,ToastManager
from folder_watch import FolderWatch,WatchRuleDialog,discover_operations
from signature_editor import DrawPad,SignPlacer
from watermark_editor import WatermarkEditor
from page_board import PageBoard
from rename_dialog import BatchRenameDialog
from convertanny_core.sharing import (BLOCKED_UPLOAD_EXT, HOST_CHOICES,
                                      upload_temporary as _owned_upload_temporary)
from convertanny_core.interaction_preferences import InteractionPreferences

import engine
import i18n
import theme
import updater
import winsys
from i18n import tr

APP = "ConvertANNY"
VERSION = "0.1.0"

ACCENT = QColor("#2563eb")
ON_ACCENT = QColor("#ffffff")


def sync_accent():
    """The theme's accent colour, used by everything that's painted (changed in place, so it's everywhere)."""
    try:
        ACCENT.setRgba(QColor(theme.hexc("accent")).rgba())
        ON_ACCENT.setRgba(QColor(theme.hexc("on_accent")).rgba())
    except Exception:
        pass


def C(name):
    """Current theme colour (see theme.py)."""
    return theme.color(name)

MODES = ["convert", "tool", "action"]
MODE_LABEL = {"convert": "Convert", "tool": "Tools", "action": "Actions"}   # translated at use: tr(MODE_LABEL[m])
DEFAULT_KEYS = InteractionPreferences.DEFAULT_KEYS


def settings() -> QSettings:
    return QSettings(APP, APP)


def mode_keys() -> dict[str, str]:
    return _interaction_preferences().mode_keys()


def _interaction_preferences() -> InteractionPreferences:
    store = settings()
    return InteractionPreferences(store.value)


def trigger_mode() -> str:
    """When a wheel key opens the wheel: "drag" (while dragging a file), "hover" (also when pointing at a file),
    "select" (also for the files selected in Explorer)."""
    return _interaction_preferences().trigger()


def peek_key() -> str:
    """The key that shows Quick preview while dragging (Space unless you chose another, or turned it off)."""
    return _interaction_preferences().preview_key()


# Windows language ids NSIS uses for each app language (Setup remembers its choice under "InstallerLanguage")
INSTALLER_LANG_IDS = {"en": 1033, "ar": 1025, "fr": 1036, "es": 1034, "de": 1031, "it": 1040, "pt": 1046, "tr": 1055,
                      "ru": 1049, "fa": 1065, "ur": 1056, "hi": 1081, "ja": 1041, "zh": 2052}


def peek_hold() -> bool:
    """File preview: True = shown while the key is held, False = press to open, press again to close."""
    return _interaction_preferences().preview_held()


def key_label(spec: str) -> str:
    """'Ctrl+Q' as shown to you (each part translated)."""
    return InteractionPreferences.label(spec, tr)


# ============================================================================
# Files: batch rename, checksum, shred, send to phone
# ============================================================================








def shred_path(path):
    from convertanny_core.secure_delete import shred_path as remove
    return remove(path)


_IPS = (0.0, None)
from convertanny_core.background_refresh import SingleFlightRefresh
_IP_REFRESH = SingleFlightRefresh()


def _lan_ips() -> list[str]:
    """IPv4 addresses a phone could reach, best first (looked up in the background a moment earlier when possible:
    the lookup can take a second and would freeze a playing float)."""
    t, ips = _IPS
    if ips and time.time() - t < 120:
        return list(ips)
    return _find_lan_ips()


def warm_lan_ips():
    def save(addresses):
        global _IPS
        _IPS = (time.time(), addresses)
    _IP_REFRESH.start(_find_lan_ips, save)


def _find_lan_ips() -> list[str]:
    from convertanny_core.lan_addresses import phone_reachable_addresses
    return phone_reachable_addresses()


def allow_through_firewall() -> bool:
    """Ask Windows (UAC) to let phones reach ConvertANNY: removes old block rules, adds an allow rule."""
    if not winsys.IS_WIN:
        return False
    import ctypes
    exe = sys.executable
    cmd = (f'/c netsh advfirewall firewall delete rule name=all program="{exe}" & '
           f'netsh advfirewall firewall add rule name="ConvertANNY (Send to phone)" dir=in action=allow protocol=TCP '
           f'program="{exe}" profile=private,public enable=yes')
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", cmd, None, 0)
    winsys.log(f"firewall rule requested: {r}")
    return r > 32


def _lan_ip() -> str:
    from convertanny_core.lan_addresses import route_address
    return route_address()


from dialog_base import FrontDialog


class PhoneShare(FrontDialog):
    """Share files with a phone on the same Wi-Fi: a QR code opens a page served straight from this PC."""

    def __init__(self, paths, mode="wifi"):
        super().__init__(None)
        import secrets
        self.mode = mode                 # "wifi": phones on this network · "tunnel": anywhere, through Cloudflare
        self.tunnel = None
        self.keep_hides = True
        self.key = share_key(paths)
        self.ended = False
        self.setWindowTitle(f"{APP} — " + tr("Send to phone"))
        self.setWindowIcon(app_icon())
        self.setStyleSheet(i18n.css(DIALOG_CSS))
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.paths = [Path(x) for x in paths]
        token = secrets.token_urlsafe(6)
        share = self
        self.hits = 0

        from convertanny_core.phone_server import PhoneFileServer
        self.server = PhoneFileServer(
            self.paths, token, host="127.0.0.1" if mode == "tunnel" else "0.0.0.0",
            human_size=_human,
            on_request=lambda address, path: self._phone_request(address, path),
            on_download=self._hit,
        )
        self._port, self._token = self.server.port, token
        self.ips = _lan_ips() if mode == "wifi" else []
        lay = QVBoxLayout(self)
        from PySide6.QtWidgets import QLayout
        lay.setSizeConstraint(QLayout.SetFixedSize)          # the window always fits the code and the text
        what = self.paths[0].name if len(self.paths) == 1 else tr("{n} files", n=len(self.paths))
        self.header(lay, tr("Link from this PC") if mode == "tunnel" else tr("Same Wi-Fi"), what)
        self.qr = QrBox()
        lay.addWidget(self.qr, 0, Qt.AlignHCenter)
        self.link = QLabel()
        self.link.setObjectName("sub")
        self.link.setAlignment(Qt.AlignCenter)
        self.link.setWordWrap(True)
        self.link.setFixedWidth(QR_W)
        self.link.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.link, 0, Qt.AlignHCenter)
        if len(self.ips) > 1:                              # several network adapters: let the user switch
            self.ip_box = QComboBox()
            for ip in self.ips:
                self.ip_box.addItem(tr("Network address: {ip}", ip=ip), ip)
            self.ip_box.currentIndexChanged.connect(lambda _i: self._show_qr(self.ip_box.currentData()))
            lay.addWidget(self.ip_box)
        if mode == "tunnel":
            self.url = ""
            self.qr.busy(tr("Making the link…"))
            info = QLabel(tr("Sharing {what}. The link works on any network, even mobile data. The file goes straight "
                             "from this PC through Cloudflare and isn't stored anywhere; the link ends when you close "
                             "this window, so keep it open until it's downloaded.", what=what))
        else:
            self._show_qr(self.ips[0])
            info = QLabel(tr("Sharing {what}. Your phone must be on the same Wi-Fi. If Windows asks, allow ConvertANNY on "
                             "private networks. Nothing goes through the internet; sharing stops when you close this window.",
                             what=what))
        info.setObjectName("note")
        info.setWordWrap(True)
        info.setFixedWidth(QR_W)
        lay.addWidget(info)
        self.count = QLabel()
        lay.addWidget(self.count)
        stop = QPushButton(tr("Stop sharing"))
        stop.clicked.connect(self._stop_now)                 # the button says it: stop, no question
        if mode == "tunnel":
            self.copy_b = QPushButton(tr("Copy link"))
            self.copy_b.setObjectName("primary")
            self.copy_b.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.url))
            self.copy_b.setEnabled(False)
            self.buttons(lay, self.copy_b, stop)
        else:
            help_b = QPushButton(tr("Phone can't open it?"))
            help_b.clicked.connect(self._help)
            self.buttons(lay, help_b, stop)
        self.diag = QLabel()
        self.diag.setWordWrap(True)
        self.diag.setFixedWidth(QR_W)
        self.diag.setStyleSheet(f"color:{theme.hexc('danger')}")
        self.diag.hide()
        lay.insertWidget(lay.indexOf(self.count), self.diag)
        self._seen = None
        self._diag_lines = None
        self._poll = QTimer(self, interval=500, timeout=self._update)
        self._poll.start()
        self._last = ""
        self._tunnel_url = None
        self._tunnel_err = None
        if mode == "tunnel":
            threading.Thread(target=self._start_tunnel, daemon=True).start()
        else:
            threading.Thread(target=self._diagnose, daemon=True).start()

    def _start_tunnel(self):
        """Cloudflare's quick tunnel: a random https://….trycloudflare.com address that reaches this window's
        little web server. No account; it lasts while cloudflared runs."""
        import re
        import subprocess
        try:
            self.tunnel = subprocess.Popen(
                [str(engine.model_path("cloudflared")), "tunnel", "--no-autoupdate", "--url",
                 f"http://127.0.0.1:{self._port}"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, creationflags=engine.NO_WINDOW)
        except Exception as e:
            self._tunnel_err = str(e)
            return
        t0 = time.monotonic()
        for raw in iter(self.tunnel.stdout.readline, b""):
            line = raw.decode("utf-8", "replace")
            m = re.search(r"https://[-a-z0-9]+\.trycloudflare\.com", line)
            if m and self._tunnel_url is None:
                self._tunnel_url = m.group(0)
                winsys.log(f"send to phone: tunnel {self._tunnel_url} after {time.monotonic() - t0:.1f} s")
            elif ("ERR" in line or "error" in line.lower()) and self._tunnel_url is None:
                winsys.log("cloudflared: " + line.strip()[:200])
        if self._tunnel_url is None:
            self._tunnel_err = tr("Couldn't make the link. Check the internet connection, or that a firewall or "
                                  "antivirus lets cloudflared.exe connect.")

    def _show_qr(self, ip):
        self._show_url(f"http://{ip}:{self._port}/{self._token}/")

    def _show_url(self, url):
        self.url = url
        winsys.log(f"send to phone: {self.url} (addresses: {', '.join(self.ips) or 'tunnel'})")
        self.link.setText(self.url)
        self.qr.show_code(self.url)

    def _help(self):
        box = QMessageBox(self)
        box.setWindowTitle(f"{APP} — " + tr("Send to phone"))
        box.setStyleSheet(i18n.css(DIALOG_CSS))
        box.setTextFormat(Qt.RichText)
        box.setText("<b>" + tr("If the phone says the site can't be reached:") + "</b><ol>"
                    + "<li>" + tr("Windows Firewall is probably blocking it. Press Allow in firewall below (Windows asks for permission once).") + "</li>"
                    + "<li>" + tr("Make sure the phone is on the same Wi-Fi as this PC, not mobile data or a guest network.") + "</li>"
                    + ("<li>" + tr("Try the other network address in the list under the QR code.") + "</li>" if len(self.ips) > 1 else "")
                    + "<li>" + tr("Turn off any VPN on the phone and on this PC while sharing.") + "</li>"
                    + "<li>" + tr("Some routers keep Wi-Fi devices apart ('AP isolation' or 'client isolation'), or put the phone on a separate 2.4/5 GHz or mesh network. If nothing above helps, that's the cause — it can be turned off in the router's settings.") + "</li>"
                    + "</ol>")
        allow = box.addButton(tr("Allow in firewall"), QMessageBox.AcceptRole)
        box.addButton(tr("Close"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is allow:
            if allow_through_firewall():
                self.count.setText(tr("Allowed. Scan the code again on the phone."))

    def _diagnose(self):
        """Why a phone may not get through: network set to Public with incoming blocked, Windows' 'block all
        incoming connections', another security app's firewall, or no allow rule. Read-only, no admin."""
        if not winsys.IS_WIN:
            return
        import subprocess
        ip = self.url.split("//")[1].split(":")[0]
        exe = sys.executable.replace("'", "''")
        ps = f"""
$ErrorActionPreference='SilentlyContinue'
$a = Get-NetIPAddress -IPAddress '{ip}'
if ($a) {{ $p = Get-NetConnectionProfile -InterfaceIndex $a.InterfaceIndex; "iface|$($a.InterfaceAlias)|$($p.NetworkCategory)|$($p.Name)" }}
Get-NetFirewallProfile | ForEach-Object {{ "profile|$($_.Name)|$($_.Enabled)|$($_.DefaultInboundAction)|$($_.AllowInboundRules)" }}
Get-NetFirewallApplicationFilter -Program '{exe}' | Get-NetFirewallRule | ForEach-Object {{ "rule|$($_.DisplayName)|$($_.Direction)|$($_.Action)|$($_.Enabled)|$($_.Profile)" }}
Get-CimInstance -Namespace root/SecurityCenter2 -ClassName FirewallProduct | ForEach-Object {{ "fwproduct|$($_.displayName)" }}
Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntivirusProduct | ForEach-Object {{ "av|$($_.displayName)" }}
"""
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                               capture_output=True, timeout=40, creationflags=engine.NO_WINDOW)
            lines = [x.strip() for x in r.stdout.decode("utf-8", "replace").splitlines() if "|" in x]
        except Exception as e:
            lines = [f"error|{e}"]
        for x in lines:
            winsys.log("send to phone check: " + x)
        self._diag_lines = lines

    def _diag_text(self, lines):
        notes = []
        cat = next((x.split("|")[2] for x in lines if x.startswith("iface|")), "")
        profiles = {x.split("|")[1].lower(): x.split("|") for x in lines if x.startswith("profile|")}
        active = profiles.get("public" if cat.lower() == "public" else "private" if cat.lower() == "private" else "domain")
        if active and active[2].lower() == "true" and active[4].lower() == "false":
            notes.append(tr("Windows Security is set to block all incoming connections on this network, even for allowed apps. "
                            "Turn that off in Windows Security → Firewall & network protection → {net} network.", net=active[1]))
        rules = [x.split("|") for x in lines if x.startswith("rule|") and x.split("|")[2].lower() == "inbound"]
        if any(r[3].lower() == "block" and r[4].lower() == "true" for r in rules):
            notes.append(tr("A firewall rule blocks ConvertANNY. Press Allow in firewall."))
        elif not any(r[3].lower() == "allow" and r[4].lower() == "true" for r in rules):
            notes.append(tr("ConvertANNY isn't allowed in Windows Firewall yet. Press Allow in firewall."))
        others = [x.split("|", 1)[1] for x in lines if x.startswith("fwproduct|") and "windows" not in x.lower()]
        if any("eset" in o.lower() for o in others):
            notes.append(tr("ESET's firewall is blocking the phone. In ESET open Setup → Network protection → "
                            "Connected networks, and set this network to Trusted (Home or office). Or add a rule: "
                            "Firewall → Rules → Add → Allow incoming for ConvertANNY.exe."))
            others = [o for o in others if "eset" not in o.lower()]
        if others:
            notes.append(tr("{app} has its own firewall: allow ConvertANNY there too (or let it trust your home network).",
                            app=", ".join(others)))
        if cat.lower() == "public":
            notes.append(tr("This Wi-Fi is set as a Public network in Windows. Setting it to Private lets home devices connect."))
        return notes

    def _phone_request(self, address, path):
        winsys.log(f"send to phone: request from {address}: {path[:60]}")
        self._seen = address

    def _hit(self, name):
        self.hits += 1
        self._last = name

    def _update(self):
        if self.mode == "tunnel" and not self.url:
            if self._tunnel_url:
                self._show_url(f"{self._tunnel_url}/{self._token}/")
                self.copy_b.setEnabled(True)
            elif self._tunnel_err:
                self.qr.idle(tr("No link"))
                self.link.setText(f"<span style='color:{theme.hexc('danger')}'>{self._tunnel_err}</span>")
                self._tunnel_err = ""
        if self._diag_lines is not None:
            notes = self._diag_text(self._diag_lines)
            self._diag_lines = None
            self._notes = notes
            if notes:
                self.diag.setText("⚠ " + "\n\n⚠ ".join(notes))
                self.diag.show()
        if self.hits:
            self.count.setText(tr("Downloaded {n} time(s) — last: {name}", n=self.hits, name=self._last))

    def sharing(self):
        return not self.ended

    def _stop_now(self):
        self._leaving = True
        self.close()

    def stop_question(self):
        what = self.paths[0].name if len(self.paths) == 1 else tr("{n} files", n=len(self.paths))
        return tr("Stop sharing ends the link for {what}. Keep sharing hides this window and the link keeps "
                  "working; open it again from the tray (Send to phone).", what=what)

    def closeEvent(self, e):
        if not self.leave_ok(e):
            return
        self.ended = True
        try:
            self.server.close()
        except Exception:
            pass
        if self.tunnel is not None:                    # the link ends with the window
            try:
                self.tunnel.kill()
            except Exception:
                pass
        super().closeEvent(e)


QUICK_SHARE_URL = "https://www.android.com/better-together/quick-share-app/"














# name, function, size limit in MB, longest it keeps a file (minutes)
# what the Service list shows, and the link times each one offers (minutes)








def upload_temporary(path, minutes, progress=lambda fraction: None, cancelled=lambda: False, only=None):
    return _owned_upload_temporary(path, minutes, progress, cancelled, only,
                                   translate=tr, log=winsys.log)


def share_links() -> list:
    """Internet links still alive: [{"url", "name", "expires"}] (Unix time)."""
    from convertanny_core.share_history import live_links
    return live_links(settings())


def share_key(paths) -> str:
    """Which files were shared, and as they were then (a changed file is shared again, not the old copy)."""
    from convertanny_core.share_history import file_set_key
    return file_set_key(paths)


def remember_share_link(url, name, minutes, key=""):
    from convertanny_core.share_history import remember
    remember(settings(), url, name, minutes, key)


def qr_pixmap(text, scale=7) -> QPixmap:
    import io as _io
    import segno
    buf = _io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=3, dark="#000", light="#fff")
    return QPixmap.fromImage(QImage.fromData(buf.getvalue()))


QR_W = 372                    # content width of the Send to phone windows


def qr_image(text) -> QImage:
    """The QR code as a tiny 1-pixel-per-module picture (drawn bigger without smoothing, so it stays sharp)."""
    import segno
    rows = list(segno.make(text, error="m").matrix_iter(scale=1, border=2))
    n = len(rows)
    img = QImage(n, n, QImage.Format_RGB32)
    img.fill(QColor("#ffffff"))
    black = QColor("#000000").rgb()
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            if v:
                img.setPixel(x, y, black)
    return img


class QrBox(QWidget):
    """The place for a QR code: a spinning wheel inside it while the link is being made, then the code.
    Clicking the code copies the link."""

    def __init__(self, side=236, parent=None):
        super().__init__(parent)
        self.setFixedSize(side, side)
        self.url, self._img, self._busy, self._text, self._angle = "", None, False, "", 0
        self._spin = QTimer(self, interval=16, timeout=self._tick)

    def busy(self, text=""):
        self._img, self._busy, self._text = None, True, text
        self._spin.start()
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def idle(self, text=""):
        self._img, self._busy, self._text = None, False, text
        self._spin.stop()
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def set_text(self, text):
        self._text = text
        self.update()

    def show_code(self, url):
        self.url = url
        self._busy = False
        self._spin.stop()
        try:
            self._img = qr_image(url)
        except Exception as e:
            winsys.log(f"qr: {e}")
            self._img = None
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("Click to copy the link"))
        self.update()

    def mousePressEvent(self, e):
        if self._img is not None and e.button() == Qt.LeftButton:
            QGuiApplication.clipboard().setText(self.url)
            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(e.globalPosition().toPoint(), tr("Link copied"), self)

    def _tick(self):
        self._angle = (self._angle + 7) % 360
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._img is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(r, 16, 16)
            n = self._img.width()
            k = max(1, int((self.width() - 12) // n))
            size = n * k
            off = (self.width() - size) / 2
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            p.drawImage(QRectF(off, off, size, size), self._img)
            return
        p.setPen(QPen(QColor(theme.hexc("border")), 1.5))
        p.setBrush(QColor(theme.hexc("surface")))
        p.drawRoundedRect(r, 16, 16)
        c = QPointF(self.width() / 2, self.height() / 2 - (12 if self._text else 0))
        if self._busy:
            ring = QRectF(c.x() - 26, c.y() - 26, 52, 52)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme.hexc("border")), 5))
            p.drawEllipse(ring)
            p.setPen(QPen(QColor(theme.hexc("accent")), 5, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(ring, int(-self._angle * 16), 100 * 16)
        else:                                             # a faint QR mark: where the code will appear
            dim = QColor(theme.hexc("dim"))
            dim.setAlpha(110)
            p.setPen(QPen(dim, 3))
            p.setBrush(Qt.NoBrush)
            for dx, dy in ((-26, -26), (6, -26), (-26, 6)):
                p.drawRoundedRect(QRectF(c.x() + dx, c.y() + dy, 20, 20), 4, 4)
            p.setPen(Qt.NoPen)
            p.setBrush(dim)
            for dx, dy in ((10, 10), (20, 10), (10, 20), (20, 20)):
                p.drawRect(QRectF(c.x() + dx - 2, c.y() + dy - 2, 6, 6))
        if self._text:
            p.setPen(QColor(theme.hexc("dim")))
            f = p.font()
            f.setPointSizeF(9)
            p.setFont(f)
            p.drawText(QRectF(14, c.y() + 38, self.width() - 28, 44), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                       self._text)


def find_codes(img: QImage) -> list:
    from convertanny_core.barcode_scan import scan_image
    return scan_image(img)


def find_codes_in_file(path) -> list:
    from convertanny_core.barcode_scan import scan_file
    return scan_file(path, image_loader=engine.open_image, decoder=find_codes)


def _qr_meaning(text):
    from convertanny_core.qr_payload import interpret_payload
    return interpret_payload(text, tr)


class QrResult(FrontDialog):
    """What a QR code says, with Open / Copy."""

    def __init__(self, codes):
        super().__init__(None)
        from PySide6.QtWidgets import QLayout
        self.setWindowTitle(f"{APP} — " + tr("QR code"))
        self.setWindowIcon(app_icon())
        self.setStyleSheet(i18n.css(DIALOG_CSS))
        self.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        lay.setSizeConstraint(QLayout.SetFixedSize)
        self.header(lay, tr("QR code") if len(codes) == 1 else tr("{n} codes", n=len(codes)))
        for c in codes[:6]:
            kind, main, fields, url = _qr_meaning(c["text"])
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 12)
            k = QLabel(kind.upper())
            k.setObjectName("sub")
            cl.addWidget(k)
            m = QLabel(main)
            m.setWordWrap(True)
            m.setFixedWidth(QR_W - 28)
            m.setTextInteractionFlags(Qt.TextSelectableByMouse)
            m.setTextFormat(Qt.PlainText)
            cl.addWidget(m)
            for label, value in fields:
                f = QLabel(f"<span style='color:{theme.hexc('dim')}'>{label}:</span> {html_escape(value)}")
                f.setTextInteractionFlags(Qt.TextSelectableByMouse)
                cl.addWidget(f)
            btns = []
            if url:
                o = QPushButton(tr("Open"))
                o.setObjectName("primary")
                o.clicked.connect(lambda _=False, u=url: (QDesktopServices.openUrl(QUrl(u)), self.close()))
                btns.append(o)
            pw = dict(fields).get(tr("Password"))
            if pw:
                b = QPushButton(tr("Copy password"))
                b.setObjectName("primary")
                b.clicked.connect(lambda _=False, v=pw: QGuiApplication.clipboard().setText(v))
                btns.append(b)
            b = QPushButton(tr("Copy"))
            b.clicked.connect(lambda _=False, v=c["text"], b=b: (QGuiApplication.clipboard().setText(v), b.setText(tr("Copied"))))
            btns.append(b)
            self.buttons(cl, *btns)
            lay.addWidget(card)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.close)
        self.buttons(lay, close)


def html_escape(t):
    import html as _h
    return _h.escape(str(t))


class QrScanOverlay(QWidget):
    """Read QR code on screen: a still picture of one screen with the codes on it lit up. Click one to read it,
    or drag a box around one. Esc cancels."""

    def __init__(self, screen, shot, codes, done):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        from convertanny_core.qr_overlay_geometry import screen_rect
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.shot, self.done = shot, done
        dpr = shot.devicePixelRatio() or 1.0
        self.dpr = dpr
        self.codes = [dict(c, view=screen_rect(c["rect"], dpr)) for c in codes]
        self.hover, self.drag_from, self.drag_to, self.msg = None, None, None, ""
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(screen.geometry())

    def _hint(self, any_codes):
        if self.msg:
            return self.msg
        return (tr("Click a QR code to read it — or drag a box around one. Esc to cancel.") if any_codes
                else tr("No QR code found here. Drag a box around one, or press Esc."))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawPixmap(self.rect(), self.shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))
        accent = QColor(theme.hexc("accent"))
        for i, c in enumerate(self.codes):
            v = c["view"]
            src = QRectF(v.x() * self.dpr, v.y() * self.dpr, v.width() * self.dpr, v.height() * self.dpr)
            p.drawPixmap(v, self.shot, src)                       # the code itself stays bright
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(accent, 5 if i == self.hover else 3))
            p.drawRoundedRect(v, 10, 10)
        if self.drag_from is not None and self.drag_to is not None:
            box = QRectF(self.drag_from, self.drag_to).normalized()
            src = QRectF(box.x() * self.dpr, box.y() * self.dpr, box.width() * self.dpr, box.height() * self.dpr)
            p.drawPixmap(box, self.shot, src)
            p.setPen(QPen(accent, 2, Qt.DashLine))
            p.drawRect(box)
        text = self._hint(any(True for _ in self.codes))
        f = p.font()
        f.setPointSizeF(10.5)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        fm = QFontMetrics(f)
        w = fm.horizontalAdvance(text) + 40
        pill = QRectF((self.width() - w) / 2, 28, w, 40)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(28, 28, 30, 235))
        p.drawRoundedRect(pill, 20, 20)
        p.setPen(QColor("#ffffff"))
        p.drawText(pill, Qt.AlignCenter, text)

    def _at(self, pos):
        from convertanny_core.qr_overlay_geometry import hit_test
        return hit_test(self.codes, pos)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.drag_from is not None and (pos - self.drag_from).manhattanLength() > 6:
            self.drag_to = pos
        h = self._at(pos)
        if h != self.hover:
            self.hover = h
            self.setCursor(Qt.PointingHandCursor if h is not None else Qt.CrossCursor)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.done(None)
            return
        self.drag_from, self.drag_to, self.msg = e.position(), None, ""

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self.drag_from is None:
            return
        if self.drag_to is None:                                  # a click
            i = self._at(e.position())
            self.drag_from = None
            if i is not None:
                self.done([self.codes[i]])
            return
        box = QRectF(self.drag_from, self.drag_to).normalized()
        self.drag_from = self.drag_to = None
        crop = self.shot.copy(QRectF(box.x() * self.dpr, box.y() * self.dpr, box.width() * self.dpr,
                                     box.height() * self.dpr).toRect()).toImage()
        codes = []
        for k in (1, 2, 3):                                      # small codes read better a bit bigger
            img = crop if k == 1 else crop.scaled(crop.width() * k, crop.height() * k, Qt.KeepAspectRatio,
                                                   Qt.SmoothTransformation)
            try:
                codes = find_codes(img)
            except Exception as ex:
                winsys.log(f"read qr: {ex}")
            if codes:
                break
        if codes:
            self.done(codes)
        else:
            self.msg = tr("No QR code in that box. Try again, or press Esc.")
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.done(None)


def _time_left(expires) -> str:
    from convertanny_core.expiry import expiry_label
    return expiry_label(expires, tr)


class ShareQR(FrontDialog):
    """Tray → Send to phone — show QR code: an internet link made earlier, until it runs out."""

    def __init__(self, item, title=None, new=None):
        super().__init__(None)
        from PySide6.QtWidgets import QLayout
        self.item = item
        self.setWindowTitle(f"{APP} — " + tr("Send to phone"))
        self.setWindowIcon(app_icon())
        self.setStyleSheet(i18n.css(DIALOG_CSS))
        self.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        lay.setSizeConstraint(QLayout.SetFixedSize)
        self.header(lay, title or tr("Internet link"), item["name"])
        qr = QrBox()
        qr.show_code(item["url"])
        lay.addWidget(qr, 0, Qt.AlignHCenter)
        self.left = QLabel()
        self.left.setObjectName("sub")
        self.left.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.left)
        link = QLabel(item["url"])
        link.setObjectName("sub")
        link.setWordWrap(True)
        link.setFixedWidth(QR_W)
        link.setTextInteractionFlags(Qt.TextSelectableByMouse)
        link.setAlignment(Qt.AlignCenter)
        lay.addWidget(link, 0, Qt.AlignHCenter)
        b = QPushButton(tr("Copy link"))
        b.setObjectName("primary")
        b.clicked.connect(lambda: QGuiApplication.clipboard().setText(item["url"]))
        c = QPushButton(tr("Close"))
        c.clicked.connect(self.close)
        if new is not None:                                # already shared: or make a fresh link instead
            n = QPushButton(tr("New link"))
            n.setToolTip(tr("Share it again with a new link"))
            n.clicked.connect(lambda: (self.close(), QTimer.singleShot(0, new)))
            self.buttons(lay, b, n, c)
        else:
            self.buttons(lay, b, c)
        self._t = QTimer(self, interval=20000, timeout=self._tick)
        self._t.start()
        self._tick()

    def sharing(self):
        return bool(self.item.get("path")) and Path(self.item["path"]).exists()

    def stop_question(self):
        return tr("Stop sharing deletes the copy from your cloud, so the link stops working. Keep sharing leaves "
                  "it until its time runs out.")

    def stop_sharing(self):
        stop_cloud_share(self.item["path"])

    def closeEvent(self, e):
        if not self.leave_ok(e):
            return
        super().closeEvent(e)

    def _tick(self):
        import time
        if not self.item.get("expires"):
            self.left.setText(tr("Kept until you delete it"))
            return
        if self.item["expires"] <= time.time():
            self.close()                                   # the link has run out
            return
        self.left.setText(_time_left(self.item["expires"]))


class InternetShare(FrontDialog):
    """Send to phone through a temporary internet link: upload, then a QR code to open it on any phone."""
    MINUTES = [60, 12 * 60, 24 * 60, 72 * 60]     # what the file services offer (none deletes sooner than an hour)

    def __init__(self, paths):
        super().__init__(None)
        from PySide6.QtWidgets import QLayout, QProgressBar
        self.setWindowTitle(f"{APP} — " + tr("Send to phone"))
        self.setWindowIcon(app_icon())
        self.setStyleSheet(i18n.css(DIALOG_CSS))
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.paths = [Path(x) for x in paths]
        lay = QVBoxLayout(self)
        lay.setSizeConstraint(QLayout.SetFixedSize)
        what = self.paths[0].name if len(self.paths) == 1 and self.paths[0].is_file() else \
            tr("{n} files (as one ZIP)", n=len(self.paths)) if len(self.paths) > 1 else self.paths[0].name + ".zip"
        if len(self.paths) == 1 and self.paths[0].is_file() and self.paths[0].suffix.lower() in BLOCKED_UPLOAD_EXT:
            what = self.paths[0].stem + ".zip — " + tr("programs are sent inside a ZIP, because file services refuse them")
        self.header(lay, tr("Internet link"), what)
        self.qr = QrBox()
        self.qr.idle(tr("The QR code appears here"))
        lay.addWidget(self.qr, 0, Qt.AlignHCenter)
        self.link = QLabel()
        self.link.setObjectName("sub")
        self.link.setWordWrap(True)
        self.link.setFixedWidth(QR_W)
        self.link.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.link.setAlignment(Qt.AlignCenter)
        self.link.hide()
        lay.addWidget(self.link, 0, Qt.AlignHCenter)
        form = QFormLayout()
        self.host = QComboBox()
        for key, label, _m in HOST_CHOICES:
            self.host.addItem(tr(label), key)
        self.host.setCurrentIndex(max(0, self.host.findData(settings().value("share_host", "auto"))))
        form.addRow(tr("Service"), self.host)
        self.hours = QComboBox()
        form.addRow(tr("Keep the link for"), self.hours)
        lay.addLayout(form)
        self.ads = QLabel(tr("tmpfiles.org's download page shows ads and pop-ups, with fake Download buttons that open "
                             "other sites. ConvertANNY gives the direct file link, but tell whoever opens it not to tap "
                             "anything else on that page."))
        self.ads.setWordWrap(True)
        self.ads.setFixedWidth(QR_W)
        self.ads.setStyleSheet(f"color:{theme.hexc('danger')};font-size:9pt")
        lay.addWidget(self.ads)
        self.host.currentIndexChanged.connect(self._host_changed)
        self._host_changed()
        note = QLabel(tr("The file is uploaded to a free temporary file service and deleted automatically after about "
                         "that time. Anyone with the link can download it until then."))
        note.setObjectName("note")
        note.setWordWrap(True)
        note.setFixedWidth(QR_W)
        lay.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setFixedWidth(QR_W)
        self.status.hide()
        lay.addWidget(self.status)
        self.go = QPushButton(tr("Upload and make a link"))
        self.go.setObjectName("primary")
        self.go.clicked.connect(self._start)
        self.copy = QPushButton(tr("Copy link"))
        self.copy.setObjectName("primary")
        self.copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.url))
        self.copy.hide()
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.close)
        self.buttons(lay, self.go, self.copy, close)
        self._cancel = False
        self._frac = 0.0
        self._result = None
        self._poll = QTimer(self, interval=150, timeout=self._update)

    def _host_changed(self, *_):
        key = self.host.currentData()
        times = next(m for k, _l, m in HOST_CHOICES if k == key)
        want = int(self.hours.currentData() or settings().value("share_minutes", 60))
        self.hours.clear()
        for m in times:
            self.hours.addItem(tr("{n} minutes", n=m) if m < 60 else tr("{n} hour(s)", n=m // 60), m)
        self.hours.setCurrentIndex(max(0, self.hours.findData(min(times, key=lambda m: abs(m - want)))))
        self.ads.setVisible(key == "tmpfiles.org")

    def _start(self):
        settings().setValue("share_minutes", self.hours.currentData())
        settings().setValue("share_host", self.host.currentData())
        self.shared_name = self.paths[0].name if len(self.paths) == 1 else tr("{n} files", n=len(self.paths))
        self.go.setEnabled(False)
        self.hours.setEnabled(False)
        self.host.setEnabled(False)
        self.status.hide()
        self.qr.busy(tr("Uploading…"))
        hours = self.hours.currentData()
        only = self.host.currentData()

        def work():
            try:
                src = self.paths[0]
                # free file services refuse programs and scripts (.exe, .msi…): those travel inside a ZIP
                blocked = src.is_file() and src.suffix.lower() in BLOCKED_UPLOAD_EXT
                if len(self.paths) > 1 or src.is_dir() or blocked:
                    import tempfile
                    import zipfile
                    tmp = Path(tempfile.mkdtemp(prefix="convertanny-share-"))
                    src = tmp / ((self.paths[0].stem if blocked else self.paths[0].name if len(self.paths) == 1
                                  else "ConvertANNY") + ".zip")         # "Setup.zip", not "Setup.exe.zip": some services refuse that
                    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
                        for it in self.paths:
                            for f in ([it] if it.is_file() else [x for x in it.rglob("*") if x.is_file()]):
                                z.write(f, str(f.relative_to(it.parent)))
                link, host = upload_temporary(src, hours, lambda f: setattr(self, "_frac", f), lambda: self._cancel,
                                              only=only)
                self._result = ("ok", link, host)
            except Exception as e:
                self._result = ("err", str(e), "")
        threading.Thread(target=work, daemon=True).start()
        self._poll.start()

    def _update(self):
        if self._result is None:
            if self._frac > 0:
                self.qr.set_text(tr("Uploading…") + f"  {int(self._frac * 100)}%")
            return
        self._poll.stop()
        kind, val, host = self._result
        if kind == "err":
            self.qr.idle(tr("No link"))
            self.status.show()
            self.status.setText(f"<span style='color:{theme.hexc('danger')}'>" + val.replace("\n", "<br>") + "</span>")
            self.go.setEnabled(True)
            self.hours.setEnabled(True)
            self.host.setEnabled(True)
            return
        self.url = val
        winsys.log(f"send to phone (internet): uploaded to {host}")
        remember_share_link(val, self.shared_name, int(self.hours.currentData()), share_key(self.paths))
        self.status.show()
        self.status.setText("<b>" + tr("Scan with your phone's camera") + "</b> — " +
                            tr("works on any network, even mobile data."))
        self.qr.show_code(val)
        self.link.setText(val)
        self.link.show()
        self.go.hide()
        self.copy.show()

    def closeEvent(self, e):
        self._cancel = True
        super().closeEvent(e)


class SendChooser(FrontDialog):
    """How to send to the phone: Quick Share, an internet link, or the same Wi-Fi."""

    def __init__(self, paths):
        super().__init__(None)
        from PySide6.QtWidgets import QLayout
        self.setWindowTitle(f"{APP} — " + tr("Send to phone"))
        self.setWindowIcon(app_icon())
        self.setStyleSheet(i18n.css(DIALOG_CSS) +
                           f"QPushButton#way{{text-align:left;padding:0;border-radius:10px;background:{theme.hexc('surface')};"
                           f"border:1px solid {theme.hexc('border')}}}"
                           f"QPushButton#way:hover{{border:1px solid {theme.hexc('accent')}}}"
                           f"QPushButton#way:disabled{{background:transparent}}"
                           "QLabel#waytitle{font:700 10.5pt 'Segoe UI';background:transparent}"
                           f"QLabel#waydesc{{color:{theme.hexc('dim')};font:9pt 'Segoe UI';background:transparent}}")
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setSizeConstraint(QLayout.SetFixedSize)
        what = Path(paths[0]).name if len(paths) == 1 else tr("{n} files", n=len(paths))
        lay.addWidget(QLabel(f"<b>{tr('How do you want to send it?')}</b><br>"
                             f"<span style='color:{theme.hexc('dim')}'>{what}</span>"))
        self.choice = None
        last = settings().value("share_way", "quick")
        last = "internet" if last == "iphone" else last
        clouds = cloud_folders()
        refresh_clouds()
        warm_lan_ips()                                     # ready if Same Wi-Fi is chosen
        cloud_names = ", ".join(dict.fromkeys(n.split(" (")[0] for n, _ in clouds))
        from PySide6.QtCore import QSize as _QS
        for key, icon, title, desc, ok in (
                ("quick", "quickshare", tr("Quick Share"), tr("Straight to a nearby Android phone. No network setup."), True),
                ("internet", "link", tr("Internet link"), tr("Uploads to a free temporary file service. Any phone, any network."), True),
                ("pclink", "pclink", tr("Link from this PC"), tr("A link that works anywhere, served from this PC while the window is open. Nothing is uploaded."), True),
                ("cloud", "cloud", tr("Cloud link"),
                 tr("A share link from your {cloud}. Works even when this PC is off.", cloud=cloud_names) if clouds
                 else tr("A share link from OneDrive, Google Drive, iCloud Drive, Dropbox or Box. Works even when this PC is off."), True),
                ("bluetooth", "bluetooth", tr("Bluetooth"), tr("Slower, but needs no network. Android phones paired to this PC."), True),
                ("wifi", "wifi", tr("Same Wi-Fi"), tr("The phone downloads directly from this PC. Routers and firewalls can block it."), True)):
            b = QPushButton()
            b.setObjectName("way")
            b.setAutoDefault(False)
            b.setEnabled(ok)
            b.setMinimumWidth(440)
            row = QHBoxLayout(b)
            row.setContentsMargins(14, 10, 14, 10)
            row.setSpacing(14)
            ic = QLabel()
            ic.setPixmap(nav_icon(icon).pixmap(_QS(26, 26), QIcon.Selected if ok else QIcon.Normal))
            ic.setFixedSize(28, 28)
            col = QVBoxLayout()
            col.setSpacing(1)
            t = QLabel(title)
            t.setObjectName("waytitle")
            d = QLabel(desc)
            d.setObjectName("waydesc")
            d.setWordWrap(True)
            col.addWidget(t)
            col.addWidget(d)
            for w in (ic, t, d):
                w.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.addWidget(ic, 0, Qt.AlignVCenter)
            row.addLayout(col, 1)
            b.setMinimumHeight(row.sizeHint().height() + 4)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            lay.addWidget(b)

    def _pick(self, key):
        self.choice = key
        settings().setValue("share_way", key)
        self.accept()


CLOUD_APPS = [("OneDrive", "https://www.microsoft.com/microsoft-365/onedrive/download"),
              ("Google Drive", "https://www.google.com/drive/download/"),
              ("iCloud Drive", "https://apps.microsoft.com/detail/9pktq5699m62"),
              ("Dropbox", "https://www.dropbox.com/install"),
              ("Box", "https://www.box.com/resources/downloads/drive")]
_CLOUDS = None          # [(name, folder)] found in the background (looking can be slow: drives, network)


def _detect_clouds() -> list:
    """Cloud storage apps set up on this PC and their synced folders: OneDrive, Google Drive, iCloud Drive,
    Dropbox and Box."""
    out, seen = [], set()

    def add(name, folder):
        try:
            if folder and Path(folder).is_dir() and os.path.normcase(str(folder)) not in seen:
                seen.add(os.path.normcase(str(folder)))
                out.append((name, Path(folder)))
        except OSError:
            pass
    for env, name in (("OneDriveConsumer", "OneDrive"), ("OneDriveCommercial", "OneDrive (work)"), ("OneDrive", "OneDrive")):
        add(name, os.environ.get(env))
    # Google Drive for desktop: its settings say which drive letter it mounts ("My Drive" inside)
    gdrive = None
    if winsys.IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\DriveFS") as k:
                prefs = json.loads(winreg.QueryValueEx(k, "PerAccountPreferences")[0])
            for acc in prefs.get("per_account_preferences", []):
                mp = (acc.get("value") or {}).get("mount_point_path")
                if mp:
                    gdrive = Path((mp.rstrip(":\\") + ":\\") if len(mp.rstrip(":\\")) == 1 else mp) / "My Drive"
                    break
        except (OSError, ValueError, TypeError):
            pass
        if gdrive is None or not gdrive.is_dir():   # otherwise: the drive Google Drive puts up (it's labelled
            import ctypes                           # "Google Drive"); never network or CD drives
            gdrive = None
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(3, 26):
                if not mask & (1 << i):
                    continue
                root = f"{chr(65 + i)}:\\"
                if ctypes.windll.kernel32.GetDriveTypeW(root) not in (3, 4):
                    continue
                try:
                    label = ctypes.create_unicode_buffer(261)
                    ok = ctypes.windll.kernel32.GetVolumeInformationW(root, label, 261, None, None, None, None, 0)
                    if (ok and "google" in label.value.lower()) or Path(root, "My Drive").is_dir():
                        mine = Path(root, "My Drive")
                        if not mine.is_dir():       # "My Drive" in another language: the first ordinary folder
                            mine = next((d for d in sorted(Path(root).iterdir()) if d.is_dir() and not d.name.startswith(
                                (".", "$")) and d.name not in ("Shared drives", "Other computers")), None)
                        if mine is not None:
                            gdrive = mine
                            break
                except OSError:
                    continue
    add("Google Drive", gdrive)
    add("Google Drive", Path.home() / "My Drive")                  # Google Drive set to mirror files into a folder
    add("Google Drive", Path.home() / "Google Drive")              # the older Backup and Sync folder
    add("iCloud Drive", Path.home() / "iCloudDrive")
    for base in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA")):   # Dropbox writes where its folder is
        try:
            info = json.loads((Path(base) / "Dropbox" / "info.json").read_text(encoding="utf-8")) if base else {}
        except (OSError, ValueError):
            info = {}
        for kind, name in (("personal", "Dropbox"), ("business", "Dropbox (work)")):
            add(name, (info.get(kind) or {}).get("path"))
    add("Box", Path.home() / "Box")
    return out


def cloud_folders(wait=False) -> list:
    """The clouds found so far (looked for in the background, so opening a window never waits for drives)."""
    global _CLOUDS
    if _CLOUDS is None and wait:
        _CLOUDS = _detect_clouds()
    return list(_CLOUDS or [])


def refresh_clouds():
    def run():
        global _CLOUDS
        try:
            _CLOUDS = _detect_clouds()
        except Exception as e:
            winsys.log(f"clouds: {e}")
    threading.Thread(target=run, daemon=True).start()


def cloud_shares() -> list:
    return _jload("cloud_shares", []) if "_jload" in globals() else []


def remember_cloud_share(path, expires, key="", url="", name=""):
    old = next((x for x in cloud_shares() if x.get("path") == str(path)), {})
    item = dict(old, path=str(path), expires=expires)
    for k, v in (("key", key), ("url", url), ("name", name)):
        if v:
            item[k] = v
    lst = [x for x in cloud_shares() if x.get("path") != str(path)] + [item]
    settings().setValue("cloud_shares", json.dumps(lst, ensure_ascii=False))


def stop_cloud_share(path):
    """Stop sharing now: the cloud copy goes (to the cloud's recycle bin), so its link stops working."""
    try:
        Path(path).unlink(missing_ok=True)
        winsys.log(f"cloud link stopped: {Path(path).name}")
    except OSError as e:
        winsys.log(f"cloud link: couldn't delete {path}: {e}")
        return
    settings().setValue("cloud_shares", json.dumps([x for x in cloud_shares() if x.get("path") != str(path)],
                                                   ensure_ascii=False))


def live_share(kind, paths):
    """A link made earlier for these same files that still works: {"url", "name", "expires"} or None."""
    key = share_key(paths)
    if kind == "internet":
        return next((x for x in share_links() if x.get("key") == key), None)
    for x in cloud_shares():
        if x.get("key") == key and x.get("url") and (not x.get("expires") or x["expires"] > time.time()) \
                and Path(x["path"]).exists():
            return {"url": x["url"], "name": x.get("name") or Path(x["path"]).name, "expires": x.get("expires", 0),
                    "path": x["path"]}
    return None


def clean_cloud_shares():
    """Delete cloud-link copies whose time is up (they go to the cloud's own recycle bin)."""
    keep = []
    for x in cloud_shares():
        if x.get("expires") and x["expires"] <= time.time():
            try:
                Path(x["path"]).unlink(missing_ok=True)
                winsys.log(f"cloud link ended: {Path(x['path']).name}")
            except OSError as e:
                winsys.log(f"cloud link: couldn't delete {x['path']}: {e}")
                keep.append(x)
        else:
            keep.append(x)
    if len(keep) != len(cloud_shares()):
        settings().setValue("cloud_shares", json.dumps(keep, ensure_ascii=False))


_CLOUD_LINK = ("1drv.ms/", "onedrive.live.com/", "sharepoint.com/", "drive.google.com/", "docs.google.com/",
               "icloud.com/", "dropbox.com/", "db.tt/", "box.com/")


class CloudShare(FrontDialog):
    """Send to phone → Cloud link: a copy goes into your OneDrive or Google Drive, and its own Share window gives the
    link (trusted, no ads, works when this PC is off). ConvertANNY shows the link you copy as a QR code."""
    KEEP = [(60, "1 hour"), (12 * 60, "12 hours"), (24 * 60, "1 day"), (3 * 24 * 60, "3 days"), (7 * 24 * 60, "1 week"),
            (0, "Keep it")]

    def __init__(self, paths):
        super().__init__(None)
        from PySide6.QtWidgets import QLayout
        self.setWindowTitle(f"{APP} — " + tr("Send to phone"))
        self.setWindowIcon(app_icon())
        self.setStyleSheet(i18n.css(DIALOG_CSS))
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.paths = [Path(x) for x in paths]
        self.clouds = cloud_folders(wait=True)
        refresh_clouds()                                   # anything set up since: ready for next time
        lay = QVBoxLayout(self)
        lay.setSizeConstraint(QLayout.SetFixedSize)
        what = self.paths[0].name if len(self.paths) == 1 and self.paths[0].is_file() else \
            tr("{n} files (as one ZIP)", n=len(self.paths)) if len(self.paths) > 1 else self.paths[0].name + ".zip"
        self.header(lay, tr("Cloud link"), what)
        self.qr = QrBox()
        self.qr.idle(tr("The QR code appears here"))
        lay.addWidget(self.qr, 0, Qt.AlignHCenter)
        self.link = QLabel()
        self.link.setObjectName("sub")
        self.link.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.link.setAlignment(Qt.AlignCenter)
        self.link.setWordWrap(True)
        self.link.setFixedWidth(QR_W)
        self.link.hide()
        lay.addWidget(self.link, 0, Qt.AlignHCenter)
        form = QFormLayout()
        self.cloud = QComboBox()
        for name, folder in self.clouds:
            self.cloud.addItem(name, str(folder))
        have = {n.split(" (")[0] for n, _ in self.clouds}
        missing = [(n, url) for n, url in CLOUD_APPS if n not in have]
        if missing:                                   # the others: a quick way to get them
            if self.clouds:
                self.cloud.insertSeparator(self.cloud.count())
            for n, url in missing:
                self.cloud.addItem(tr("{cloud} — not set up on this PC", cloud=n), "get:" + url)
        self.cloud.setCurrentIndex(max(0, self.cloud.findText(settings().value("cloud_last", ""))))
        self.cloud.currentIndexChanged.connect(self._cloud_changed)
        form.addRow(tr("Cloud"), self.cloud)
        self.keep = QComboBox()
        for m, label in self.KEEP:
            self.keep.addItem(tr(label), m)
        self.keep.setCurrentIndex(max(0, self.keep.findData(int(settings().value("cloud_keep", 24 * 60)))))
        form.addRow(tr("Delete it after"), self.keep)
        lay.addLayout(form)
        note = QLabel(tr("A copy goes into a “ConvertANNY shares” folder in your cloud, and the cloud's own Share window "
                         "opens: choose who can open it and copy the link. The link works even when this PC is off."))
        note.setObjectName("note")
        note.setWordWrap(True)
        note.setFixedWidth(QR_W)
        lay.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setFixedWidth(QR_W)
        lay.addWidget(self.status)
        self.go = QPushButton(tr("Make a link"))
        self.go.setObjectName("primary")
        self.go.clicked.connect(self._start)
        self._note = note
        self._cloud_changed()
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.close)
        self.buttons(lay, self.go, close)
        self.dest = None
        self._copied = None
        self._clip_start = ""
        self._shared = None
        self._closed = False
        self._poll = QTimer(self, interval=400, timeout=self._update)

    def sharing(self):
        return self.dest is not None and Path(self.dest).exists()

    def stop_question(self):
        return tr("Stop sharing deletes the copy from {cloud}, so the link stops working. Keep sharing leaves it "
                  "until the time you chose.", cloud=self.cloud.currentText())

    def stop_sharing(self):
        stop_cloud_share(self.dest)

    def closeEvent(self, e):
        if not self.leave_ok(e):
            return
        self._closed = True
        super().closeEvent(e)

    def _cloud_changed(self, *_):
        data = str(self.cloud.currentData() or "")
        get = data.startswith("get:")
        name = self.cloud.currentText().split(" — ")[0]
        self.keep.setEnabled(not get)
        self.go.setText(tr("Get {cloud}", cloud=name) if get else tr("Make a link"))
        self._note.setText(tr("{cloud} isn't set up on this PC. Install it and sign in, then choose it here.", cloud=name)
                           if get else tr("A copy goes into a “ConvertANNY shares” folder in your cloud, and the cloud's "
                                          "own Share window opens: choose who can open it and copy the link. The link "
                                          "works even when this PC is off."))

    def _start(self):
        data = str(self.cloud.currentData() or "")
        if data.startswith("get:"):
            QDesktopServices.openUrl(QUrl(data[4:]))
            refresh_clouds()
            return
        settings().setValue("cloud_last", self.cloud.currentText())
        settings().setValue("cloud_keep", self.keep.currentData())
        self.go.setEnabled(False)
        self.cloud.setEnabled(False)
        self.keep.setEnabled(False)
        folder = Path(self.cloud.currentData()) / "ConvertANNY shares"
        self.status.setText(tr("Copying to {cloud}…", cloud=self.cloud.currentText()))
        self._clip_start = QGuiApplication.clipboard().text()

        def work():
            try:
                folder.mkdir(parents=True, exist_ok=True)
                src = self.paths[0]
                if len(self.paths) == 1 and src.is_file():
                    dest = engine.unique_path(folder / src.name)
                    shutil.copy2(src, dest)
                else:
                    import zipfile
                    dest = engine.unique_path(folder / ((src.name if len(self.paths) == 1 else "ConvertANNY") + ".zip"))
                    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                        for it in self.paths:
                            for f in ([it] if it.is_file() else [x for x in it.rglob("*") if x.is_file()]):
                                z.write(f, str(f.relative_to(it.parent)))
                self._copied = ("ok", dest)
            except Exception as e:
                self._copied = ("err", str(e))
        threading.Thread(target=work, daemon=True).start()
        self._poll.start()

    def _update(self):
        if self._copied is not None:
            kind, val = self._copied
            self._copied = None
            if kind == "err":
                self.qr.idle(tr("No link"))
                self.status.setText(f"<span style='color:{theme.hexc('danger')}'>{val}</span>")
                self._poll.stop()
                return
            self.dest = val
            m = int(self.keep.currentData())
            remember_cloud_share(val, time.time() + m * 60 if m else 0, share_key(self.paths),
                                 name=self.paths[0].name if len(self.paths) == 1 else Path(val).name)
            winsys.log(f"send to phone (cloud): {val}")
            self.status.setText("")
            self.qr.busy(tr("Waiting for {cloud} to take the file…", cloud=self.cloud.currentText()))
            cloud = self.cloud.currentText()

            def ask():
                # the cloud's own right-click entry. Never the plain Windows "Share" (that's Quick Share / Nearby).
                # OneDrive only offers "Copy link" once the file has synced, so keep trying for a while.
                names = ["Copy link", "Copy Dropbox link", "Copy Shared Link", "Share with Google Drive",
                         "Share with iCloud", "Share with Dropbox", "Share with Box", "iCloud Drive"]
                ok = False
                for _ in range(20):
                    try:
                        ok = winsys.invoke_shell_verb([str(val)], *names)
                    except Exception as e:
                        winsys.log(f"cloud share verb: {e}")
                    if ok or self._closed:
                        break
                    time.sleep(2)
                self._shared = ok
            self._shared = None
            threading.Thread(target=ask, daemon=True).start()
            return
        if self._shared is not None:
            ok, self._shared = self._shared, None
            self.qr.busy(tr("Waiting for the link…"))
            if ok:
                self.status.setText(tr("In {cloud}'s Share window, choose who can open it and copy the link. "
                                       "It appears here as a QR code.", cloud=self.cloud.currentText()))
            else:
                winsys.reveal(str(self.dest))
                self.status.setText(tr("Right-click the file in the window that opened, choose Share (or Copy link), "
                                       "and copy the link. It appears here as a QR code."))
        text = QGuiApplication.clipboard().text().strip()
        if self.dest is not None and text != self._clip_start and text.startswith("http") and any(
                c in text for c in _CLOUD_LINK):
            self._poll.stop()
            self._show(text)

    def _show(self, url):
        self.url = url
        if self.dest is not None:
            m = int(self.keep.currentData())
            remember_cloud_share(self.dest, next((x["expires"] for x in cloud_shares() if x.get("path") == str(self.dest)),
                                                 time.time() + m * 60 if m else 0), url=url)
        self.status.setText("<b>" + tr("Scan with your phone's camera") + "</b> — " +
                            tr("works on any network, even mobile data."))
        self.qr.show_code(url)
        self.link.setText(url)
        self.link.show()
        self.go.setText(tr("Copy link"))
        self.go.setEnabled(True)
        try:
            self.go.clicked.disconnect()
        except Exception:
            pass
        self.go.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.url))
        self.adjustSize()


def shutil_copy(fi, fo):
    while chunk := fi.read(1024 * 1024):
        fo.write(chunk)


def _human(p: Path) -> str:
    try:
        n = p.stat().st_size if p.is_file() else sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return ""
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024


# ============================================================================
# File actions (don't use the engine)
# ============================================================================
class Actions:
    def __init__(self, app: "ConvertANNYApp"):
        self.app = app

    def ops(self, paths):
        A = lambda i, l, f, h="": engine.Op(i, l, f, group="action", multi=True, hint=h)
        return [
            A("copy", "Copy", self.copy, "to clipboard"),  # labels are translated when drawn
            A("path", "Copy path", self.copy_path),
            A("move", "Move to…", self.move),
            A("copyto", "Copy to…", self.copy_to),
            A("terminal", "Terminal", self.terminal, "open here"),
            A("float", "Float", self.float),
            A("reveal", "Show", self.reveal, "in Explorer"),
            A("openwith", "Open with…", self.open_with),
            A("rename", "Rename…", self.rename, "several at once"),
            A("hash", "Checksum", self.checksum, "SHA-256"),
            A("unblock", "Unblock", self.unblock, "downloaded files"),
            A("phone", "Send to phone", self.phone),
            A("shred", "Shred…", self.shred, "can't be undone"),
        ] + ([A("readqr", "Read QR code", self.read_qr)]
             if paths and all(engine.EXT_CATEGORY.get(engine.ext_of(x)) == "image" for x in paths) else [])

    def read_qr(self, paths, p):
        """What the QR codes in these pictures say."""
        def work(state):
            out = []
            for f in paths:
                out += find_codes_in_file(f)
            return out

        def finish(codes):
            if codes:
                self.app.show_qr_result(codes)
            else:
                self.app.toast.show_msg(tr("Read QR code"), tr("No QR code found in this picture."), "err", 5000)
        self._background(tr("Read QR code"), Path(paths[0]).name, work, finish)

    def rename(self, paths, p):
        dlg = BatchRenameDialog(paths, icon=app_icon(), css=i18n.css(DIALOG_CSS))
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            done = dlg.apply()
        except OSError as e:
            self.app.toast.show_msg(tr("Couldn't rename"), str(e), "err", 8000)
            return
        winsys.log("renamed: " + "; ".join(f"{Path(o).name} -> {Path(n).name}" for o, n in done[:50]))
        self.app.toast.show_result(tr("Renamed {n} files", n=len(done)), [n for _, n in done])

    def _background(self, title, name, work, finish, progress=None):
        """Run `work(state)` off the main thread so the wheel and floats stay responsive; a card shows it's busy
        (with `progress(state)` text) and has a Cancel button that sets state["stop"]. `finish(result)` runs here."""
        state, result = {"stop": False}, {}
        card = self.app.toast.show_busy(title, name, lambda: state.update(stop=True))

        def run():
            try:
                result["ok"] = work(state)
            except Exception as e:
                result["err"] = e

        def check():
            if not result:
                if progress is not None and card in self.app.toast.cards:
                    text = progress(state)
                    if text:
                        card.body.setText(text)
                QTimer.singleShot(200, check)
                return
            if card in self.app.toast.cards:
                card.close_card()
            if "err" in result:
                winsys.log(f"{title}: {result['err']}")
                self.app.toast.show_msg(title, str(result["err"]), "err", 8000)
                return
            finish(result["ok"])
        threading.Thread(target=run, daemon=True).start()
        QTimer.singleShot(200, check)

    def unblock(self, paths, p):
        """Remove Windows' "This file came from another computer" mark (folders: everything inside)."""
        name = Path(paths[0]).name if len(paths) == 1 else tr("{n} files", n=len(paths))

        def work(st):
            return winsys.unblock(paths, progress=lambda n: st.update(n=n), stop=lambda: st["stop"])

        def finish(r):
            n, blocked, failed = r
            if failed:
                self.app.toast.show_msg(tr("Unblock"), tr("{n} files couldn't be unblocked", n=failed), "err", 6000)
            elif blocked:
                self.app.toast.show_msg(tr("Unblocked {n} files", n=blocked), tr("Windows won't warn about them any more."), "ok", 5000)
            else:
                self.app.toast.show_msg(tr("Unblock"), tr("Nothing was blocked ({n} files checked)", n=n), "info", 5000)
        self._background(tr("Unblock") + "…", name, work, finish,
                         lambda st: tr("{n} files checked", n=f"{st['n']:,}") if st.get("n") else None)

    def checksum(self,paths,p):
        from convertanny_core.checksums import sha256_batch
        files=[Path(value) for value in paths if Path(value).is_file()]
        if not files:
            self.app.toast.show_msg(tr('Checksum'),tr('Pick files, not folders'),'err',4000)
            return
        clipboard=QGuiApplication.clipboard().text().strip().lower()
        title=tr('Checksum');name=files[0].name if len(files)==1 else tr('{n} files',n=len(files))
        def work(state):
            def progress(index,count,done,total,filename):state.update(index=index+1,count=count,done=done,total=total,name=filename)
            return sha256_batch(files,stop=lambda:state['stop'],on_progress=progress)
        def finish(pairs):
            import re
            if re.fullmatch(r'[0-9a-f]{64}',clipboard):
                match=next((path for path,digest in pairs if digest==clipboard),None)
                if match:self.app.toast.show_msg('✓ '+tr('Checksum matches'),tr('{name} is the genuine file.',name=match.name),'ok',10000)
                else:self.app.toast.show_msg('✗ '+tr("Checksum doesn't match"),tr('The copied checksum is different — the file may be damaged or not the original.'),'err',12000)
                return
            text='\n'.join(f'{digest}  {path.name}' for path,digest in pairs)
            QGuiApplication.clipboard().setText(text)
            short=pairs[0][1][:16]+'…' if len(pairs)==1 else tr('{n} files',n=len(pairs))
            self.app.toast.show_msg(tr('SHA-256 copied'),f"{short}<br><small>{tr('Copy a published checksum first to compare it instead.')}</small>",'ok',9000)
        self._background(title,name,work,finish,
                         lambda state:tr('Hashing {name}',name=state['name']) if state.get('name') else None)


    def phone(self, paths, p):
        chooser = SendChooser(paths)
        ok = chooser.exec() == QDialog.Accepted
        choice = chooser.choice if ok else None
        mode = {"wifi": "wifi", "pclink": "tunnel"}.get(choice)
        key = share_key(paths)
        live = getattr(self.app, "_live_phone", {})
        for k, w in list(live.items()):                    # shares kept going: same way again = same window
            try:
                gone = w.ended
            except RuntimeError:
                gone = True
            if gone:
                live.pop(k, None)
        self.app._live_phone = live
        if not ok:
            return
        if (mode, key) in live:
            w = live[(mode, key)]
            w.back = lambda: self.phone(paths, p)
            w.show()
            w.raise_()
            w.activateWindow()
            return
        if chooser.choice == "quick":
            self.quick_share(paths)
            return
        if chooser.choice == "bluetooth":
            self.bluetooth(paths)
            return
        def open_window(w):
            w.back = lambda: self.phone(paths, p)
            self.app._phone_windows = getattr(self.app, "_phone_windows", [])
            self.app._phone_windows.append(w)
            if isinstance(w, PhoneShare):
                self.app._live_phone[(w.mode, key)] = w
            w.show()
            w.raise_()
        if chooser.choice == "pclink":
            self.app._ensure_model("cloudflared", tr("Link from this PC"),
                                   lambda: open_window(PhoneShare(paths, mode="tunnel")))
            return
        if chooser.choice in ("internet", "cloud"):        # already shared and the link still works: the same code
            item = live_share(chooser.choice, paths)
            if item:
                fresh = (lambda: open_window(InternetShare(paths))) if chooser.choice == "internet" else \
                    (lambda: open_window(CloudShare(paths)))
                open_window(ShareQR(item, tr("Internet link") if chooser.choice == "internet" else tr("Cloud link"),
                                    new=fresh))
                return
        if chooser.choice == "cloud":
            open_window(CloudShare(paths))
            return
        open_window(PhoneShare(paths) if chooser.choice == "wifi" else InternetShare(paths))

    def quick_share(self, paths):
        exe = winsys.quick_share_installed()
        ok = False
        if exe:
            try:                                          # the same call Quick Share's own right-click entry makes
                import subprocess
                subprocess.Popen([exe, "--files-from=context-menu", *[str(Path(p)) for p in paths]],
                                 creationflags=engine.NO_WINDOW)
                winsys.log(f"quick share: started with {len(paths)} item(s)")
                ok = True
            except Exception as e:
                winsys.log(f"quick share: {e}")
        if ok:
            self.app.toast.show_msg(tr("Quick Share"), tr("Pick your phone in the Quick Share window, then tap Accept on the phone."), "info", 6000)
            return
        box = QMessageBox()
        box.setWindowTitle(f"{APP} — " + tr("Quick Share"))
        box.setWindowIcon(app_icon())
        box.setStyleSheet(i18n.css(DIALOG_CSS))
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        if exe:
            box.setText(tr("Quick Share is installed but didn't offer to send these files. Opening it — drag the files into its window."))
            box.exec()
            os.startfile(exe)
            winsys.reveal(paths)
            return
        box.setText("<b>" + tr("Quick Share isn't installed") + "</b><br><br>" +
                    tr("It's free from Google and sends files to nearby Android phones (Samsung phones have it built in). "
                       "Install it once, then choose Quick Share again."))
        get = box.addButton(tr("Get Quick Share"), QMessageBox.AcceptRole)
        box.addButton(tr("Close"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is get:
            QDesktopServices.openUrl(QUrl(QUICK_SHARE_URL))

    def bluetooth(self, paths):
        """Windows' own Bluetooth file sender, with the files already chosen (what Send To → Bluetooth does)."""
        exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "fsquirt.exe"
        files = [str(Path(p)) for p in paths if Path(p).is_file()]
        if not exe.exists():
            self.app.toast.show_msg(tr("Bluetooth"), tr("This PC has no Bluetooth file sending."), "err", 6000)
            return
        if not files:
            self.app.toast.show_msg(tr("Bluetooth"), tr("Pick files, not folders"), "err", 5000)
            return
        ok = False
        link = winsys.sendto_entry("bluetooth")
        if link is not None:
            try:                                          # what right-click → Send to → Bluetooth device does
                ok = winsys.drop_files_on(link, files)
            except Exception as e:
                winsys.log(f"bluetooth drop: {e}")
        if not ok:
            import subprocess
            subprocess.Popen([str(exe), *files])
        self.app.toast.show_msg(tr("Bluetooth"), tr("Choose your phone in the Bluetooth window, then accept the files on the phone. "
                                                    "The phone must be paired with this PC first."), "info", 8000)

    def shred(self, paths, p):
        box = QMessageBox()
        box.setWindowTitle(f"{APP} — " + tr("Shred…").rstrip("…"))
        box.setWindowIcon(app_icon())
        box.setStyleSheet(i18n.css(DIALOG_CSS))
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        box.setIcon(QMessageBox.Warning)
        names = "<br>".join("• " + Path(x).name for x in paths[:6]) + ("<br>…" if len(paths) > 6 else "")
        box.setText("<b>" + tr("Destroy {n} item(s) for good?", n=len(paths)) + "</b><br><br>" + names + "<br><br>" +
                    tr("They're overwritten and deleted. They won't go to the Recycle Bin and can't be recovered."))
        go = box.addButton(tr("Shred"), QMessageBox.DestructiveRole)
        box.addButton(tr("Cancel"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            return
        card = self.app.toast.show_busy(tr("Shredding…"), Path(paths[0]).name)
        result = {}

        def work():
            errs = []
            for x in paths:
                try:
                    shred_path(x)
                except Exception as e:
                    errs.append(f"{Path(x).name}: {e}")
            result["errs"] = errs

        def check():
            if not result:
                QTimer.singleShot(200, check)
                return
            if card in self.app.toast.cards:
                card.close_card()
            winsys.log(f"shredded {len(paths)} item(s); errors: {result['errs']}")
            if result["errs"]:
                self.app.toast.show_msg(tr("Some items couldn't be shredded"), "<br>".join(result["errs"][:4]), "err", 10000)
            else:
                self.app.toast.show_msg(tr("Shredded"), tr("{n} item(s) destroyed", n=len(paths)), "ok", 4000)
        threading.Thread(target=work, daemon=True).start()
        QTimer.singleShot(200, check)

    def copy(self, paths, p):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(x) for x in paths])
        QGuiApplication.clipboard().setMimeData(md)
        self.app.toast.show_msg(tr("Copied to clipboard"), tr("{n} item(s) — paste anywhere", n=len(paths)))

    def copy_path(self, paths, p):
        QGuiApplication.clipboard().setText("\n".join(str(Path(x)) for x in paths))
        self.app.toast.show_msg(tr("Path copied"), str(Path(paths[0])) if len(paths) == 1 else tr("{n} paths", n=len(paths)))

    def _pick_dir(self, title):
        location=QFileDialog.getExistingDirectory(None,title,settings().value('last_dir',str(Path(self._first).parent)))
        if location:settings().setValue('last_dir',location)
        return location

    def move(self, paths, p):
        self._transfer(paths,move=True)

    def copy_to(self, paths, p):
        self._transfer(paths,move=False)

    def _transfer(self,paths,*,move):
        self._first=paths[0]
        directory=self._pick_dir(tr('Move to') if move else tr('Copy to'))
        if not directory:return
        from convertanny_core.file_transfer import transfer_items
        name=Path(paths[0]).name if len(paths)==1 else tr('{n} files',n=len(paths))
        title=tr('Move to') if move else tr('Copy to')
        def work(state):
            def progress(done,total,completed):state.update(n=completed,done=done)
            result,failures=transfer_items(paths,directory,move=move,stop=lambda:state['stop'],on_progress=progress)
            return result,failures
        def finish(outcome):
            results,failures=outcome
            if results:self.app.toast.show_result(tr('Moved') if move else tr('Copied'),results)
            if failures:self.app.toast.show_msg(title,tr('{n} items could not be transferred',n=len(failures)),'err',5000)
        self._background(title.rstrip('…')+'…',name,work,finish,
                         lambda state:tr('{a} of {b} done',a=state.get('n',0),b=len(paths)) if len(paths)>1 else None)

    def terminal(self, paths, p):
        x = Path(paths[0])
        winsys.open_terminal(str(x if x.is_dir() else x.parent))

    def float(self, paths, p):
        for x in paths[:6]:
            w = FloatWindow(x)
            self.app.floats.append(w)
            self.app._sync_media_polling()
            w.closed.connect(lambda w=w: self.app._forget_float(w))
            w.show()
            w.come_forward()

    def reveal(self, paths, p):
        winsys.reveal(paths[0])

    def open_with(self, paths, p):
        winsys.open_with(paths[0])


# ============================================================================
# Background worker
# ============================================================================
CANCELLED = "__cancelled__"


class WorkerSignals(QObject):
    done = Signal(object, object, object)   # worker, outputs, error
    progress = Signal(object, float)         # worker, 0..1
    count = Signal(object, int, int)         # worker, files done, files in the batch


class Worker(QRunnable):
    def __init__(self, op, paths, params):
        super().__init__()
        self.op, self.paths, self.params = op, paths, params
        self.sig = WorkerSignals()
        self.cancel_requested = False
        self.card = None
        self.failed = []
        self.count = (0, len(paths))

    def cancel(self):
        self.cancel_requested = True

    def run(self):
        """Run the conversion outside Qt's event loop so Cancel remains responsive."""
        try:
            from convertanny_core.jobs import ConversionJob
            job = ConversionJob(self.op.group, self.op.id, self.paths, self.params,
                                getattr(self, "output_dir", None) or engine.OUTPUT_DIR,
                                on_progress=lambda f: self.sig.progress.emit(self, f),
                                on_count=lambda a, b: self.sig.count.emit(self, a, b))
            kind, val = job.run(lambda: self.cancel_requested)
            self.failed = list(job.failed)
            if kind == "done":
                self.sig.done.emit(self, [Path(v) for v in val], None)
            elif kind == "cancelled":
                self.sig.done.emit(self, None, CANCELLED)
            else:
                self.sig.done.emit(self, None, str(val))
        except Exception as e:
            traceback.print_exc()
            self.sig.done.emit(self, None, str(e) or e.__class__.__name__)


# ============================================================================
# Update check / download (background)
# ============================================================================
class UpdateSignals(QObject):
    checked = Signal(object, object, bool)     # release | None, error | None, manual
    progress = Signal(int, int)
    downloaded = Signal(object, object)        # path | None, error | None


class UpdateCheck(QRunnable):
    def __init__(self, manual):
        super().__init__()
        self.manual = manual
        self.sig = UpdateSignals()

    def run(self):
        try:
            self.sig.checked.emit(updater.latest_release(), None, self.manual)
        except Exception as e:
            self.sig.checked.emit(None, str(e), self.manual)


class UpdateDownload(QRunnable):
    def __init__(self, release):
        super().__init__()
        self.release = release
        self.stop = False
        self.sig = UpdateSignals()

    def run(self):
        try:
            path = updater.download(self.release.installer_url, self.release.installer_name,
                                    progress=lambda d, t: self.sig.progress.emit(d, t),
                                    should_stop=lambda: self.stop,
                                    size=self.release.installer_size, sha256=self.release.installer_sha256)
            self.sig.downloaded.emit(path, None)
        except InterruptedError:
            self.sig.downloaded.emit(None, CANCELLED)
        except Exception as e:
            self.sig.downloaded.emit(None, str(e))


_APP = None          # the running ConvertANNYApp (floats use it for "Play copied link")


class LinkSignals(QObject):
    done = Signal(object, object)          # info dict | None, error | None


class LinkResolve(QRunnable):
    def __init__(self, url, quality=None):
        super().__init__()
        self.url = url
        self.quality = quality or settings().value("link_quality", "1080p")
        self.sig = LinkSignals()

    def run(self):
        try:
            self.sig.done.emit(engine.resolve_link(self.url, self.quality), None)
        except Exception as e:
            self.sig.done.emit(None, str(e))


class ModelDownload(QRunnable):
    """Downloads an AI model once into %LOCALAPPDATA%\\ConvertANNY\\models (checksum-verified)."""
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.stop = False
        self.sig = UpdateSignals()

    def run(self):
        m = engine.MODELS[self.name]
        try:
            path = updater.download(m["url"], m["file"], progress=lambda d, t: self.sig.progress.emit(d, t),
                                    should_stop=lambda: self.stop, size=m["size"], sha256=m["sha256"],
                                    folder=engine.models_dir())
            engine.mark_model_ready(self.name)
            self.sig.downloaded.emit(path, None)
        except InterruptedError:
            self.sig.downloaded.emit(None, CANCELLED)
        except Exception as e:
            self.sig.downloaded.emit(None, str(e))


# ============================================================================
# The wheel
# ============================================================================
WHEEL_ANIMS = [("bloom", "Bloom"), ("circle", "Circle"), ("fade", "Fade"), ("spin", "Spin"), ("zoom", "Zoom"),
               ("pop", "Pop"), ("drop", "Drop"), ("rise", "Rise"), ("flip", "Flip"), ("swirl", "Swirl"),
               ("none", "None")]


def wheel_anim() -> str:
    v = settings().value("wheel_anim", "bloom")
    return v if v in dict(WHEEL_ANIMS) else "bloom"


def wheel_anim_close() -> str:
    """How the wheel goes away: the opening style, unless you chose another one."""
    if settings().value("anim_same", "true") == "true":
        return wheel_anim()
    v = settings().value("wheel_anim_close", "fade")
    return v if v in dict(WHEEL_ANIMS) else "fade"


def anim_speed() -> float:
    """Animation speed from Settings: 100 = normal, 25 = four times slower, 250 = 2.5 times faster."""
    try:
        return max(25, min(250, int(settings().value("anim_speed", 100)))) / 100
    except (TypeError, ValueError):
        return 1.0


def _ease_back(k):
    """0..1 with a small overshoot, like something popping open."""
    k = max(0.0, min(1.0, k)) - 1
    return 1 + 2.2 * k ** 3 + 1.2 * k ** 2




# ============================================================================
# Toast
# ============================================================================
_SOUND_CACHE = {}


def _media_sound(words) -> str | None:
    """A Windows sound file by name, e.g. ("notify", "calendar") -> C:\\Windows\\Media\\Windows Notify Calendar.wav."""
    if words in _SOUND_CACHE:
        return _SOUND_CACHE[words]
    found = None
    media = Path(os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows") / "Media"
    try:
        for f in sorted(media.glob("*.wav")):
            n = f.stem.lower()
            if all(w in n for w in words):
                found = str(f)
                break
    except OSError:
        pass
    _SOUND_CACHE[words] = found
    return found


_TICK = None


_SELECT = None
_EFFECTS = {}
_LAST_SELECT = 0.0


_WAV_CACHE = {}


def _play_wav(name, volume, pack=None) -> bool:
    """Windows: play a short ConvertANNY sound without Qt's audio engine (which can stall the app for seconds
    when sounds are started and stopped quickly, e.g. sweeping over the wheel's slices). The volume is baked
    into a small copy of the sound, made once per volume level."""
    if not winsys.IS_WIN:
        return False
    try:
        import tempfile
        import wave
        import winsound
        import array
        vol = max(0, min(100, int(volume)))
        pack = pack or sound_pack()
        key = (name, vol, pack)
        path = _WAV_CACHE.get(key)
        if path is None or not os.path.exists(path):
            folder = Path(tempfile.gettempdir()) / "ConvertANNY sounds"
            folder.mkdir(parents=True, exist_ok=True)
            path = str(folder / f"{name}-{pack}-{vol}.wav")
            with wave.open(sound_file(name, pack), "rb") as src:
                params = src.getparams()
                frames = src.readframes(src.getnframes())
            if params.sampwidth == 2:
                a = array.array("h", frames)
                k = vol / 100
                a = array.array("h", (int(x * k) for x in a))
                frames = a.tobytes()
            with wave.open(path, "wb") as out:
                out.setparams(params)
                out.writeframes(frames)
            _WAV_CACHE[key] = path
        if vol == 0:
            return True
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        return True
    except Exception as e:
        winsys.log(f"sound {name}: {e}")
        return False


SOUND_PACKS = [("classic", "Classic"), ("soft", "Soft"), ("glass", "Glass"), ("bubble", "Bubble"),
               ("mechanical", "Mechanical"), ("retro", "Retro"), ("velvet", "Velvet"), ("crystal", "Crystal"),
               ("pulse", "Pulse")]


def sound_pack() -> str:
    v = settings().value("sound_pack", "classic")
    v = {"steam": "velvet", "playstation": "crystal", "xbox": "pulse"}.get(v, v)    # names in early 1.2.1 builds
    return v if v in dict(SOUND_PACKS) else "classic"


def sound_file(name, pack=None) -> str:
    """The .wav for 'tick', 'select', 'open' or 'close' in the chosen sound style."""
    pack = pack or sound_pack()
    if pack != "classic":
        f = asset(f"sounds/{name}-{pack}.wav")
        if os.path.exists(f):
            return f
    return asset(f"sounds/{name}.wav")


def _tick_effect(name="tick"):
    """Qt's player for a wheel sound (only used where Windows' own player isn't available)."""
    from PySide6.QtMultimedia import QSoundEffect
    key = (name, sound_pack())
    if key not in _EFFECTS:
        fx = QSoundEffect()
        fx.setSource(QUrl.fromLocalFile(sound_file(name)))
        _EFFECTS[key] = fx
    return _EFFECTS[key]


def play_wheel_sound(name):
    """The soft rising sound when the wheel opens and the falling one when it closes (same switch and volume as the tick)."""
    if settings().value("tick_sound", "true") != "true":
        return
    if name == "close" and time.monotonic() - _LAST_SELECT < 0.8:
        return                                   # choosing a slice already made its own sound
    vol = int(int(settings().value("tick_volume", 70)) * 0.8)
    if _play_wav(name, vol):
        return
    try:
        fx = _tick_effect(name)
        fx.setVolume(max(0, min(100, vol)) / 100)
        fx.play()
    except Exception as e:
        winsys.log(f"{name} sound: {e}")


def play_select():
    """The deeper "press" when you choose a slice (like the iPod's centre button). Same switch and volume as the tick."""
    global _LAST_SELECT
    _LAST_SELECT = time.monotonic()
    if settings().value("tick_sound", "true") != "true":
        return
    vol = int(settings().value("tick_volume", 70))
    if _play_wav("select", vol):
        return
    try:
        fx = _tick_effect("select")
        fx.setVolume(max(0, min(100, vol)) / 100)
        fx.play()
    except Exception as e:
        winsys.log(f"select sound: {e}")


def play_tick(force=False):
    """The click when the highlight moves to another slice (Settings → Everyday, with its own volume)."""
    if settings().value("tick_sound", "true") != "true" and not force:
        return
    vol = int(settings().value("tick_volume", 70))
    if _play_wav("tick", vol):
        return
    try:
        fx = _tick_effect()
        fx.setVolume(max(0, min(100, vol)) / 100)
        fx.play()
    except Exception as e:
        winsys.log(f"tick sound: {e}")


def play_finish_sound(kind="ok"):
    """Windows' "Notify Calendar" sound when a job finishes, "Notify Messaging" for an error (Settings → Everyday)."""
    if settings().value("finish_sound", "true") != "true" or not winsys.IS_WIN:
        return
    wav = _media_sound(("notify", "messaging") if kind == "err" else ("notify", "calendar"))
    try:
        import winsound
        if wav:
            winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        winsys.log(f"sound ({kind}): {Path(wav).name if wav else 'not found in Windows Media folder'}")
    except Exception as e:
        winsys.log(f"sound ({kind}) failed: {e}")






# ============================================================================
# Float window — pinned, always on top, like a mini player.
# The picture fills the card; the close button, name, grip (and video controls) fade in only while
# the cursor is over it. Drag to move, drag an edge or corner to resize, drag the grip to drop the
# file into another app. Videos and audio play in place; other files show their icon, click to open.
# ============================================================================
def _fmt_time(ms):
    s = max(0, int(ms // 1000))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _find_side_subtitles(video) -> list[str]:
    """Subtitle files next to a video with the same name: movie.srt, movie.en.srt, movie.vtt ..."""
    v = Path(video)
    try:
        return sorted(str(f) for f in v.parent.iterdir()
                      if f.suffix.lower() in (".srt", ".vtt") and f.name.lower().startswith(v.stem.lower()))
    except OSError:
        return []


def _parse_subtitles(path) -> list[tuple[int, int, str]]:
    """Read an SRT or WebVTT file into (start ms, end ms, text) cues. Handles UTF-8 and Arabic (Windows-1256)."""
    import re
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    ts = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})|(\d\d):(\d\d)[,.](\d{1,3})")

    def ms(t):
        m = ts.fullmatch(t.strip().split(" ")[0])
        if not m:
            return None
        if m.group(1):
            h, mi, se, fr = m.group(1, 2, 3, 4)
        else:
            h, (mi, se, fr) = "0", m.group(5, 6, 7)
        return ((int(h) * 60 + int(mi)) * 60 + int(se)) * 1000 + int(fr.ljust(3, "0"))

    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", text.replace("\r\n", "\n")):
        lines = [l for l in block.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                a, b = line.split("-->", 1)
                start, end = ms(a), ms(b)
                if start is not None and end is not None:
                    body = "\n".join(lines[i + 1:])
                    body = re.sub(r"<[^>]+>|\{[^}]*\}", "", body).strip()
                    if body:
                        cues.append((start, end, body))
                break
    return cues




def _cacheable(url) -> bool:
    u = str(url).lower()
    own = u.startswith("http://127.0.0.1:") and u.endswith(("/media", "/live.ts"))     # ConvertANNY's own
    return u.startswith(("http://", "https://")) and "m3u8" not in u and "hls_playlist" not in u \
        and not own and ".mpd" not in u


LIVE_OUTPUT = ["-f", "mpegts"]
LIVE_INPUT_EXTRA = []          # tests add "-re" to feed a recorded stream at live speed




def saved_links() -> list:
    """Links played in Float, newest first: [{"url", "title"}]."""
    try:
        v = json.loads(settings().value("float_links", "[]") or "[]")
        return [x for x in v if isinstance(x, dict) and x.get("url")]
    except (TypeError, ValueError):
        return []


def remember_link(url, title):
    old = next((x for x in saved_links() if x["url"] == url), {})
    links = [x for x in saved_links() if x["url"] != url]
    item = {"url": url, "title": title or url}
    if old.get("name"):
        item["name"] = old["name"]                  # a name you gave it stays
    links.insert(0, item)
    settings().setValue("float_links", json.dumps(links[:40], ensure_ascii=False))


def link_name(it: dict) -> str:
    """What a saved link is called: the name you gave it, else the page's title."""
    return it.get("name") or it.get("title") or it.get("url", "")


def rename_link(url, name):
    links = saved_links()
    for x in links:
        if x["url"] == url:
            if name and name.strip() and name.strip() != x.get("title"):
                x["name"] = name.strip()
            else:
                x.pop("name", None)                  # an empty name goes back to the page's title
    settings().setValue("float_links", json.dumps(links, ensure_ascii=False))


class SavedLinksDialog(QDialog):
    """Rename, remove, reorder and play the links you played in Float."""

    def __init__(self, play=None, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem
        self.play = play
        self.setWindowTitle(f"{APP} — " + tr("Saved links"))
        self.setWindowIcon(app_icon())
        self.setStyleSheet(i18n.css(DIALOG_CSS))
        self.setLayoutDirection(Qt.RightToLeft if i18n.is_rtl() else Qt.LeftToRight)
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        tip = QLabel(tr("Double-click a name to rename it. Drag to change the order."))
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.list = QListWidget()
        self.list.setStyleSheet("QListWidget::item{padding:6px 8px; min-height:24px}"
                                "QListWidget QLineEdit{padding:2px 6px; min-height:26px; margin:0}")
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.SelectedClicked)
        for it in saved_links():
            self._add_item(it)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for label, fn in ((tr("Play"), self._play), (tr("Add…"), self._add), (tr("Rename"), self._rename),
                          (tr("Remove"), self._remove), (tr("Clear the list"), self._clear)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Save"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lay.addLayout(row)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _add_item(self, it, select=False):
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QListWidgetItem
        li = QListWidgetItem(link_name(it))
        li.setData(Qt.UserRole, dict(it))
        li.setToolTip(it["url"])
        li.setFlags(li.flags() | Qt.ItemIsEditable)
        li.setSizeHint(QSize(0, 36))                 # room to type when renaming
        self.list.addItem(li)
        if select:
            self.list.setCurrentItem(li)
        return li

    def _add(self):
        from PySide6.QtWidgets import QInputDialog
        clip = QGuiApplication.clipboard().text().strip()
        url, ok = QInputDialog.getText(self, tr("Add…"), tr("Link to a video or song"),
                                       text=clip if engine.is_link(clip) else "")
        url = url.strip()
        if not ok or not url:
            return
        if not engine.is_link(url):
            QMessageBox.information(self, tr("Saved links"), tr("That isn't a link to a web page."))
            return
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole)["url"] == url:
                self.list.setCurrentRow(i)
                return
        name, ok = QInputDialog.getText(self, tr("Rename"), tr("Name for this link (empty = the page's title)"))
        it = {"url": url, "title": url}
        if ok and name.strip():
            it["name"] = name.strip()
        li = self._add_item(it)
        self.list.takeItem(self.list.row(li))       # newest first, like links you play
        self.list.insertItem(0, li)
        self.list.setCurrentItem(li)

    def _clear(self):
        if not self.list.count():
            return
        if QMessageBox.question(self, tr("Saved links"), tr("Remove all saved links?")) == QMessageBox.Yes:
            self.list.clear()

    def _items(self):
        out = []
        for i in range(self.list.count()):
            li = self.list.item(i)
            it = dict(li.data(Qt.UserRole))
            name = li.text().strip()
            if name and name != it.get("title"):
                it["name"] = name
            else:
                it.pop("name", None)
            out.append(it)
        return out

    def _save(self):
        settings().setValue("float_links", json.dumps(self._items(), ensure_ascii=False))
        self.accept()

    def _rename(self):
        li = self.list.currentItem()
        if li is not None:
            self.list.editItem(li)

    def _remove(self):
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)

    def _play(self):
        li = self.list.currentItem()
        if li is None:
            return
        self._save()
        if self.play:
            self.play(li.data(Qt.UserRole)["url"])


def forget_link(url):
    settings().setValue("float_links", json.dumps([x for x in saved_links() if x["url"] != url], ensure_ascii=False))


def refresh_link_title(url, title):
    """A saved link that was played again: keep its place and your name, just update the page's title."""
    links = saved_links()
    for x in links:
        if x["url"] == url and title:
            x["title"] = title
    settings().setValue("float_links", json.dumps(links, ensure_ascii=False))


def recent_played() -> list:
    """Links and files played in Float, newest first: [{"kind": "link"|"file", "key", "title"}]."""
    try:
        v = json.loads(settings().value("float_recent", "[]") or "[]")
        return [x for x in v if isinstance(x, dict) and x.get("key")]
    except (TypeError, ValueError):
        return []


def remember_played(kind, key, title):
    items = [x for x in recent_played() if x["key"] != key]
    items.insert(0, {"kind": kind, "key": key, "title": title or key})
    settings().setValue("float_recent", json.dumps(items[:30], ensure_ascii=False))


def forget_played(key=None):
    items = [] if key is None else [x for x in recent_played() if x["key"] != key]
    settings().setValue("float_recent", json.dumps(items, ensure_ascii=False))


class RecentPlayedDialog(QDialog):
    """The links and files you played in Float: play one again, save a link, or remove them."""

    def __init__(self, play=None, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        self.play = play
        self.setWindowTitle(f"{APP} — " + tr("Recently played"))
        self.setWindowIcon(app_icon())
        self.setStyleSheet(i18n.css(DIALOG_CSS))
        self.setLayoutDirection(Qt.RightToLeft if i18n.is_rtl() else Qt.LeftToRight)
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        for it in recent_played():
            li = QListWidgetItem(("🔗  " if it["kind"] == "link" else "🎞  ") + it.get("title", it["key"]))
            li.setData(Qt.UserRole, it)
            li.setToolTip(it["key"])
            li.setSizeHint(QSize(0, 34))
            self.list.addItem(li)
        self.list.itemDoubleClicked.connect(lambda _i: self._play())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for label, fn in ((tr("Play"), self._play), (tr("Save this link"), self._save),
                          (tr("Remove"), self._remove), (tr("Clear the list"), self._clear)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        b = QPushButton(tr("Close"))
        b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _cur(self):
        li = self.list.currentItem()
        return li.data(Qt.UserRole) if li is not None else None

    def _play(self):
        it = self._cur()
        if it and self.play:
            self.accept()
            self.play(it)

    def _save(self):
        it = self._cur()
        if it and it["kind"] == "link" and not any(x["url"] == it["key"] for x in saved_links()):
            remember_link(it["key"], it.get("title"))

    def _remove(self):
        it = self._cur()
        if it:
            forget_played(it["key"])
            self.list.takeItem(self.list.currentRow())

    def _clear(self):
        if self.list.count() and QMessageBox.question(self, tr("Recently played"),
                                                      tr("Remove everything from the list?")) == QMessageBox.Yes:
            forget_played()
            self.list.clear()


def _float_pins() -> list:
    """Floats that reopen when Windows starts: [{"id", "src", "link", "x", "y", "w", "on_top"}]."""
    try:
        v = json.loads(settings().value("float_pins", "[]") or "[]")
        return v if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


def _save_float_pins(pins):
    settings().setValue("float_pins", json.dumps(pins))


class MediaOSD(QWidget):
    """A big see-through play/pause/next/previous sign in the middle of the screen for a second."""
    _one = None

    @staticmethod
    def wanted(focused) -> bool:
        s = settings()
        if s.value("media_osd", "true") != "true":
            return False
        return s.value("media_osd_when", "unfocused") == "always" or not focused

    @classmethod
    def flash(cls, kind, near=None, level=None, hold=750):
        if cls._one is None:
            cls._one = MediaOSD()
        cls._one.level = level
        cls._one._show(kind, near, hold)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.kind = "play"
        self.level = None
        self.setFixedSize(180, 180)
        self._hold = QTimer(self, singleShot=True, timeout=self._fade)
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.finished.connect(self._done)

    def _show(self, kind, near, hold=750):
        self.kind = kind
        scr = (near.screen() if near is not None else None) or QGuiApplication.screenAt(QCursor.pos()) \
            or QGuiApplication.primaryScreen()
        g = scr.geometry()
        self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)
        self._anim.stop()
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self.update()
        self._hold.start(hold)

    def _fade(self):
        self._anim.setDuration(250)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _done(self):
        if self.windowOpacity() < 0.05:
            self.hide()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawEllipse(self.rect().adjusted(2, 2, -2, -2))
        p.setBrush(QColor(255, 255, 255, 215))
        c = self.rect().center()
        cx, cy = c.x() + 1, c.y() + 1

        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)

        def tri(x0, pointing_right=True, w=46, h=56):
            x1 = x0 + w if pointing_right else x0 - w
            path.addPolygon(QPolygonF([QPointF(x0, cy - h / 2), QPointF(x1, cy), QPointF(x0, cy + h / 2),
                                       QPointF(x0, cy - h / 2)]))

        k = self.kind
        if k == "play":
            tri(cx - 20, w=54, h=64)
        elif k == "pause":
            p.drawRoundedRect(QRectF(cx - 26, cy - 32, 18, 64), 4, 4)
            p.drawRoundedRect(QRectF(cx + 8, cy - 32, 18, 64), 4, 4)
        elif k == "stop":
            p.drawRoundedRect(QRectF(cx - 28, cy - 28, 56, 56), 6, 6)
        elif k == "next":
            tri(cx - 40)
            tri(cx - 4)
            p.drawRoundedRect(QRectF(cx + 40, cy - 28, 9, 56), 2, 2)
        elif k == "prev":
            tri(cx + 40, False)
            tri(cx + 4, False)
            p.drawRoundedRect(QRectF(cx - 49, cy - 28, 9, 56), 2, 2)
        elif k in ("volume", "mute"):
            sy = cy - 16                                   # speaker a little higher, the level bar under it
            sp = QPolygonF([QPointF(cx - 38, sy - 11), QPointF(cx - 26, sy - 11), QPointF(cx - 8, sy - 28),
                            QPointF(cx - 8, sy + 28), QPointF(cx - 26, sy + 11), QPointF(cx - 38, sy + 11)])
            path.addPolygon(sp)
            path.closeSubpath()
            pen = QPen(QColor(255, 255, 255, 215), 6, Qt.SolidLine, Qt.RoundCap)
            lvl = self.level if self.level is not None else 1.0
            if k == "mute" or lvl <= 0.001:
                p.setPen(pen)
                p.drawLine(QPointF(cx + 6, sy - 14), QPointF(cx + 34, sy + 14))
                p.drawLine(QPointF(cx + 34, sy - 14), QPointF(cx + 6, sy + 14))
            else:
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                for i, r in enumerate((14, 26, 38)):
                    if lvl > i / 3 or i == 0:
                        p.drawArc(QRectF(cx - 8 - r, sy - r, 2 * r, 2 * r), -45 * 16, 90 * 16)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 215))
            bar = QRectF(cx - 50, cy + 34, 100, 8)
            p.setBrush(QColor(255, 255, 255, 70))
            p.drawRoundedRect(bar, 4, 4)
            p.setBrush(QColor(255, 255, 255, 215) if k == "volume" else QColor(255, 255, 255, 110))
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * lvl, bar.height()), 4, 4)
            f = QFont(i18n.ui_font(), 10, QFont.DemiBold)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 215))
            p.drawText(QRectF(cx - 50, cy + 44, 100, 22), Qt.AlignCenter, f"{round(lvl * 100)}")
            p.setPen(Qt.NoPen)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 215))
        p.drawPath(path.simplified())
        p.end()


def _clipboard_media_file():
    """A file copied in Explorer (Ctrl+C), or a copied path ("Copy as path"), when it's something Float shows."""
    md = QGuiApplication.clipboard().mimeData()
    cands = []
    if md is not None and md.hasUrls():
        cands += [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
    txt = QGuiApplication.clipboard().text().strip()
    if txt and len(txt) < 1000:
        cands.append(txt.splitlines()[0].strip().strip('"').strip("'"))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


class FloatWindow(QWidget):
    def come_forward(self):
        """A float you just opened shows in front of other windows, even when it isn't set to stay on top."""
        self.raise_()
        if not getattr(self, "on_top", True):
            QTimer.singleShot(60, lambda: winsys.bring_to_front(int(self.winId())))

    closed = Signal()
    page_ready = Signal(object, object)    # path, QImage of a document's first page (from a thread)
    RADIUS = 14
    EDGE = 7              # resize border
    CLOSE_R = 11
    MIN_W = 160

    def __init__(self, path, link=None, play=False, pin=None):
        on_top = settings().value("float_on_top", "true") == "true"
        if pin is not None:
            on_top = bool(pin.get("on_top", on_top))
        taskbar = settings().value("float_taskbar", "true") == "true"
        super().__init__(None, Qt.FramelessWindowHint | (Qt.Window if taskbar else Qt.Tool)
                         | (Qt.WindowStaysOnTopHint if on_top else Qt.Widget))
        self.on_top = on_top
        self._vol_open = False
        self._vol_drag = False
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(True)        # drop another file on the float to replace it
        self.player = None
        self.hover = None
        self.ctrl = 1.0                  # opacity of the controls; fades with the cursor
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.valueChanged.connect(self._set_ctrl)
        self._press = None               # (kind, global pos, local pos, geometry, edges)
        self._seeking = False
        self._drop_hover = False
        self.pin_id = None               # set when this float reopens with Windows
        self._pin_timer = QTimer(self, singleShot=True, interval=500, timeout=self._save_pin)
        self.companion = None
        self._relay = None
        self.repeat = settings().value("float_repeat", "off")     # off | one | all
        self._play_now = play
        self._load(path, link)
        self.move(QCursor.pos() - QPoint(self.width() // 2, 40))
        self._resume_ms = int((pin or {}).get("pos") or 0)     # where playback was before an update
        self._placing = False
        self._pin_play = bool((pin or {}).get("playing", True))    # a reopened link keeps playing or stays paused
        if pin is not None:
            self.pin_id = pin.get("id")
            self._place_from(pin)
        # show the controls briefly so people know they exist, then let them fade
        QTimer.singleShot(1600, self._maybe_hide_controls)

    def _place_from(self, pin, tries=0):
        """Put a reopened float back exactly where it was, at the same size. Right after signing in to Windows the
        screens may not be ready yet: then it waits (up to 20 s) instead of saving a wrong place over the right one."""
        try:
            w = max(self.MIN_W, int(pin.get("w", self.width())))
            h = int(pin.get("h") or 0)
            at = QPoint(int(pin["x"]), int(pin["y"]))
        except (KeyError, TypeError, ValueError):
            self._placing = False
            return
        self._placing = True
        if h and self.aspect and self.kind in ("video", "image"):
            self.aspect = w / max(1, h)               # the shape it had (a video corrects it with its first frame)
        self._apply_size(w, h or self._height_for(w))
        if QGuiApplication.screenAt(at + QPoint(20, 20)) is None and tries < 20:
            QTimer.singleShot(1000, lambda: self._place_from(pin, tries + 1))
            return
        if QGuiApplication.screenAt(at + QPoint(20, 20)) is not None:
            self.move(at)
        self._placing = False

    def _load(self, path, link=None):
        """Show `path` in this float (also used when another file is dropped on it).
        `link` = {"url", "title", "page"} when playing a web link (path is then the media URL)."""
        self._drop_companion()
        self._stop_relay()
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
            self.player.deleteLater()
            self.player = None
        prev_kind, prev_w = getattr(self, "kind", None), self.width()
        self.path = path
        self.link = link
        cat = "video" if link else engine.EXT_CATEGORY.get(engine.ext_of(path))
        self.kind = "other"          # image | video | audio | other
        self.src = None              # QPixmap for images, album covers and icons
        self.art = False             # True when src is an album cover
        self.frame = None            # current video frame (QImage)
        self.aspect = None           # width / height of the picture, kept while resizing
        self._scaled = None
        if cat == "image":
            try:
                img = engine.open_image(path)
                img.thumbnail((1600, 1600))
                q = QImage(img.convert("RGBA").tobytes("raw", "RGBA"), img.width, img.height,
                           img.width * 4, QImage.Format_RGBA8888)
                self.src = QPixmap.fromImage(q.copy())
                self.kind = "image"
                self.aspect = img.width / max(1, img.height)
            except Exception:
                self.src = None
        elif path and (cat in DOC_PREVIEW_CATS or cat == "comic") and Path(path).suffix.lower() not in (".cbr", ".cb7", ".cbt"):
            # PDFs, e-books and Office files show their first page; the icon stays until it's drawn
            if not getattr(self, "_page_hooked", False):
                self.page_ready.connect(self._got_page, Qt.QueuedConnection)
                self._page_hooked = True
            threading.Thread(target=lambda pp=path: self.page_ready.emit(pp, document_page_image(pp, 1400)),
                             daemon=True).start()
        elif not path and not link:                   # an empty float: drop a file, paste a link, or pick a saved one
            self.kind = "empty"
            self.aspect = 16 / 9
            self.src = QPixmap(2, 2)
            self.src.fill(Qt.transparent)
        elif link and link.get("pending"):           # reopening: the window shows now, the video when it's fetched
            self.kind = "video"
            self.aspect = 16 / 9
            self.src = QPixmap(2, 2)
            self.src.fill(QColor(0, 0, 0))
            self._busy, self._spin = True, 0.0
            self._pending_timer = QTimer(self, interval=40, timeout=self._pending_tick)
            self._pending_timer.start()
        elif cat in ("video", "audio") and self._start_player(cat):
            self.kind = cat
            if path and not link:
                remember_played("file", str(path), Path(path).name)
            if cat == "video":
                self.aspect = 16 / 9
            else:
                self._set_cover(engine.cover_art(path))
        if self.src is None:
            from PySide6.QtCore import QFileInfo
            from PySide6.QtWidgets import QFileIconProvider
            self.src = QFileIconProvider().icon(QFileInfo(path)).pixmap(256, 256)
        if self.kind == "image":
            w = 300 if self.aspect >= 1 else int(300 * self.aspect)
        elif self.kind == "video":
            w = 420
        elif self.art:
            w = 280
        elif self.kind == "empty":
            w = 360
        else:
            w = 200
        if self.isVisible() and self.kind == prev_kind and self.kind != "other":
            w = prev_w                                   # next/previous keeps the size you chose
        tl = self.pos() if self.isVisible() else None
        self._apply_size(w, self._height_for(w))
        if tl is not None:
            self.move(tl)                                # stay exactly where it is
        self._pin_changed()
        self.setToolTip(f"{link['page'] if link else path}\n" + tr("Drag to move · drag ⠿ to drop the file · double-click to open · scroll to resize"))
        try:
            self.setWindowTitle((self.display_name() if (path or link) else tr("Open Float")) or APP)   # the taskbar button
        except Exception:
            self.setWindowTitle(APP)
        self.update()
        if _APP is not None:
            _APP._sync_media_polling()

    def set_rate(self, rate):
        """Play faster or slower (the sound keeps its pitch)."""
        if self.player is not None:
            self.player.setPlaybackRate(rate)
        if getattr(self, "companion", None) is not None:
            self.companion.setPlaybackRate(rate)
            if self.player is not None:
                self.companion.setPosition(self.player.position())

    def _play_recent(self, it):
        if it["kind"] == "link":
            if _APP is not None:
                _APP.play_link(target=self, url=it["key"])
        elif os.path.isfile(it["key"]):
            self._play_now = True
            self._load(it["key"])
            self._fade_to(1.0)
            self.come_forward()
        else:
            forget_played(it["key"])                     # the file was moved or deleted

    def display_name(self):
        if self.link:
            keys = (self.link.get("saved"), self.link.get("page"))
            saved = next((x for x in saved_links() if x["url"] in keys), None)
            return link_name(saved) if saved else self.link["title"]
        return Path(self.path).name

    def _rename_link(self):
        from PySide6.QtWidgets import QInputDialog
        keys = (self.link.get("saved"), self.link.get("page")) if self.link else ()
        saved = next((x for x in saved_links() if x["url"] in keys), None)
        page = saved["url"] if saved else None
        if not saved:
            return
        self.activateWindow()
        winsys.set_foreground(int(self.winId()))
        name, ok = QInputDialog.getText(self, tr("Rename"), tr("Name for this link (empty = the page's title)"),
                                        text=link_name(saved))
        if ok:
            rename_link(page, name)
            self.update()

    def _got_page(self, path, img):
        if path != self.path or self.link or img is None or img.isNull():
            return
        self.src = QPixmap.fromImage(img)
        self.kind = "image"
        self.aspect = img.width() / max(1, img.height())
        self._scaled = None
        w = 300 if self.aspect >= 1 else max(self.MIN_W, int(400 * self.aspect))
        tl = self.pos() if self.isVisible() else None
        self._apply_size(w, self._height_for(w))
        if tl is not None:
            self.move(tl)
        self.update()

    def _has_content(self) -> bool:
        return bool(self.link) or (self.kind != "empty" and bool(self.path))

    def _open_original(self):
        if not self._has_content():                  # an empty float: Open picks a file to show in it
            QTimer.singleShot(0, self._browse_file)  # once the menu has closed
            return
        QDesktopServices.openUrl(QUrl(self.link["page"]) if self.link else QUrl.fromLocalFile(self.path))

    def _browse_file(self):
        """Choose a picture, video, song or document to show in this float."""
        start = str(Path(self.path).parent) if self.path and not self.link else str(Path.home())
        # floats never take the focus by themselves, so make ConvertANNY the foreground app first:
        # otherwise Windows opens the file window behind everything else
        self.activateWindow()
        winsys.set_foreground(int(self.winId()))
        f, _ = QFileDialog.getOpenFileName(self, tr("Open"), start)
        if f:
            self._load(f)
            self._fade_to(1.0)
            self.come_forward()
            QTimer.singleShot(1600, self._maybe_hide_controls)

    def _nothing_playing(self) -> bool:
        if self.kind == "empty":
            return True
        if self.player is None or self.kind not in ("video", "audio"):
            return False
        from PySide6.QtMultimedia import QMediaPlayer
        return self.player.playbackState() == QMediaPlayer.StoppedState and not getattr(self, "_busy", False)

    def _set_cover(self, data):
        """Use an album cover (PNG bytes or QImage) as the picture of an audio float."""
        img = QImage.fromData(data) if isinstance(data, (bytes, bytearray)) else data
        if img is None or img.isNull():
            return
        self.src = QPixmap.fromImage(img)
        self.art = True
        self.aspect = img.width() / max(1, img.height())
        self._scaled = None

    def _on_metadata(self):
        if self.kind != "audio" or self.art or not self.player:
            return
        from PySide6.QtMultimedia import QMediaMetaData
        md = self.player.metaData()
        for key in (QMediaMetaData.CoverArtImage, QMediaMetaData.ThumbnailImage):
            img = md.value(key)
            if isinstance(img, QImage) and not img.isNull():
                self._set_cover(img)
                tl = self.pos()
                self._apply_size(self.width() if self.width() > 200 else 280, self._height_for(280))
                self.move(tl)
                return

    # ---------------------------------------------------------------- drop to replace
    def _dropped_path(self, md):
        if not md.hasUrls():
            return None
        files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        return files[0] if files and os.path.exists(files[0]) and files[0] != self.path else None

    @staticmethod
    def _dropped_link(md):
        """A web page dragged from the browser (the address bar's site icon, a link, a tab)."""
        cands = [u.toString() for u in md.urls() if not u.isLocalFile()] if md.hasUrls() else []
        if md.hasText():
            cands.append(md.text().strip().splitlines()[0] if md.text().strip() else "")
        return next((c for c in cands if c and engine.is_link(c)), None)

    def dragEnterEvent(self, e):
        if self._dropped_path(e.mimeData()) or (_APP is not None and self._dropped_link(e.mimeData())):
            e.acceptProposedAction()
            self._drop_hover = True
            self.update()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._drop_hover = False
        self.update()

    def dropEvent(self, e):
        self._drop_hover = False
        path = self._dropped_path(e.mimeData())
        if path:
            e.acceptProposedAction()
            self._load(path)
            self._fade_to(1.0)
            QTimer.singleShot(1600, self._maybe_hide_controls)
            return
        link = self._dropped_link(e.mimeData()) if _APP is not None else None
        if link:                                     # a video page dragged from the browser plays here
            e.acceptProposedAction()
            _APP.play_link(target=self, url=link)
        self.update()

    # ---------------------------------------------------------------- media
    def _start_player(self, cat):
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
        except Exception as e:                      # build without Qt Multimedia
            winsys.log(f"float: no multimedia ({e})")
            return False
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        try:
            self.audio.setVolume(float(settings().value("float_volume", 1.0)))
        except (TypeError, ValueError):
            pass
        self.player.setAudioOutput(self.audio)
        self.autoplay = settings().value("float_autoplay", "true") == "true" or getattr(self, "_play_now", False)
        self._play_now = False
        self.subs = None             # external subtitles: list of (start ms, end ms, text)
        self.sub_text = ""           # built-in subtitle line currently shown
        if cat == "video":
            self.sink = QVideoSink(self)
            self.player.setVideoSink(self.sink)
            self.sink.videoFrameChanged.connect(self._on_frame)
            self.sink.subtitleTextChanged.connect(self._on_subtitle)
            self._first_frame = True
            if not self.autoplay:
                # play until the first frame arrives (silently), then pause on it
                self.audio.setMuted(True)
        self.player.positionChanged.connect(lambda _p: self.update())
        # loading circle while the video waits for data (like YouTube's)
        if getattr(self, "_busy_timer", None) is not None:
            self._busy_timer.stop()
            self._busy_timer.deleteLater()
        self._busy = False
        self._spin = 0.0
        self._pos_seen = (-1, 0.0)
        self._busy_timer = QTimer(self, interval=40, timeout=self._check_busy)
        self._busy_timer.start()
        self.player.durationChanged.connect(lambda _d: self.update())
        self.player.playbackStateChanged.connect(lambda _s: self.update())
        self.player.errorOccurred.connect(self._on_media_error)
        if cat == "audio":
            self.player.metaDataChanged.connect(self._on_metadata)
        self.player.mediaStatusChanged.connect(self._on_status)
        if self.link and self.link.get("audio"):
            self._add_companion(self.link["audio"])
        if self.link and not self._live() and _cacheable(self.path):
            self.player.setSource(QUrl(self._cached(self.path, self.link.get("size"))))
        elif self._live():
            self._start_relay()
            self.player.mediaStatusChanged.connect(lambda st: winsys.log(f"float: live status {st.name}"))
            self.player.setSource(QUrl(self._relay.url))
            QTimer.singleShot(20000, self._prefetch_live)
        else:
            self.player.setSource(QUrl(self.path) if self.link else QUrl.fromLocalFile(self.path))
        if cat == "video" or self.autoplay:
            self.player.play()
        if cat == "video" and not self.link:
            side = _find_side_subtitles(self.path)
            if side:
                self._load_subs(side[0])
        return True

    # ---- separate sound stream (some YouTube videos only come as picture + sound apart)
    def _add_companion(self, audio_url):
        from PySide6.QtMultimedia import QMediaPlayer
        self.player.setAudioOutput(None)                    # the picture stream is silent anyway
        self.companion = QMediaPlayer(self)
        self.companion.setAudioOutput(self.audio)           # volume slider and mute keep working
        self.companion.setSource(QUrl(self._cached(audio_url, (self.link or {}).get("audio_size"))
                                      if _cacheable(audio_url) else audio_url))
        self.player.playbackStateChanged.connect(self._sync_companion_state)
        self.player.positionChanged.connect(self._sync_companion_pos)

    def _drop_companion(self):
        c = getattr(self, "companion", None)
        if c is not None:
            c.stop()
            c.setSource(QUrl())
            c.deleteLater()
            self.companion = None

    def _sync_companion_state(self, state):
        from PySide6.QtMultimedia import QMediaPlayer
        c = getattr(self, "companion", None)
        if c is None:
            return
        if state == QMediaPlayer.PlayingState:
            c.setPosition(self.player.position())
            c.play()
        elif state == QMediaPlayer.PausedState:
            c.pause()
        else:
            c.stop()

    def _sync_companion_pos(self, ms):
        c = getattr(self, "companion", None)
        if c is not None and abs(c.position() - ms) > 350:     # seeked, or drifted
            c.setPosition(ms)

    # ---- previous / next file in the same folder
    def _siblings(self):
        import re
        if self.link:
            return []
        cat = engine.EXT_CATEGORY.get(engine.ext_of(self.path))
        here = Path(self.path)
        try:
            files = [str(f) for f in here.parent.iterdir()
                     if f.is_file() and engine.EXT_CATEGORY.get(engine.ext_of(str(f))) == cat]
        except OSError:
            return []
        natural = lambda t: [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", Path(t).name)]
        return sorted(files, key=natural)

    def _neighbour(self, step):
        files = self._siblings()
        try:
            i = [os.path.normcase(f) for f in files].index(os.path.normcase(self.path))
        except ValueError:
            return None
        j = i + step
        return files[j] if 0 <= j < len(files) else None

    def _step(self, step):
        nxt = self._neighbour(step)
        if nxt:
            self._play_now = True
            self._load(nxt)
        return bool(nxt)

    def _check_busy(self):
        import time
        from PySide6.QtMultimedia import QMediaPlayer
        if self.player is None:
            return
        st = self.player.mediaStatus()
        now = time.monotonic()
        pos = self.player.position()
        if pos != self._pos_seen[0]:
            self._pos_seen = (pos, now)
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        busy = st in (QMediaPlayer.LoadingMedia, QMediaPlayer.StalledMedia) and (playing or self.link is not None)
        if not busy and self.link and playing and self.kind == "video":       # stream stuck waiting for data
            busy = now - self._pos_seen[1] > 0.9
        if self.kind == "video" and self.frame is None and (playing or self.link):
            busy = True                                                     # nothing to show yet
        if busy and not self._busy:
            self._busy_since = now
        relay = getattr(self, "_relay", None)
        if busy and self._live() and relay is not None and now - relay.last_data > 6 \
                and now - getattr(self, "_last_refresh", 0) > 20 and now - getattr(self, "_live_fixing", 0) > 6:
            winsys.log("float: live relay got nothing for 6 s")
            self._last_refresh = now
            self._live_continue(error=True) if getattr(self, "_spare", None) else self.refresh_link(auto=True)
        if busy and self.link and now - getattr(self, "_busy_since", now) > 15 \
                and now - getattr(self, "_last_refresh", 0) > 45 and now - getattr(self, "_live_fixing", 0) > 25:
            self.refresh_link(auto=True)                      # stuck: fetch a fresh link by itself
        if busy or busy != self._busy:
            self._spin = (self._spin + 12) % 360
            self._busy = busy
            self.update()

    def _pending_tick(self):
        if not (self.link or {}).get("pending"):
            self._pending_timer.stop()
            return
        self._spin = (self._spin + 12) % 360
        self.update()

    def _paint_busy(self, p):
        c = QPointF(self.width() / 2, self.height() / 2)
        rad = max(14.0, min(self.width(), self.height()) * 0.09)
        p.save()
        p.setOpacity(1.0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawEllipse(c, rad + 10, rad + 10)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 60), max(3.0, rad / 5), Qt.SolidLine, Qt.RoundCap))
        p.drawEllipse(c, rad, rad)
        p.setPen(QPen(QColor(255, 255, 255, 235), max(3.0, rad / 5), Qt.SolidLine, Qt.RoundCap))
        box = QRectF(c.x() - rad, c.y() - rad, rad * 2, rad * 2)
        p.drawArc(box, int(-self._spin * 16), int(-100 * 16))
        p.restore()

    def _on_status(self, status):
        from PySide6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.LoadedMedia and self._resume_ms and self.autoplay:
            self.player.setPosition(self._resume_ms)
            self._resume_ms = 0
        if status == QMediaPlayer.EndOfMedia and self._live():
            import time
            if time.monotonic() - getattr(self, "_live_fixing", 0) >= 8:
                QTimer.singleShot(50, self._live_continue)
            return
        if status == QMediaPlayer.EndOfMedia and self.repeat == "one":
            self.player.setPosition(0)                       # repeat this one
            self.player.play()
            return
        if status == QMediaPlayer.EndOfMedia and (self.repeat == "all" or settings().value("float_autoplay", "true") == "true"):
            if self._neighbour(1):
                QTimer.singleShot(300, lambda: self._step(1))
            elif self.repeat == "all":                       # end of the folder: back to the first one
                files = self._siblings() if not self.link else []
                if len(files) > 1:
                    QTimer.singleShot(300, lambda f=files[0]: (setattr(self, "_play_now", True), self._load(f)))
                else:
                    self.player.setPosition(0)
                    self.player.play()

    def set_repeat(self, mode):
        self.repeat = mode
        settings().setValue("float_repeat", mode)
        self.update()

    def _on_frame(self, frame):
        img = frame.toImage()
        if img.isNull():
            return
        self.frame = img
        if getattr(self, "_first_frame", False):
            self._first_frame = False
            if not self.autoplay:
                self.player.pause()
                self.player.setPosition(self._resume_ms or 0)
                self._resume_ms = 0
                self.audio.setMuted(False)
            a = img.width() / max(1, img.height())
            if abs(a - (self.aspect or 0)) > 0.01:
                self.aspect = a
                tl = self.pos()
                self._apply_size(self.width(), self._height_for(self.width()))
                self.move(tl)
        self.update()

    def _on_subtitle(self, text):
        self.sub_text = text or ""
        self.update()

    def _load_subs(self, path):
        try:
            self.subs = _parse_subtitles(path)
            self.subs_path = path
            self.player.setActiveSubtitleTrack(-1)        # one subtitle source at a time
        except Exception as e:
            winsys.log(f"float: cannot read subtitles {path}: {e}")
            self.subs = None
        self.update()

    def _current_subtitle(self):
        if self.subs:
            pos = self.player.position()
            return "\n".join(t for a, b, t in self.subs if a <= pos <= b)
        return self.sub_text

    @staticmethod
    def _track_name(md, i):
        from PySide6.QtCore import QLocale
        from PySide6.QtMultimedia import QMediaMetaData
        parts = []
        lang = md.value(QMediaMetaData.Language)
        try:
            if lang is not None and lang != QLocale.AnyLanguage:
                parts.append(QLocale.languageToString(lang))
        except Exception:
            pass
        title = md.stringValue(QMediaMetaData.Title)
        if title and title not in parts:
            parts.append(title)
        return " · ".join(parts) or tr("Track {n}", n=i + 1)

    def _add_track_menus(self, m):
        from PySide6.QtGui import QActionGroup
        audio = self.player.audioTracks()
        am = m.addMenu(tr("Audio track"))
        grp = QActionGroup(am)
        for i, md in enumerate(audio):
            a = am.addAction(self._track_name(md, i))
            a.setCheckable(True)
            a.setChecked(i == self.player.activeAudioTrack() or (len(audio) == 1))
            a.triggered.connect(lambda _c=False, i=i: self.player.setActiveAudioTrack(i))
            grp.addAction(a)
        if not audio:
            am.setEnabled(False)
        sm = m.addMenu(tr("Subtitles"))
        grp2 = QActionGroup(sm)
        off = sm.addAction(tr("Off"))
        off.setCheckable(True)
        off.setChecked(not self.subs and self.player.activeSubtitleTrack() < 0)
        off.triggered.connect(self._subs_off)
        grp2.addAction(off)
        for i, md in enumerate(self.player.subtitleTracks()):
            a = sm.addAction(self._track_name(md, i))
            a.setCheckable(True)
            a.setChecked(not self.subs and i == self.player.activeSubtitleTrack())
            a.triggered.connect(lambda _c=False, i=i: self._subs_track(i))
            grp2.addAction(a)
        for f in ([] if self.link else _find_side_subtitles(self.path)):
            a = sm.addAction(Path(f).name)
            a.setCheckable(True)
            a.setChecked(bool(self.subs) and getattr(self, "subs_path", "") == f)
            a.triggered.connect(lambda _c=False, f=f: self._load_subs(f))
            grp2.addAction(a)
        sm.addSeparator()
        sm.addAction(tr("Browse…"), self._browse_subs)

    def _subs_off(self):
        self.subs = None
        self.player.setActiveSubtitleTrack(-1)
        self.sub_text = ""
        self.update()

    def _subs_track(self, i):
        self.subs = None
        self.player.setActiveSubtitleTrack(i)
        self.update()

    def _browse_subs(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Subtitles"), str(Path.home() if self.link else Path(self.path).parent),
                                           "Subtitles (*.srt *.vtt)")
        if f:
            self._load_subs(f)

    # ---- live streams: the player only gets the newest ~30 s at a time, so keep loading the next part
    def _live(self):
        return bool(self.link and self.link.get("live"))

    def _start_relay(self):
        self._stop_relay()
        try:
            self._relay = LiveRelay(self.path, (self.link or {}).get("headers"), (self.link or {}).get("client", ""))
        except Exception as e:
            winsys.log(f"live relay failed: {e}")
            self._relay = None

    def _stop_relay(self):
        r = getattr(self, "_relay", None)
        if r is not None:
            r.close()
            self._relay = None
        for c in getattr(self, "_caches", []):
            threading.Thread(target=c.close, daemon=True).start()
        self._caches = []

    def _cached(self, url, size=None):
        """Local address of the download-ahead copy of `url` (or the url itself if that can't be set up)."""
        try:
            c = StreamCache(url, (self.link or {}).get("headers"), size)
        except Exception as e:
            winsys.log(f"stream cache not used: {e}")
            return url
        self._caches = getattr(self, "_caches", []) + [c]
        if getattr(self, "_expiry_timer", None) is None:
            self._expiry_timer = QTimer(self, interval=2000, timeout=self._check_expired)
        self._expiry_timer.start()
        return c.local

    def _check_expired(self):
        """A video link stopped working (sites give links that last a few hours): get a fresh one, same place."""
        caches = getattr(self, "_caches", [])
        if not caches:
            self._expiry_timer.stop()
            return
        if not any(c.expired for c in caches) or _APP is None or not (self.link or {}).get("page"):
            return
        now = time.monotonic()
        if now - getattr(self, "_renewed_at", 0.0) < 60:
            return                                       # renewed a moment ago: don't loop
        self._renewed_at = now
        self._resume_ms = self.player.position() if self.player is not None else 0
        winsys.log("float: link expired, getting a fresh one")
        for c in caches:
            c.expired = False                            # so this runs once per renewal
        _APP._resolve_and_play(self.link["page"], self, quiet=True)

    def restart_live(self, info):
        """The link was renewed: keep the float as it is (size, place, volume) and carry on playing —
        live streams through a fresh relay, other videos from where they were."""
        if self.player is None or info.get("audio") or self.companion is not None:
            keep = getattr(self, "_resume_ms", 0)
            pos = 0 if info.get("live") else (self.player.position() if self.player is not None else keep)
            self._play_now = True if self.player is not None else getattr(self, "_pin_play", True)
            self._load(info["url"], info)                # picture and sound apart: set both up again
            self._resume_ms = pos
            return
        pos = 0 if info.get("live") else self.player.position()
        self.link = info
        self.path = info["url"]
        self._pos_seen = (-1, 0.0)
        if info.get("live"):
            self._start_relay()
            if self._relay is not None:
                self.player.setSource(QUrl(self._relay.url))
            QTimer.singleShot(20000, self._prefetch_live)
        else:
            self._stop_relay()
            self._resume_ms = pos
            self.autoplay = True
            self.player.setSource(QUrl(self._cached(info["url"], info.get("size")) if _cacheable(info["url"]) else info["url"]))
        self.player.play()

    def _set_quality(self, q):
        settings().setValue("link_quality", q)
        self.refresh_link(quality=q)

    def refresh_link(self, auto=False, quality=None):
        """Ask the site again for the video (its links expire) and continue."""
        if not self.link or _APP is None:
            return
        import time
        self._last_refresh = time.monotonic()
        winsys.log(f"float: refresh link ({'automatic, stuck loading' if auto else 'from the menu'})")
        self._live_fixing = time.monotonic()
        _APP._resolve_and_play(self.link["page"], self, quiet=True, quality=quality)

    def _prefetch_live(self):
        """Fetch a fresh stream link in the background while this one still plays, so a failure is fixed in
        seconds instead of waiting for YouTube."""
        if not self._live() or _APP is None or self.player is None:
            return
        job = LinkResolve(self.link["page"])
        job.setAutoDelete(False)
        _APP._update_jobs.add(job)

        def got(info, err, job=job):
            _APP._update_jobs.discard(job)
            if info and info.get("live"):
                self._spare = (time.monotonic(), info)
        job.sig.done.connect(got, Qt.QueuedConnection)
        _APP.pool.start(job)

    def _live_continue(self, error=False):
        import time
        now = time.monotonic()
        recent = [t for t in getattr(self, "_live_reloads", []) if now - t < 60] + [now]
        self._live_reloads = recent
        spare = getattr(self, "_spare", None)
        if spare and spare[1].get("client") in engine.LIVE_BAD_CLIENTS:
            spare = self._spare = None                   # made for a player YouTube now refuses
        relay = getattr(self, "_relay", None)
        if relay is not None and relay.forbidden:
            alts = [a for a in (self.link or {}).get("alts", []) if a.get("client") not in engine.LIVE_BAD_CLIENTS]
            if alts:                                     # another player's stream is already known: switch now
                nxt = dict(self.link, url=alts[0]["url"], headers=alts[0].get("headers") or {},
                           client=alts[0].get("client", ""), alts=alts[1:])
                winsys.log(f"float: live stream switched to the {nxt['client']} player")
                relay.forbidden = False
                self._live_reloads = []
                self.restart_live(nxt)
                return
        if relay is not None and relay.forbidden and not spare and _APP is not None:
            winsys.log("float: live stream re-opened with another player")
            relay.forbidden = False
            self._live_reloads = []
            _APP._resolve_and_play(self.link["page"], self, quiet=True)
            return
        if spare and now - spare[0] < 90:                 # a fresh link is ready: switch to it right away
            self._spare = None
            winsys.log("float: live stream switched to the fresh link")
            self.restart_live(spare[1])
            return
        # a hiccup: just restart the local relay (2-3 s). Several in a minute: the link has expired, ask YouTube again
        if len(recent) > 3:
            self._live_reloads = []
            if _APP is not None:
                winsys.log(f"float: live stream re-opened ({'error' if error else 'stalled'})")
                _APP._resolve_and_play(self.link["page"], self, quiet=True)
            return
        relay = getattr(self, "_relay", None)
        self.player.setSource(QUrl(relay.url if relay is not None else self.path))   # ffmpeg starts again
        self.player.play()

    def _on_media_error(self, *_a):
        if self._live() and self.player is not None:
            import time
            if time.monotonic() - getattr(self, "_live_fixing", 0) < 8:      # one reconnect at a time
                return
            self._live_fixing = time.monotonic()
            winsys.log(f"float: live stream error, reconnecting: {self.player.errorString()}")
            QTimer.singleShot(300, self._live_continue)
            return
        winsys.log(f"float: cannot play {self.path}: {self.player.errorString()}")
        self.player.stop()
        self.player = None
        self.kind = "other"
        self.art = False
        self.aspect = None
        self.frame = None
        self._apply_size(200, 200)

    def _playing(self):
        from PySide6.QtMultimedia import QMediaPlayer
        return self.player is not None and self.player.playbackState() == QMediaPlayer.PlayingState

    def media_key(self, key):
        """Play/pause, next, previous, stop from the keyboard's media keys."""
        if not self.player:
            return None
        if key == "play":
            self._toggle_play()
            return "pause" if not self._playing() else "play"
        if key == "stop":
            self.player.pause()
            self.player.setPosition(0)
            return "stop"
        return key if self._step(1 if key == "next" else -1) else None

    LONG_PAUSE = 10 * 60          # seconds paused after which Play reopens the float instead

    def _toggle_play(self):
        if not self.player:
            return
        if self._playing():
            self.player.pause()
            self._paused_at = time.monotonic()
        else:
            paused = getattr(self, "_paused_at", None)
            if (paused is not None and time.monotonic() - paused > self.LONG_PAUSE and self.kind == "video"
                    and _APP is not None):
                # after hours (or a night asleep) the player and the video link are stale: the sound came back
                # but the picture and the window froze. Reopen it fresh, same place, size and point in the video.
                winsys.log(f"float: playing again after {int((time.monotonic() - paused) / 60)} min paused — reopening")
                self.reopen(play=True)
                return
            self._paused_at = None
            if self.player.duration() and self.player.position() >= self.player.duration() - 200:
                self.player.setPosition(0)
            self.player.play()

    # ---------------------------------------------------------------- geometry
    def _height_for(self, w):
        if self.aspect:
            return int(round(w / self.aspect))
        return w if self.kind == "other" else 150      # audio: a short card

    def _apply_size(self, w, h):
        scr = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        w = max(self.MIN_W, min(int(w), scr.width()))
        h = max(110, min(int(h), scr.height()))
        if self.aspect:                                   # keep the shape when a limit kicked in
            if w / h > self.aspect + 0.01:
                w = max(self.MIN_W, int(h * self.aspect))
            else:
                h = max(110, int(w / self.aspect))
        self.resize(w, h)
        self._scaled = None
        self.update()

    def _close_center(self):
        return QPointF(self.width() - 20, 20)

    def _band_h(self):
        return 62 if self.player else 40

    def _grip_rect(self):
        return QRectF(self.width() - 42, self.height() - 36, 30, 26)

    def _seek_rect(self):
        return QRectF(14, self.height() - 52, self.width() - 28, 4)

    def _vol_rect(self):
        return QRectF(44, self.height() - 27, 74, 6)

    def _set_volume_x(self, x):
        r = self._vol_rect()
        v = min(1.0, max(0.0, (x - r.left()) / r.width()))
        self.audio.setVolume(v)
        self.audio.setMuted(False)
        settings().setValue("float_volume", round(v, 3))
        self.update()

    def _mute_rect(self):
        return QRectF(10, self.height() - 38, 28, 28)

    def _play_center(self):
        if self.kind == "audio" and not self.art:
            return QPointF(self.width() / 2, (self.height() - self._band_h()) / 2 + 8)
        return QPointF(self.width() / 2, self.height() / 2 - 8)

    def _icon_rect(self):
        side = min(self.width(), self.height() - self._band_h()) * 0.55
        side = max(48, min(side, 256))
        cx, cy = self.width() / 2, (self.height() - self._band_h()) / 2 + 6
        return QRectF(cx - side / 2, cy - side / 2, side, side)

    def _edges(self, pos):
        e, c = self.EDGE, 18                                 # edge band, corner grab area
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        l, t, r, b = x < e, y < e, x > w - e, y > h - e
        if (x < c or x > w - c) and (y < c or y > h - c) and (l or t or r or b):
            l, r, t, b = x < c, x > w - c, y < c, y > h - c    # near a corner: grab the corner
        return (l, t, r, b)                                   # left, top, right, bottom

    def _hit(self, pos):
        c = self._close_center()
        controls = self.ctrl > 0.4
        if controls and (pos.x() - c.x()) ** 2 + (pos.y() - c.y()) ** 2 <= (self.CLOSE_R + 4) ** 2:
            return "close"
        if controls and self._grip_rect().contains(pos):
            return "grip"
        if any(self._edges(pos)):
            return "edge"
        if self.player and controls:
            if self._seek_rect().adjusted(0, -8, 0, 8).contains(pos) and not self._live():
                return "seek"
            if self._mute_rect().contains(pos):
                return "mute"
            if self._vol_open and QRectF(38, self.height() - 38, 88, 28).contains(pos):
                return "vol"
            pc = self._play_center()
            if (pos.x() - pc.x()) ** 2 + (pos.y() - pc.y()) ** 2 <= 30 ** 2:
                return "play"
            for name, dx in (("prev", -62), ("next", 62)):
                if (pos.x() - pc.x() - dx) ** 2 + (pos.y() - pc.y()) ** 2 <= 22 ** 2:
                    return name
        if self.kind == "other" and self._icon_rect().contains(pos):
            return "icon"
        return "body"

    # ---------------------------------------------------------------- fading controls
    def set_taskbar(self, on):
        """Show this float as a button on the taskbar (so it's easy to get back to), or not."""
        geo, vis = self.geometry(), self.isVisible()
        self.setWindowFlag(Qt.Tool, not on)
        self.setWindowFlag(Qt.Window, True)
        self.setGeometry(geo)
        if vis:
            self.show()

    def set_on_top(self, on):
        self.on_top = bool(on)
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.on_top)
        self.setGeometry(geo)
        self.show()
        self._pin_changed()

    # ---------------------------------------------------------------- reopen when Windows starts
    def set_pinned(self, on):
        pins = [x for x in _float_pins() if x.get("id") != self.pin_id]
        if on:
            import uuid
            self.pin_id = self.pin_id or uuid.uuid4().hex[:12]
            _save_float_pins(pins)
            self._save_pin()
            if not winsys.startup_enabled():          # ConvertANNY itself has to start with Windows
                try:
                    winsys.set_startup(True)
                except Exception as e:
                    winsys.log(f"startup: {e}")
        else:
            self.pin_id = None
            _save_float_pins(pins)

    def _pin_changed(self):
        if getattr(self, "pin_id", None) and not getattr(self, "_placing", False):
            self._pin_timer.start()

    def state(self) -> dict:
        """Everything needed to bring this float back: file or link, place, size, playback."""
        g = self.geometry()
        st = {"id": self.pin_id, "src": self.link["page"] if self.link else str(self.path), "link": bool(self.link),
              "title": (self.link or {}).get("title", ""),
              "x": g.x(), "y": g.y(), "w": g.width(), "h": g.height(), "on_top": self.on_top}
        if self.player is not None and not self._live():
            st["pos"] = int(self.player.position())
            st["playing"] = bool(self._playing())
        return st

    def _save_pin(self):
        if not self.pin_id:
            return
        entry = self.state()
        entry.pop("pos", None)
        entry.pop("playing", None)
        pins = [x for x in _float_pins() if x.get("id") != self.pin_id] + [entry]
        _save_float_pins(pins)

    def moveEvent(self, e):
        super().moveEvent(e)
        self._pin_changed()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._pin_changed()

    def reopen(self, play=None):
        """Close this float and open it again: same size, place and media, from the same point."""
        if _APP is None or not self._has_content():
            return
        st = self.state()
        if play is not None:
            st["playing"] = bool(play)
        if self.link:
            st["src"] = self.link.get("saved") or self.link.get("page")
        winsys.log("float: reopen")
        self._pin_timer.stop()
        self.hide()
        QTimer.singleShot(0, self.close)                 # stays pinned to Windows start (not closed by you)
        QTimer.singleShot(120, lambda: _APP.open_float_state(st))

    def close_by_user(self):
        """Closed with ✕, Esc or the menu: it no longer reopens with Windows."""
        if self.pin_id:
            self.set_pinned(False)
        self.close()

    def _set_ctrl(self, v):
        self.ctrl = float(v)
        self.update()

    def _fade_to(self, target):
        if abs(self.ctrl - target) < 0.01 and self._fade.state() != QVariantAnimation.Running:
            return
        self._fade.stop()
        self._fade.setStartValue(self.ctrl)
        self._fade.setEndValue(float(target))
        self._fade.start()

    def _maybe_hide_controls(self):
        if not self.underMouse() and self._press is None:
            self._fade_to(0.0)

    def enterEvent(self, e):
        self._fade_to(1.0)

    def leaveEvent(self, e):
        self.hover = None
        self._vol_open = False
        if self._press is None:
            self._fade_to(0.0)
        self.update()

    # ---------------------------------------------------------------- paint
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(r, self.RADIUS, self.RADIUS)
        p.setClipPath(clip)
        bare = self.kind == "other" and not self.link and settings().value("float_icon_only", "true") == "true"
        if bare:                                            # just the icon and its name: no panel, frame or highlight
            p.fillRect(r, QColor(0, 0, 0, 1))               # (all but invisible, so the float still takes the mouse)
        else:
            p.fillRect(r, QColor(0, 0, 0) if self.kind == "video" else C("panel"))
        media = self.kind in ("image", "video") or self.art
        if self.kind == "image" or self.art:
            if self._scaled is None or self._scaled.size() != self.size():
                self._scaled = self.src.scaled(self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(0, 0, self._scaled)
        elif self.kind == "video":
            if self.frame is not None:
                fr = QSizeF(self.frame.size()).scaled(QSizeF(self.size()), Qt.KeepAspectRatio)
                p.drawImage(QRectF((self.width() - fr.width()) / 2, (self.height() - fr.height()) / 2,
                                   fr.width(), fr.height()), self.frame)
        elif self.kind == "empty":
            box = r.adjusted(10, 10, -10, -10)
            pen = QPen(ACCENT if self._drop_hover else C("line"), 1.6, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box, 10, 10)
            p.setPen(C("text"))
            p.setFont(QFont(i18n.ui_font(), 11, QFont.DemiBold))
            p.drawText(box.adjusted(12, 0, -12, -box.height() / 2 + 6), Qt.AlignHCenter | Qt.AlignBottom, tr("Drop a file here"))
            p.setPen(C("dim"))
            p.setFont(QFont(i18n.ui_font(), 9))
            p.drawText(box.adjusted(14, box.height() / 2 + 8, -14, -8), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                       tr("or press Ctrl+V to play a copied link · right-click for saved links"))
        else:                                               # icon, centred; highlights on hover
            ir = self._icon_rect()
            if self.hover == "icon" and not bare:
                hl = QColor(ACCENT)
                hl.setAlpha(46)
                p.setPen(QPen(ACCENT, 1.5))
                p.setBrush(hl)
                p.drawRoundedRect(ir.adjusted(-12, -12, 12, 12), 16, 16)
            p.drawPixmap(ir.toRect(), self.src.scaled(int(ir.width()), int(ir.height()),
                                                       Qt.KeepAspectRatio, Qt.SmoothTransformation))
            if bare and settings().value("float_hide_name", "false") != "true":   # the name under the icon
                pt = max(7.0, min(22.0, ir.width() * 0.085))     # grows and shrinks with the icon
                nf = QFont(i18n.ui_font())
                nf.setPointSizeF(pt)
                nf.setBold(True)
                p.setFont(nf)
                nr = QRectF(6, ir.bottom() + pt * 0.4, self.width() - 12, pt * 3)
                pp = Path(self.path or "")
                label = pp.name if pp.is_dir() or not pp.suffix else pp.stem      # no ".zip", ".exe"…
                txt = QFontMetrics(nf).elidedText(label, Qt.ElideRight, int(nr.width()))
                p.setPen(QColor(0, 0, 0, 170))
                for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1), (0, 1.5)):
                    p.drawText(nr.translated(dx, dy), Qt.AlignHCenter | Qt.AlignTop, txt)
                p.setPen(QColor("#ffffff"))
                p.drawText(nr, Qt.AlignHCenter | Qt.AlignTop, txt)
        # ---- subtitles (above the controls when they are showing)
        if self.kind == "video" and self.player:
            text = self._current_subtitle()
            if text:
                self._paint_subtitle(p, text)
        if getattr(self, "_busy", False) and self.kind == "video" and (self.player is not None or (self.link or {}).get("pending")):
            self._paint_busy(p)
        # ---- overlay controls (fade with the cursor)
        if self.ctrl > 0.01:
            p.setOpacity(self.ctrl)
            band = self._band_h()
            if media:
                g = QLinearGradient(0, self.height() - band - 30, 0, self.height())
                g.setColorAt(0, QColor(0, 0, 0, 0))
                g.setColorAt(1, QColor(0, 0, 0, 175))
                p.fillRect(QRectF(0, self.height() - band - 30, self.width(), band + 30), g)
            fg = QColor("#ffffff") if media else C("text")
            f = QFont(i18n.ui_font(), 9)
            p.setFont(f)
            left = 14
            if self.player:
                self._paint_player(p, fg)
                left = 44
                if self._vol_open:                         # volume slider next to the speaker
                    vr = self._vol_rect()
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(255, 255, 255, 70) if (self.kind == "video" or self.art) else C("busy_track"))
                    p.drawRoundedRect(vr, 3, 3)
                    vol = 0.0 if self.audio.isMuted() else self.audio.volume()
                    p.setBrush(ACCENT)
                    p.drawRoundedRect(QRectF(vr.left(), vr.top(), vr.width() * vol, vr.height()), 3, 3)
                    p.drawEllipse(QPointF(vr.left() + vr.width() * vol, vr.center().y()), 6, 6)
                    left = 130
                t = ("● " + tr("LIVE")) if self._live() else f"{_fmt_time(self.player.position())} / {_fmt_time(self.player.duration())}"
                if not self._live() and self.repeat in ("one", "all"):
                    t += "   ↻" + ("1" if self.repeat == "one" or self.link else "")
                p.setPen(fg)
                tw = QFontMetrics(f).horizontalAdvance(t) + 12
                p.drawText(QRectF(left, self.height() - 38, tw, 28), Qt.AlignVCenter | Qt.AlignLeft, t)
                left += tw
            name_r = QRectF(left, self.height() - 38, self._grip_rect().left() - left - 6, 28)
            if not bare:                                    # (a bare icon has its name under it all the time)
                p.setPen(fg)
                p.drawText(name_r, Qt.AlignVCenter | Qt.AlignLeft,
                           QFontMetrics(f).elidedText(self.display_name(), Qt.ElideMiddle, int(max(0, name_r.width()))))
            gr = self._grip_rect()
            p.setPen(Qt.NoPen)
            p.setBrush(ACCENT if self.hover == "grip" else (QColor(255, 255, 255, 46) if media else C("grip")))
            p.drawRoundedRect(gr, 7, 7)
            p.setBrush(ON_ACCENT if self.hover == "grip" else fg)
            for i in range(3):
                for j in range(2):
                    p.drawEllipse(QPointF(gr.center().x() - 3 + j * 6, gr.center().y() - 5 + i * 5), 1.6, 1.6)
            c = self._close_center()
            p.setBrush(C("danger") if self.hover == "close" else QColor(20, 20, 22, 190))
            p.setPen(QPen(QColor(255, 255, 255, 70), 1))
            p.drawEllipse(c, self.CLOSE_R, self.CLOSE_R)
            pen = QPen(QColor("#ffffff"), 2)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            d = 4.2
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))
            p.setOpacity(1.0)
        # border
        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        if self._drop_hover:                                # a file is being dragged over: drop replaces
            p.setPen(QPen(ACCENT, 3))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), self.RADIUS, self.RADIUS)
        else:
            col = QColor(ACCENT if (self.hover and self.hover != "icon") else C("line"))
            if bare:                                        # icon only: never a frame
                col.setAlphaF(0.0)
            if col.alphaF() > 0.01:
                p.setPen(QPen(col, 1.2))
                p.drawRoundedRect(r, self.RADIUS, self.RADIUS)

    def _paint_subtitle(self, p, text):
        size = max(10, min(22, self.height() / 18))
        f = QFont(i18n.ui_font(), 1)
        f.setPointSizeF(size)
        f.setWeight(QFont.DemiBold)
        fm = QFontMetrics(f)
        bottom = self.height() - (self._band_h() + 8) * self.ctrl - 12
        width = self.width() - 32
        rect = fm.boundingRect(QRect(0, 0, int(width), 1000), Qt.AlignHCenter | Qt.TextWordWrap, text)
        box = QRectF((self.width() - rect.width()) / 2 - 8, bottom - rect.height() - 4, rect.width() + 16, rect.height() + 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(box, 6, 6)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(box, Qt.AlignCenter | Qt.TextWordWrap, text)

    def _paint_player(self, p, fg):
        # big play / pause in the middle (hidden while the loading circle shows, like YouTube)
        pc = self._play_center()
        p.setPen(Qt.NoPen)
        if getattr(self, "_busy", False) and self.kind == "video":
            p.setOpacity(0.0)
        p.setBrush(ACCENT if self.hover == "play" else QColor(20, 20, 22, 170))
        p.drawEllipse(pc, 26, 26)
        p.setBrush(ON_ACCENT if self.hover == "play" else QColor("#ffffff"))
        if self._playing():
            p.drawRoundedRect(QRectF(pc.x() - 8, pc.y() - 10, 6, 20), 2, 2)
            p.drawRoundedRect(QRectF(pc.x() + 2, pc.y() - 10, 6, 20), 2, 2)
        else:
            tri = QPolygonF([QPointF(pc.x() - 7, pc.y() - 11), QPointF(pc.x() - 7, pc.y() + 11), QPointF(pc.x() + 11, pc.y())])
            p.drawPolygon(tri)
        # previous / next in the folder (dimmed at the ends)
        for name, dx, d in (("prev", -62, -1), ("next", 62, 1)):
            c = QPointF(pc.x() + dx, pc.y())
            have = self._neighbour(d) is not None
            p.setOpacity(0.0 if (getattr(self, "_busy", False) and self.kind == "video") else self.ctrl * (1.0 if have else 0.35))
            p.setBrush(ACCENT if (self.hover == name and have) else QColor(20, 20, 22, 150))
            p.drawEllipse(c, 18, 18)
            p.setBrush(ON_ACCENT if (self.hover == name and have) else QColor("#ffffff"))
            sgn = 1 if d > 0 else -1
            p.drawPolygon(QPolygonF([QPointF(c.x() - 5 * sgn, c.y() - 7), QPointF(c.x() - 5 * sgn, c.y() + 7),
                                     QPointF(c.x() + 4 * sgn, c.y())]))
            p.drawRect(QRectF(c.x() + 4 * sgn - (2 if sgn > 0 else 0), c.y() - 7, 2, 14))
        p.setOpacity(self.ctrl)
        # seek bar
        sr = self._seek_rect()
        p.setBrush(QColor(255, 255, 255, 70) if (self.kind == "video" or self.art) else C("busy_track"))
        p.drawRoundedRect(sr, 2, 2)
        dur = self.player.duration()
        if dur > 0 and not self._live():
            frac = min(1.0, self.player.position() / dur)
            p.setBrush(ACCENT)
            p.drawRoundedRect(QRectF(sr.left(), sr.top(), sr.width() * frac, sr.height()), 2, 2)
            p.drawEllipse(QPointF(sr.left() + sr.width() * frac, sr.center().y()), 6 if self.hover == "seek" else 4.5,
                          6 if self.hover == "seek" else 4.5)
        # speaker (click to mute)
        mr = self._mute_rect()
        cx, cy = mr.center().x(), mr.center().y()
        p.setBrush(ACCENT if self.hover == "mute" else fg)
        p.drawPolygon(QPolygonF([QPointF(cx - 8, cy - 3), QPointF(cx - 4, cy - 3), QPointF(cx + 1, cy - 8),
                                 QPointF(cx + 1, cy + 8), QPointF(cx - 4, cy + 3), QPointF(cx - 8, cy + 3)]))
        pen = QPen(ACCENT if self.hover == "mute" else fg, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if self.audio.isMuted():
            p.drawLine(QPointF(cx + 4, cy - 4), QPointF(cx + 10, cy + 4))
            p.drawLine(QPointF(cx + 10, cy - 4), QPointF(cx + 4, cy + 4))
        else:
            p.drawArc(QRectF(cx - 3, cy - 6, 10, 12), -50 * 16, 100 * 16)
            p.drawArc(QRectF(cx - 3, cy - 10, 16, 20), -50 * 16, 100 * 16)
        p.setPen(Qt.NoPen)

    # ---------------------------------------------------------------- mouse
    def _seek_to(self, x):
        sr = self._seek_rect()
        if self.player and self.player.duration() > 0:
            frac = min(1.0, max(0.0, (x - sr.left()) / max(1.0, sr.width())))
            self.player.setPosition(int(self.player.duration() * frac))

    last_used = None                 # the float the keyboard media keys control

    def mousePressEvent(self, e):
        FloatWindow.last_used = self
        if e.button() == Qt.RightButton:
            self._menu(e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        hit = self._hit(e.position())
        gp = e.globalPosition().toPoint()
        if hit == "close":
            self.close_by_user()
            return
        if hit == "mute":
            self.audio.setMuted(not self.audio.isMuted())
            self.update()
            return
        if hit == "vol":
            self._vol_drag = True
            self._set_volume_x(e.position().x())
            return
        if hit == "seek":
            self._seeking = True
            self._seek_to(e.position().x())
        if hit == "edge":
            self._press = ("edge", gp, e.position(), self.geometry(), self._edges(e.position()))
        else:
            self._press = (hit, gp, e.position(), self.geometry(), None)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._vol_drag:
            self._set_volume_x(pos.x())
            return
        if self._press is not None:
            kind, gp0, lp0, geo0, edges = self._press
            gp = e.globalPosition().toPoint()
            moved = (gp - gp0).manhattanLength()
            if self._seeking:
                self._seek_to(pos.x())
            elif kind == "grip":
                if moved > 6:
                    self._press = None
                    self._drag_out()
            elif kind == "edge":
                self._resize_drag(gp - gp0, geo0, edges)
            elif moved > 3 or kind == "moving":
                if kind != "moving":
                    self._press = ("moving", gp0, lp0, geo0, None)
                self.move(geo0.topLeft() + (gp - gp0))
            return
        h = self._hit(pos)
        vol_open = h in ("mute", "vol")
        if vol_open != self._vol_open:
            self._vol_open = vol_open
            h = self._hit(pos)
            self.update()
        if h != self.hover:
            self.hover = h
            if h == "edge":
                l, t, r, b = self._edges(pos)
                cur = (Qt.SizeFDiagCursor if (l and t) or (r and b) else Qt.SizeBDiagCursor if (r and t) or (l and b)
                       else Qt.SizeHorCursor if (l or r) else Qt.SizeVerCursor)
            else:
                cur = {"close": Qt.PointingHandCursor, "grip": Qt.OpenHandCursor, "icon": Qt.PointingHandCursor,
                       "play": Qt.PointingHandCursor, "prev": Qt.PointingHandCursor, "next": Qt.PointingHandCursor, "seek": Qt.PointingHandCursor, "mute": Qt.PointingHandCursor, "vol": Qt.PointingHandCursor
                       }.get(h, Qt.SizeAllCursor)
            self.setCursor(cur)
            self.update()

    def _resize_drag(self, delta, geo0, edges):
        l, t, r, b = edges
        x, y, w, h = geo0.x(), geo0.y(), geo0.width(), geo0.height()
        dw = (delta.x() if r else -delta.x() if l else 0)
        dh = (delta.y() if b else -delta.y() if t else 0)
        nw, nh = w + dw, h + dh
        if self.aspect:                       # keep the picture's shape
            if (l or r) and (t or b):         # corner: follow the mouse in any direction (project on the diagonal)
                k = (dw * self.aspect + dh) / (self.aspect ** 2 + 1)
                nw, nh = w + k * self.aspect, h + k
            elif l or r:
                nh = nw / self.aspect
            else:
                nw = nh * self.aspect
        self._apply_size(nw, nh)
        nw, nh = self.width(), self.height()
        nx = x + (w - nw) if l else x
        ny = y + (h - nh) if t else y
        if self.aspect and (t or b) and not (l or r):          # grow sideways around the centre
            nx = x + (w - nw) // 2
        if self.aspect and (l or r) and not (t or b):
            ny = y + (h - nh) // 2
        self.move(int(nx), int(ny))

    def mouseReleaseEvent(self, e):
        self._vol_drag = False
        press, self._press = self._press, None
        was_seeking, self._seeking = self._seeking, False
        if press is None or was_seeking or e.button() != Qt.LeftButton:
            return
        kind = press[0]
        if kind == "icon":
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))
        elif kind in ("prev", "next"):
            self._step(-1 if kind == "prev" else 1)
        elif kind == "play" or (kind == "body" and self.kind == "video"):
            self._toggle_play()
        if not self.underMouse():
            self._fade_to(0.0)

    def mouseDoubleClickEvent(self, e):
        if self._hit(e.position()) in ("body", "icon") and self._nothing_playing():
            self._press = None
            QTimer.singleShot(0, self._browse_file)                       # nothing showing or playing: double-click picks a file
            return
        if self._hit(e.position()) == "body" and self.kind == "image":
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))

    def wheelEvent(self, e):
        if self.player and self.hover in ("mute", "vol"):          # scroll over the speaker = volume
            v = min(1.0, max(0.0, self.audio.volume() + (0.05 if e.angleDelta().y() > 0 else -0.05)))
            self.audio.setVolume(v)
            self.audio.setMuted(False)
            settings().setValue("float_volume", round(v, 3))
            self.update()
            return
        step = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
        g0 = self.geometry()
        self._apply_size(self.width() * step, (self._height_for(self.width() * step) if self.aspect
                                                else self.height() * step))
        dw, dh = self.width() - g0.width(), self.height() - g0.height()
        if dw or dh:                                 # grow or shrink around the middle; at a limit it stays put
            self._grow_left = getattr(self, "_grow_left", 0.0) + dw / 2
            self._grow_top = getattr(self, "_grow_top", 0.0) + dh / 2
            mx, my = int(self._grow_left), int(self._grow_top)    # whole pixels, the rest kept for next time
            self._grow_left -= mx
            self._grow_top -= my
            self.move(g0.x() - mx, g0.y() - my)

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Paste):
            f = _clipboard_media_file()
            if f:                                    # a copied video/song (or its path) plays here
                self._play_now = True
                self._load(f)
                self._fade_to(1.0)
                self.come_forward()
                QTimer.singleShot(1600, self._maybe_hide_controls)
            elif _APP is not None:
                _APP.play_link(target=self)
            return
        if e.key() == Qt.Key_Escape:
            self.close_by_user()
        elif e.key() == Qt.Key_Space and self.player:
            self._toggle_play()
        elif e.key() == Qt.Key_R and self.player:                             # R: repeat off → this one → all
            order = ["off", "one"] if self.link else ["off", "one", "all"]
            self.set_repeat(order[(order.index(self.repeat) + 1) % len(order)] if self.repeat in order else "off")
        elif e.key() in (Qt.Key_PageUp, Qt.Key_PageDown) and self.player:     # media keys: ConvertANNYApp._media_tick
            self._step(-1 if e.key() == Qt.Key_PageUp else 1)
        elif e.key() in (Qt.Key_Left, Qt.Key_Right) and self.player:
            self.player.setPosition(max(0, self.player.position() + (5000 if e.key() == Qt.Key_Right else -5000)))

    def _drag_out(self):
        md = QMimeData()
        md.setUrls([QUrl(self.link["page"]) if self.link else QUrl.fromLocalFile(self.path)])
        drag = QDrag(self)
        drag.setMimeData(md)
        thumb = QPixmap.fromImage(self.frame) if (self.kind == "video" and self.frame is not None) else self.src
        drag.setPixmap(thumb.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        drag.exec(Qt.CopyAction | Qt.MoveAction | Qt.LinkAction, Qt.CopyAction)

    def _menu(self, at):
        m = QMenu(self)
        if self.kind == "video" and self.player:
            self._add_track_menus(m)
        if self.player and not self._live():
            rm = m.addMenu(tr("Repeat"))
            for key, label in (("off", tr("Off")), ("one", tr("Repeat this one")),
                               ("all", tr("Loop all (the whole folder)") if not self.link else tr("Loop"))):
                if self.link and key == "all":
                    continue
                a = rm.addAction(label)
                a.setCheckable(True)
                a.setChecked(bool(self.repeat == key or (self.link and key == "one" and self.repeat == "all")))
                a.triggered.connect(lambda _=False, k=key: self.set_repeat(k))
            sp = m.addMenu(tr("Speed"))
            cur = self.player.playbackRate()
            for rate in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
                a = sp.addAction(f"{rate:g}×" + ("  (" + tr("Normal") + ")" if rate == 1.0 else ""))
                a.setCheckable(True)
                a.setChecked(abs(cur - rate) < 0.01)
                a.triggered.connect(lambda _=False, r=rate: self.set_rate(r))
        if self.player:
            m.addSeparator()
        m.addAction(tr("Open"), self._open_original)
        if self.link:
            m.addAction(tr("Copy"), lambda: QGuiApplication.clipboard().setText(self.link["page"]))
        elif self._has_content():
            m.addAction(tr("Show in Explorer"), lambda: winsys.reveal(self.path))
            m.addAction(tr("Copy path"), lambda: QGuiApplication.clipboard().setText(str(Path(self.path))))
        if self.link:
            m.addAction(tr("Refresh"), self.refresh_link)
            qm = m.addMenu(tr("Quality"))
            cur = settings().value("link_quality", "1080p")
            for q in engine.LINK_QUALITIES:
                a = qm.addAction(q + (f"  ({tr('now playing')})" if self.link.get("height") and str(self.link.get("height")) + "p" == q else ""))
                a.setCheckable(True)
                a.setChecked(q == cur)
                a.triggered.connect(lambda _=False, q=q: self._set_quality(q))
        if _APP is not None:
            m.addAction(tr("Paste link"), lambda: _APP.play_link(target=self))
            saved = saved_links()
            cur_key = self.link and (self.link.get("saved") or self.link.get("page"))
            is_saved = bool(cur_key) and any(x["url"] == cur_key for x in saved)
            if cur_key and not is_saved:
                m.addAction(tr("Save this link"), lambda _=False, k=cur_key: (
                    remember_link(k, self.link.get("title") if self.link else None), self.update()))
            sm = m.addMenu(tr("Saved links"))
            if not saved:
                a = sm.addAction(tr("Links you save show up here"))
                a.setEnabled(False)
            for it in saved[:5]:                            # the last five; all of them in Manage saved links
                title = link_name(it)
                title = title if len(title) <= 60 else title[:57] + "…"
                a = sm.addAction(title, lambda _=False, u=it["url"]: _APP.play_link(target=self, url=u))
                a.setToolTip(it["url"])
            if saved:
                sm.addSeparator()
                cur_key = next((x["url"] for x in saved if self.link and x["url"] in (self.link.get("saved"), self.link.get("page"))), None)
                if cur_key:
                    sm.addAction(tr("Rename this link…"), self._rename_link)
                    sm.addAction(tr("Remove this link from the list"), lambda _=False, k=cur_key: forget_link(k))
                sm.addAction(tr("Manage saved links…"),
                             lambda: SavedLinksDialog(lambda u: _APP.play_link(target=self, url=u)).exec())
                sm.addAction(tr("Clear the list"), lambda: settings().setValue("float_links", "[]"))
            sm.setToolTipsVisible(True)
            rm = m.addMenu(tr("Recently played"))
            recent = recent_played()
            if not recent:
                a = rm.addAction(tr("Links and files you play in Float show up here"))
                a.setEnabled(False)
            for it in recent[:10]:
                t = it.get("title") or it["key"]
                t = t if len(t) <= 60 else t[:57] + "…"
                a = rm.addAction(("🔗  " if it["kind"] == "link" else "🎞  ") + t,
                                 lambda _=False, it=it: self._play_recent(it))
                a.setToolTip(it["key"])
            if recent:
                rm.addSeparator()
                rm.addAction(tr("Manage recently played…"), lambda: RecentPlayedDialog(self._play_recent).exec())
                rm.addAction(tr("Clear the list"), lambda: forget_played())
            rm.setToolTipsVisible(True)
        m.addSeparator()
        top = m.addAction(tr("Always on top"))
        top.setCheckable(True)
        top.setChecked(self.on_top)
        top.toggled.connect(self.set_on_top)
        boot = m.addAction(tr("Open when Windows starts"))
        boot.setCheckable(True)
        boot.setChecked(bool(self.pin_id))
        boot.setToolTip(tr("This float comes back at the same place, playing the same file or link"))
        boot.toggled.connect(self.set_pinned)
        if self._has_content() and _APP is not None:
            m.addAction(tr("Reopen"), self.reopen)
        m.addAction(tr("Close"), self.close_by_user)
        m.exec(at)

    def closeEvent(self, e):
        self._drop_companion()
        self._stop_relay()
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self.closed.emit()
        super().closeEvent(e)


# ============================================================================
# Dialog styling + parameter prompt (trim times, password…)
# ============================================================================
# Settings: the pages down the left side and which sections each one shows (by their English names)
SETTINGS_PAGES = [
    ("general", "General", "Language, look, and how ConvertANNY starts with Windows",
     ["Appearance", "Startup", "Right-click menu"]),
    ("wheel", "Wheel", "The keys and gestures that open the wheel while you drag a file",
     ["Wheel keys", "Mouse Control", "Animations"]),
    ("sounds", "Sounds & notifications", "What you see and hear when a job finishes",
     ["When a job finishes"]),
    ("files", "Files & jobs", "Where results go, and how several jobs run",
     ["Output", "Jobs", "Auto Convert"]),
    ("float", "Float", "The mini player for pictures, videos, music and links",
     ["Float"]),
    ("customize", "Customize", "Choose the slices, and add your own slices, presets and chains",
     ["Wheel slices", "Custom Slices", "Presets and chains"]),
    ("advanced", "Advanced", "Command line, moving to another PC, help and crash reports",
     ["Command line", "Settings Config", "Help"]),
    ("about", "About", "", None),
]

def nav_icon(kind: str) -> "QIcon":
    from ui_icons import navigation_icon
    return navigation_icon(kind, normal=C("dim").name(), selected=C("text").name(),
                           accent=ACCENT.name(), background=C("bg").name())


SETTINGS_CSS = """
QListWidget#nav{background:transparent;border:none;padding:0;outline:0;font:700 10.5pt 'Segoe UI'}
QListWidget#nav::item{color:$dim;padding:11px 12px;margin:2px 0;border-radius:8px;font:700 10.5pt 'Segoe UI'}
QListWidget#nav::item:hover{background:$surface;color:$text}
QListWidget#nav::item:selected{background:$surface;color:$text;border-left:3px solid $accent}
QLabel#pagetitle{color:$text;font:600 17pt 'Segoe UI';padding:2px 0 0 2px}
QLabel#pagesub{color:$dim;font:9.5pt 'Segoe UI';padding:0 0 6px 2px}
QGroupBox#section{background:$surface;color:$text;font:600 10pt 'Segoe UI';border:1px solid $border;border-radius:10px;
margin-top:30px;padding:14px 12px 12px 12px}
QGroupBox#section::title{subcontrol-origin:margin;subcontrol-position:top left;left:4px;top:4px;padding:0 2px}
QGroupBox#section QLabel,QGroupBox#section QCheckBox{background:transparent}
QPushButton#keycap{background:$bg;color:$text;border:1px solid $border;border-radius:6px;padding:6px 10px;
font:600 10pt 'Segoe UI';text-align:left} QPushButton#keycap:hover{border-color:$accent}
QPushButton#keycap:focus{border-color:$accent}
"""

DIALOG_CSS = """
*{font-family:'Segoe UI'}
QDialog{background:$bg} QWidget#page{background:$bg} QLabel{color:$text;font:10pt 'Segoe UI'} QGroupBox{color:$dim;font:600 9pt 'Segoe UI';
border:1px solid $border;border-radius:8px;margin-top:22px;padding:10px 8px 8px 8px} QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;padding:0 6px;left:8px;top:0px}
QLineEdit,QComboBox{background:$surface;color:$text;border:1px solid $border;border-radius:6px;padding:5px 8px;font:10pt 'Segoe UI'}
QLineEdit:focus,QComboBox:focus{border-color:$accent} QCheckBox,QRadioButton{color:$text;font:10pt 'Segoe UI';spacing:10px}
QListWidget{font:10pt 'Segoe UI'} QListWidget::indicator{margin-right:10px}
QListWidget{background:$surface;color:$text;border:1px solid $border;border-radius:6px;padding:2px}
QScrollBar:vertical{background:transparent;width:10px;margin:2px} QScrollBar::handle:vertical{background:$button;border-radius:4px;min-height:30px}
QScrollBar::handle:vertical:hover{background:$hover} QScrollBar::add-line,QScrollBar::sub-line{height:0;width:0} QScrollBar::add-page,QScrollBar::sub-page{background:transparent}
QSlider::groove:horizontal{height:4px;background:$border;border-radius:2px} QSlider::sub-page:horizontal{background:$accent;border-radius:2px}
QSlider::handle:horizontal{background:$text;width:14px;height:14px;margin:-5px 0;border-radius:7px}
QListWidget{outline:0} QListWidget::item{padding:3px 4px;border:none} QListWidget::item:focus{border:none;outline:none}
QListWidget::item:selected{background:$accent;color:$on_accent;border-radius:4px}
QListWidget QLineEdit{background:$surface;color:$text;border:1px solid $accent;border-radius:4px;padding:2px 6px}
QPushButton{background:$button;color:$text;border:none;border-radius:6px;padding:6px 16px;font:600 9pt 'Segoe UI'}
QPushButton:default{background:$accent;color:$on_accent} QPushButton:hover{background:$hover} QPushButton:default:hover{background:$accent2}
QPushButton:pressed{background:$border} QPushButton:default:pressed{background:$accent} QPushButton:focus{outline:none}
QComboBox QAbstractItemView{background:$surface;color:$text;selection-background-color:$accent;selection-color:$on_accent}
QMessageBox{background:$bg}
QTabWidget::pane{border:none;background:$bg} QTabWidget{background:$bg}
QTabBar{background:transparent;qproperty-drawBase:0} QTabWidget::tab-bar{left:4px} QTabBar::tab{background:transparent;color:$dim;padding:9px 22px;margin:0 2px;border:none;
border-bottom:2px solid transparent;font:600 10pt 'Segoe UI'} QTabBar::tab:selected{color:$text;border-bottom:2px solid $accent}
QTabBar::tab:hover{color:$text}
QPushButton#link{background:transparent;color:$link;padding:6px 10px;border:1px solid $border;border-radius:8px}
QPushButton#link:hover{background:$hover}
QLabel#appname{font:700 20pt 'Segoe UI';color:$text} QLabel#tagline{color:$dim;font:10pt 'Segoe UI'}
QLabel#version{color:$accent;font:600 10pt 'Segoe UI'} QLabel#dim{color:$dim;font:9pt 'Segoe UI'}
QFrame#card{background:$surface;border:1px solid $border;border-radius:10px}
QFrame#card QLabel{background:transparent}
QToolButton#back{background:transparent;color:$dim;border:none;border-radius:8px;padding:5px 10px 5px 4px;font:600 9pt 'Segoe UI'}
QToolButton#back:hover{background:$hover;color:$text}
QLabel#title{font:700 12pt 'Segoe UI';color:$text} QLabel#sub{color:$dim;font:9pt 'Segoe UI'} QLabel#note{color:$dim;font:9pt 'Segoe UI'}
QPushButton#primary{background:$accent;color:$on_accent} QPushButton#primary:hover{background:$accent2}
QPushButton#primary:disabled{background:$button;color:$dim}
"""


# ============================================================================
# Waveform trimmer (Ringtone…): pick the part on the sound wave and listen before saving
# ============================================================================


def _fmt_secs(s):
    s = max(0.0, s)
    return f"{int(s // 60)}:{s % 60:04.1f}"










# ============================================================================
# PDF: page grid (Arrange pages…) and signing (Sign…)
# ============================================================================
def _render_page(doc, i, width, extra_rot=0):
    """QImage of page i, `width` px wide (visible orientation plus extra_rot degrees)."""
    import pymupdf
    page = doc[i]
    z = width / max(1.0, page.rect.width)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z).prerotate(extra_rot), alpha=False)
    return QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()












def _pil_to_qimage(img) -> QImage:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    return QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888).copy()








def ask_params(op, paths):
    from parameter_dialog import request_parameters
    return request_parameters(op,paths,icon=app_icon(),css=i18n.css(DIALOG_CSS),on_error=message,
        factories={"@trim":lambda selection:TrimWidget(selection[0],engine.RINGTONE_MAX),
                   "@pages":PageBoard,"@sign":SignPlacer,"@watermark":WatermarkEditor,
                   "@corners":lambda selection:CornerPicker(selection[0]),
                   "social":lambda selection:CropPreview(selection[0])})


def message(title, html):
    box = QMessageBox()
    box.setWindowTitle(title)
    box.setWindowIcon(app_icon())
    box.setStyleSheet(i18n.css(DIALOG_CSS))
    box.setIconPixmap(app_icon().pixmap(48, 48))
    box.setTextFormat(Qt.RichText)
    box.setText(html)
    box.setStandardButtons(QMessageBox.Ok)
    box.button(QMessageBox.Ok).setText(tr("OK"))
    box.exec()


# ============================================================================
# Settings
# ============================================================================
KEY_NAMES = ["Shift", "Ctrl", "Alt", "CapsLock", "None"]
_KEY_ORDER = ["Ctrl", "Shift", "Alt", "Win"]
_CLICK_ORDER = ["LeftClick", "RightClick", "MiddleMouse", "Mouse4", "Mouse5"]














# ============================================================================
# Make it yours: wheel layout, presets, chains, your own slices, where results go, export/import
# ============================================================================
WHEEL_TYPES = [("image", "Image"), ("video", "Video"), ("audio", "Audio"), ("pdf", "PDF"), ("document", "Document"),
               ("spreadsheet", "Spreadsheet"), ("slides", "Slides"), ("archive", "Archive"), ("ebook", "E-book"),
               ("comic", "Comic book"), ("font", "Font"), ("subtitle", "Subtitles"), ("folder", "Folder"),
               ("other", "Other")]
WHEEL_MODES = [("convert", "Convert"), ("tool", "Tools"), ("action", "Actions")]
OUTPUT_MODES = ["next", "folder", "replace", "clipboard"]




















# How the wheels come: the slices most people use, the rest hidden (Settings → Wheel slices shows them all)
DEFAULT_WHEEL_LAYOUT = {
    "convert/image": {"order": ["to_png", "to_webp", "to_heic", "to_avif", "to_tiff", "to_bmp", "to_gif", "to_ico", "to_tga", "to_jp2", "to_icns", "to_pdf", "to_jpg", "to_jpeg"],
                     "hidden": ["to_heic", "to_avif", "to_tiff", "to_bmp", "to_tga", "to_jp2", "to_icns"]},
    "tool/image": {"order": ["compress", "edit", "scan", "rotate", "flip", "gray", "strip", "resize", "removebg", "ocr", "upscale", "sharpen", "watermark", "blurfaces", "zip", "protect_zip", "splitparts"],
                  "hidden": ["rotate", "flip", "gray", "strip", "resize", "splitparts"]},
    "tool/video": {"order": ["compress", "720p", "trim", "mute", "rotate", "snapshot", "speed", "gif", "social", "ringtone", "transcribe", "zip", "protect_zip", "splitparts"],
                  "hidden": ["compress", "720p", "mute", "speed", "gif", "transcribe", "protect_zip", "splitparts"]},
    "tool/audio": {"order": ["compress", "trim", "normalize", "mono", "fade", "ringtone", "transcribe", "zip", "protect_zip", "splitparts"],
                  "hidden": ["normalize", "mono", "protect_zip", "splitparts"]},
    "tool/pdf": {"order": ["compress", "split", "pages", "rotate", "images", "protect", "arrange", "numbers", "watermark", "sign", "gray", "count", "zip", "protect_zip", "splitparts"],
                "hidden": ["compress", "numbers", "gray", "count", "zip", "protect_zip", "splitparts"]},
    "tool/document": {"order": ["count", "zip", "protect_zip", "splitparts"],
                     "hidden": ["count", "zip", "protect_zip"]},
    "convert/document": {"order": ["to_pdf", "to_odt", "to_rtf", "to_txt", "to_html", "to_docx"],
                        "hidden": ["to_odt"]},
    "convert/spreadsheet": {"order": ["to_csv", "to_tsv", "to_json", "to_html", "to_md", "to_pdf", "to_ods", "to_xlsx"],
                           "hidden": ["to_ods"]},
    "tool/spreadsheet": {"order": ["zip", "protect_zip", "splitparts"],
                        "hidden": []},
    "tool/slides": {"order": ["count", "zip", "protect_zip", "splitparts"],
                   "hidden": []},
    "convert/video": {"order": ["to_mp4", "to_mov", "to_mkv", "to_webm", "to_avi", "to_wmv", "to_hevc", "to_gif", "to_mp3", "to_m4a", "to_mkv_hevc"],
                     "hidden": ["to_webm", "to_avi", "to_gif", "to_m4a"]},
    "convert/audio": {"order": ["to_mp3", "to_m4a", "to_wav", "to_flac", "to_ogg", "to_opus", "to_aiff", "to_wma", "to_ac3"],
                     "hidden": ["to_opus", "to_aiff", "to_ac3"]},
    "convert/pdf": {"order": ["to_docx", "to_docx_flow", "to_png", "to_jpg", "to_txt", "to_md", "to_html", "to_cbz"],
                   "hidden": []},
    "convert/slides": {"order": ["to_pdf", "to_png", "to_jpg", "to_pptx", "to_odp"],
                      "hidden": []},
    "convert/archive": {"order": ["to_zip", "to_7z", "to_rar", "to_tar", "to_tar.gz", "to_tar.bz2", "to_tar.xz"],
                       "hidden": []},
    "convert/ebook": {"order": ["to_pdf", "to_txt", "to_md", "to_html"],
                     "hidden": []},
    "convert/comic": {"order": ["to_pdf", "to_cbz"],
                     "hidden": []},
    "action/*": {"order": ["copy", "path", "move", "copyto", "terminal", "float", "reveal", "openwith", "rename", "hash", "unblock", "phone", "shred", "readqr"],
                "hidden": ["copy", "move", "copyto", "reveal", "openwith", "hash"]},
}








def _watch_ops(cat,path=None):
    return discover_operations(cat,path,custom_provider=custom_ops_for)


def watch_folders() -> list:
    return _jload("watch_folders", [])


















# every option in Settings with the value it has when it was never changed — an export carries all of them,
# so importing on another PC sets each one (not only the ones that were changed on this PC)
SETTINGS_DEFAULTS = {
    "language": "", "theme": "system", "check_updates": "true", "tour_at_start": "true", "crash_reports": "false",
    "trigger_mode": "drag", "peek_hold": "false", "shake": "true", "shake_opens": "convert", "scroll": "true",
    "scroll_opens": "convert", "cursor_busy": "true", "wheel_anim": "bloom", "anim_same": "true", "anim_speed": 100,
    "tick_sound": "true", "tick_volume": 70, "sound_pack": "classic", "finish_sound": "true", "finish_anim": "true",
    "media_osd": "true", "media_osd_when": "unfocused", "output_mode": "next", "output_dir": "", "job_mode": "queue",
    "replace_no_ask": "false", "float_autoplay": "true", "float_on_top": "true", "float_ctrl_open": "true",
    "float_link_stops": "true", "float_icon_only": "true", "float_hide_name": "false", "float_taskbar": "true",
    "float_repeat": "off", "float_volume": 1.0, "link_quality": "1080p", "share_way": "quick", "share_minutes": 60,
    "sign_mode": "this", "wheel_layout": "{}", "custom_slices": "[]", "watch_folders": "[]",
}
EXPORT_SKIP = ("float_resume", "last_update", "geometry", "installer", "first_run_done", "skip_version", "detect_any",
               "hotkey")






class StallWatch:
    """Writes to the log what ConvertANNY was busy with whenever it stops responding for a moment (a playing float
    would stutter then), so the cause can be found and moved off the main thread."""
    LIMIT = 0.3

    def __init__(self, parent):
        self.beat = time.monotonic()
        self.main = threading.get_ident()
        self._t = QTimer(parent, interval=50, timeout=self._tick)
        self._t.start()
        threading.Thread(target=self._watch, daemon=True, name="stall-watch").start()

    def _tick(self):
        self.beat = time.monotonic()

    def _watch(self):
        reported, since = None, 0.0
        while True:
            time.sleep(0.1)
            beat = self.beat
            lag = time.monotonic() - beat
            if lag > self.LIMIT and reported != beat and time.monotonic() - since > 3:
                frame = sys._current_frames().get(self.main)
                where = " < ".join(f"{Path(f.filename).stem}:{f.name}:{f.lineno}"
                                   for f in reversed(traceback.extract_stack(frame)[-7:])) if frame else "?"
                reported, since = beat, time.monotonic()
                while self.beat == beat and time.monotonic() - beat < 30:     # how long it lasts
                    time.sleep(0.05)
                winsys.log(f"stall {time.monotonic() - beat:.2f}s: {where}")




# ============================================================================
# Drag watcher — polls input state (no hooks, nothing injected)
# ============================================================================
class CursorBusy(QWidget):
    """A small spinning circle next to the mouse pointer while ConvertANNY is working (Settings → Everyday)."""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(22, 22)
        self.angle = 0
        self.timer = QTimer(self, interval=30, timeout=self._tick)

    def set_busy(self, busy):
        if busy and not self.isVisible():
            self._tick()
            self.show()
            self.timer.start()
        elif not busy and self.isVisible():
            self.timer.stop()
            self.hide()

    def _tick(self):
        pos = QCursor.pos()
        self.move(pos.x() + 16, pos.y() + 18)
        self.angle = (self.angle + 14) % 360
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(3, 3, 16, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawEllipse(r.adjusted(-2, -2, 2, 2))
        p.setPen(QPen(QColor(255, 255, 255, 90), 2.6))
        p.drawEllipse(r)
        pen = QPen(ACCENT, 2.6)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(r, -self.angle * 16, 110 * 16)
        p.end()


DOC_PREVIEW_CATS = ("pdf", "document", "spreadsheet", "slides", "ebook")
TEXTLIKE_EXT = (".txt", ".md", ".csv", ".tsv", ".json", ".html", ".htm", ".rtf", ".log")


class ButtonPolish(QObject):
    """Buttons act like buttons: clicking one doesn't leave it lit up as the window's default button.
    Only the main button of a dialog's button row (Save, OK) stays highlighted."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Polish and isinstance(obj, QPushButton) and not obj.property("_dw_polished"):
            obj.setProperty("_dw_polished", True)
            if not isinstance(obj.parent(), QDialogButtonBox):
                obj.setAutoDefault(False)
                obj.setDefault(False)
        return False


class PeekSignals(QObject):
    ready = Signal(object, object)      # path, QImage


def _office_to_pdf(src: Path, dest: Path) -> bool:
    """Print a Word, Excel or PowerPoint file (or RTF, ODT…) to `dest` as a PDF, read-only, without touching
    the original's folder: Microsoft Office when it's installed, else LibreOffice."""
    cat = engine.EXT_CATEGORY.get(engine.ext_of(str(src)))
    if winsys.IS_WIN:
        try:
            import pythoncom
            import win32com.client as wc
            pythoncom.CoInitialize()
            try:
                if cat in ("document", "pdf"):
                    app = wc.DispatchEx("Word.Application")
                    app.Visible = False
                    app.DisplayAlerts = 0
                    try:
                        doc = app.Documents.Open(str(src), ConfirmConversions=False, ReadOnly=True,
                                                 AddToRecentFiles=False, Visible=False)
                        doc.ExportAsFixedFormat(str(dest), 17, OpenAfterExport=False, OptimizeFor=1,
                                                Range=3, From=1, To=1)          # first page is enough
                        doc.Close(False)
                    finally:
                        app.Quit()
                elif cat == "spreadsheet":
                    app = wc.DispatchEx("Excel.Application")
                    app.Visible = False
                    app.DisplayAlerts = False
                    try:
                        wb = app.Workbooks.Open(str(src), ReadOnly=True, UpdateLinks=0)
                        wb.ActiveSheet.ExportAsFixedFormat(0, str(dest), From=1, To=1, OpenAfterPublish=False)
                        wb.Close(False)
                    finally:
                        app.Quit()
                elif cat == "slides":
                    app = wc.DispatchEx("PowerPoint.Application")
                    try:
                        pres = app.Presentations.Open(str(src), ReadOnly=True, WithWindow=False)
                        pres.SaveAs(str(dest), 32)
                        pres.Close()
                    finally:
                        app.Quit()
            finally:
                pythoncom.CoUninitialize()
            if dest.exists() and dest.stat().st_size > 0:
                return True
        except Exception as e:
            winsys.log(f"preview: Office could not open {src.name}: {e}")
    exe = engine.soffice()
    if exe:
        import subprocess
        import tempfile
        td = Path(tempfile.mkdtemp(prefix="dw-prev-"))
        try:
            subprocess.run([exe, "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(td), str(src)],
                           timeout=90, stdin=subprocess.DEVNULL, capture_output=True, creationflags=engine.NO_WINDOW)
            made = list(td.glob("*.pdf"))
            if made:
                shutil.move(str(made[0]), str(dest))
                return True
        except Exception as e:
            winsys.log(f"preview: LibreOffice could not open {src.name}: {e}")
        finally:
            shutil.rmtree(td, ignore_errors=True)
    return False


_PREVIEW_LOCK = threading.Lock()


def _pdf_for_preview(p: Path) -> Path | None:
    """A PDF of an Office-type file for previews, made once and kept in the temp folder until the file changes."""
    import hashlib
    import tempfile
    try:
        st = p.stat()
    except OSError:
        return None
    key = hashlib.sha1(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8")).hexdigest()[:16]
    folder = Path(tempfile.gettempdir()) / "ConvertANNY previews"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{key}.pdf"
    with _PREVIEW_LOCK:                      # Float and Quick preview asking at once make it only once
        if out.exists() and out.stat().st_size > 0:
            return out
        part = folder / f"{key}.tmp.pdf"
        part.unlink(missing_ok=True)
        if _office_to_pdf(p.resolve(), part):
            os.replace(part, out)
            return out
        part.unlink(missing_ok=True)
        winsys.log(f"preview: no page for {p.name} (needs Microsoft Office or LibreOffice)")
        return None


def _text_page_image(p: Path, width: int) -> "QImage | None":
    """Text, Markdown, HTML, CSV and JSON files drawn as a white page."""
    from PySide6.QtGui import QTextDocument, QTextOption
    try:
        raw = p.read_bytes()[:400_000]
    except OSError:
        return None
    txt = None
    for enc in ("utf-8-sig", "utf-16", "cp1256", "latin-1"):
        try:
            txt = raw.decode(enc)
            if enc == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            break
        except UnicodeDecodeError:
            continue
    if txt is None:
        return None
    e = p.suffix.lower()
    doc = QTextDocument()
    doc.setDocumentMargin(36)
    f = QFont(i18n.ui_font() if e in (".md", ".markdown", ".html", ".htm") else "Consolas", 11)
    doc.setDefaultFont(f)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    if any("\u0600" <= ch <= "\u06ff" for ch in txt[:2000]):
        opt.setTextDirection(Qt.RightToLeft)
        opt.setAlignment(Qt.AlignRight)
    doc.setDefaultTextOption(opt)
    if e in (".html", ".htm"):
        doc.setHtml(txt)
    elif e in (".md", ".markdown"):
        doc.setMarkdown(txt)
    elif e in (".csv", ".tsv"):
        import csv
        import html as _h
        rows = list(csv.reader(txt.splitlines()[:60], delimiter="\t" if e == ".tsv" else ","))
        doc.setHtml("<table border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse'>" + "".join(
            "<tr>" + "".join(f"<td>{_h.escape(c)}</td>" for c in r[:12]) + "</tr>" for r in rows) + "</table>")
    elif opt.textDirection() == Qt.RightToLeft:
        import html as _h
        doc.setDefaultFont(QFont(i18n.ui_font(), 12))
        doc.setHtml("<div dir='rtl' align='right' style='white-space:pre-wrap'>" + _h.escape(txt[:20000]) + "</div>")
    else:
        doc.setPlainText(txt[:20000])
    page_w = 620
    doc.setTextWidth(page_w)
    page_h = int(page_w * 1.414)
    scale = width / page_w
    img = QImage(width, int(page_h * scale), QImage.Format_RGB888)
    img.fill(QColor(255, 255, 255))
    pnt = QPainter(img)
    pnt.setRenderHint(QPainter.Antialiasing)
    pnt.setRenderHint(QPainter.TextAntialiasing)
    pnt.scale(scale, scale)
    pnt.setClipRect(QRectF(0, 0, page_w, page_h))
    from PySide6.QtGui import QAbstractTextDocumentLayout
    ctx = QAbstractTextDocumentLayout.PaintContext()
    ctx.palette.setColor(ctx.palette.ColorRole.Text, QColor(20, 20, 20))
    doc.documentLayout().draw(pnt, ctx)
    pnt.end()
    return img


def document_page_image(path, width=1200, page=0) -> "QImage | None":
    """First page of any document as a picture: PDFs, e-books and comics directly, Word/Excel/PowerPoint/RTF/ODT
    through a PDF, and text, Markdown, HTML and CSV files drawn as a page."""
    p = Path(path)
    cat = engine.EXT_CATEGORY.get(engine.ext_of(str(p)))
    e = p.suffix.lower()
    if e in TEXTLIKE_EXT or e in (".markdown", ".json"):
        try:
            return _text_page_image(p, width)
        except Exception as ex:
            winsys.log(f"preview: {p.name}: {ex}")
            return None
    src = p
    if cat in ("document", "spreadsheet", "slides"):
        src = _pdf_for_preview(p)
        if src is None:
            return None
    try:
        import pymupdf
        with pymupdf.open(str(src)) as doc:
            if doc.page_count == 0:
                return None
            pg = doc[min(page, doc.page_count - 1)]
            zoom = width / max(1.0, pg.rect.width)
            pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            return QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
    except Exception as ex:
        winsys.log(f"preview: {p.name}: {ex}")
        return None


def _peek_image(path) -> "QImage | None":
    """A picture of the file for Quick preview: the image itself, a PDF's first page, a video frame."""
    p = Path(path)
    cat = engine.EXT_CATEGORY.get(engine.ext_of(str(p)))
    try:
        if cat == "image":
            img = QImage(str(p))
            if img.isNull():
                from PIL import Image
                try:
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                except Exception:
                    pass
                with Image.open(p) as im:
                    im.thumbnail((900, 900))
                    im = im.convert("RGBA")
                    img = QImage(im.tobytes("raw", "RGBA"), im.width, im.height, QImage.Format_RGBA8888).copy()
            return None if img.isNull() else img.scaled(900, 900, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if cat in DOC_PREVIEW_CATS or p.suffix.lower() in (".cbz", ".xps", ".json"):
            return document_page_image(p, 900)
        if cat == "video":
            import subprocess
            import tempfile
            out = Path(tempfile.gettempdir()) / f"dw-peek-{os.getpid()}.jpg"
            subprocess.run([engine.ffmpeg(), "-y", "-v", "error", "-ss", "2", "-i", str(p), "-frames:v", "1",
                            "-vf", "scale='min(900,iw)':-2", str(out)], timeout=8, stdin=subprocess.DEVNULL,
                           capture_output=True, creationflags=engine.NO_WINDOW)
            img = QImage(str(out))
            try:
                out.unlink()
            except OSError:
                pass
            return None if img.isNull() else img
    except Exception as e:
        winsys.log(f"peek: {p.name}: {e}")
    return None


class PeekWindow(QWidget):
    """Quick preview: tap Space while dragging to see what you're holding."""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.path = None
        self.img = None
        self.text = ""
        self.sig = PeekSignals()
        self.sig.ready.connect(self._got, Qt.QueuedConnection)
        self.follow = QTimer(self, interval=15, timeout=self._place)    # rides along with the pointer
        self._last_pos = None

    def peek(self, paths):
        self.path = paths[0]
        p = Path(self.path)
        self.img = None
        self.text = ""
        cat = engine.EXT_CATEGORY.get(engine.ext_of(str(p)))
        if p.is_file() and (cat in ("subtitle",) or p.suffix.lower() in (".log", ".py", ".ini", ".xml", ".srt")):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    self.text = "".join(f.readline() for _ in range(24))[:2400]
            except OSError:
                pass
        elif p.is_file():
            threading.Thread(target=lambda path=self.path: self.sig.ready.emit(path, _peek_image(path)),
                             daemon=True).start()
        self.extra = tr("{n} files", n=len(paths)) if len(paths) > 1 else ""
        self._layout()
        self.show()
        self.raise_()

    def _got(self, path, img):
        if path == self.path and self.isVisible() and img is not None:
            self.img = img
            self._layout()
            self.update()

    def _layout(self):
        w, h = 340, 120
        if self.img is not None:
            sc = min(420 / self.img.width(), 380 / self.img.height(), 1.0)
            w, h = max(240, int(self.img.width() * sc) + 24), int(self.img.height() * sc) + 74
        elif self.text:
            w, h = 420, 300
        else:
            w, h = 300, 150
        self.resize(w, h)
        self._last_pos = None
        self._place()

    def _place(self):
        pos = QCursor.pos()
        if pos == self._last_pos:
            return
        self._last_pos = pos
        w, h = self.width(), self.height()
        scr = (QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()).availableGeometry()
        x = pos.x() + 28 if pos.x() + 28 + w < scr.right() else pos.x() - 28 - w
        y = max(scr.top() + 8, min(pos.y() - h // 2, scr.bottom() - h - 8))
        self.move(x, y)

    def showEvent(self, e):
        self.follow.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.follow.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setPen(QPen(C("line"), 1))
        p.setBrush(C("panel"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 14, 14)
        path = Path(self.path or "")
        body = QRectF(12, 12, self.width() - 24, self.height() - 74)
        if self.img is not None:
            pm = QPixmap.fromImage(self.img)
            if pm.width() > body.width() or pm.height() > body.height():      # shrink big pictures, never blow up small ones
                pm = pm.scaled(body.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(int(body.center().x() - pm.width() / 2), int(body.center().y() - pm.height() / 2), pm)
        elif self.text:
            p.setPen(C("text"))
            p.setFont(QFont("Consolas", 8))
            p.drawText(body, Qt.AlignLeft | Qt.AlignTop | Qt.TextWrapAnywhere, self.text)
        else:
            from PySide6.QtCore import QFileInfo
            from PySide6.QtWidgets import QFileIconProvider
            ic = QFileIconProvider().icon(QFileInfo(str(path))).pixmap(56, 56)
            p.drawPixmap(int(body.center().x() - 28), int(body.center().y() - 28), ic)
        p.setPen(C("text"))
        p.setFont(QFont(i18n.ui_font(), 10, QFont.DemiBold))
        fm = QFontMetrics(p.font())
        p.drawText(QRectF(14, self.height() - 58, self.width() - 28, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(path.name, Qt.ElideMiddle, self.width() - 28))
        p.setPen(C("dim"))
        p.setFont(QFont(i18n.ui_font(), 9))
        info = " · ".join(x for x in (_human(path), self.extra, tr("{key} to close", key=key_label(peek_key()))) if x)
        p.drawText(QRectF(14, self.height() - 36, self.width() - 28, 20), Qt.AlignLeft | Qt.AlignVCenter, info)
        p.end()






class DragWatcher(QObject):
    tapped = Signal(str)     # mode
    released = Signal()
    hotkey = Signal()
    idle_tap = Signal(str)   # a wheel key tapped on its own, not while dragging (Trigger on: hover / selection)
    moved = Signal()         # every tick while a drag is in progress
    scrolled = Signal(int)   # wheel delta while dragging (from the hook thread, delivered queued)
    cancelled = Signal()     # Esc pressed during a drag
    ctrl_open = Signal(int)  # Ctrl + double-click on a file in Explorer (window handle), from the hook thread
    peek = Signal()          # Space tapped while dragging (Quick preview)
    volume_key = Signal(int)  # a volume key or knob step (from the hook thread)
    shaken = Signal()        # the mouse was shaken while dragging
    peek_up = Signal()       # File preview key let go (File preview set to "hold to show")
    click_drag = Signal(str)  # a wheel key + right click while dragging (from the hook thread)

    def __init__(self):
        super().__init__()
        self.timer = QTimer(self, interval=48, timeout=self.tick)
        self.down_at = None
        self.dragging = False
        self.prev = {}
        self.spoiled = set()     # combinations interrupted by a longer one (see tick)
        self.hotkey_latch = False
        self.source_hwnd = 0     # top-level window the drag started in
        self.esc_prev = False
        self.space_prev = False
        self.trail = []          # (time, x) while dragging, to notice a shake
        self.shook = False
        from convertanny_core.gestures import ShakeDetector
        self.shake_detector=ShakeDetector()
        self.refresh_settings()
        self.hook = winsys.WheelHook(self._on_wheel, self._swallow_wheel,
                                     on_ctrl_double=lambda hwnd: self.ctrl_open.emit(int(hwnd)),
                                     ctrl_double_enabled=lambda: getattr(self, "ctrl_float", False))
        self.hook.on_volume_key = lambda vk: self.volume_key.emit(vk)
        self.hook.on_click = self._on_click
        self._click_specs = []   # (mode, other keys, button) for wheel keys that end in a mouse click
        self._click_pending = None   # (mode, keys) — fires when those keys are let go (Trigger on hover / selection)
        self._hold_keys = None       # keys holding File preview open (hold to show)

    def refresh_settings(self):
        s = settings()
        self.trigger = trigger_mode()
        self.scroll_enabled = s.value("scroll", "true") == "true"
        self.any_drag = False
        self.ctrl_float = s.value("float_ctrl_open", "true") == "true"
        self.shake_enabled = s.value("shake", "true") == "true"
        self.peek_vks = winsys.combo_vks(peek_key())
        self.peek_enabled = bool(self.peek_vks)
        self.peek_hold = peek_hold()

    # ---- wheel key + mouse click (Ctrl + right click…): seen by the mouse hook, so the click never reaches Explorer
    CLICKS = (0x01, 0x02)

    def _hook_clicks(self):
        """Buttons the hook handles: during a file drag the left button is already down, so only right clicks."""
        return (0x02,) if getattr(self, "trigger", "drag") == "drag" else self.CLICKS

    def _on_click(self, btn, down):
        """On the hook thread: True = this click belongs to a wheel key, keep it from Windows."""
        if not down or btn not in self._hook_clicks():
            return False
        for mode, others, b in list(self._click_specs):
            if b != btn or not others or not all(winsys.key_down(v) for v in others):
                continue
            if getattr(self, "trigger", "drag") == "drag":
                if not self.dragging:
                    continue
                self.click_drag.emit(mode)
                if mode == "peek" and self.peek_hold:
                    self._hold_keys = others
                return True
            if self.dragging:
                continue
            if mode == "peek" and self.peek_hold:
                self.idle_tap.emit("peek")             # shown now, closed when the keys are let go
                self._hold_keys = others
            else:
                self._click_pending = (mode, others)   # after the keys are let go (so they don't change the selection)
            return True
        return False

    def _update_click_specs(self, keys):
        specs = []
        for mode, spec in list(keys.items()) + [("peek", peek_key())]:
            vks = winsys.combo_vks(spec)
            btns = [v for v in vks if v in self._hook_clicks()]
            if btns:
                specs.append((mode, [v for v in vks if v not in self.CLICKS], btns[-1]))
        self._click_specs = specs

    # called on the hook thread — keep it tiny
    def _drag_qualifies(self):
        return self.dragging and self.scroll_enabled and (self.any_drag or winsys.file_drag_active())

    def _on_wheel(self, delta):
        if self._drag_qualifies():
            self.scrolled.emit(delta)

    def _swallow_wheel(self):
        return self._drag_qualifies()

    def start(self):
        if winsys.IS_WIN:
            self.timer.start()
            self.hook.start()

    def tick(self):
        if time.monotonic() < winsys.SYNTH_UNTIL:
            return                                     # ConvertANNY is clicking for you: held keys briefly read as up
        keys = mode_keys()
        combos = {spec: set(winsys.combo_vks(spec)) for spec in set(keys.values())}
        hooked = set(self._hook_clicks())
        combos = {k: v for k, v in combos.items() if v and not v & hooked}    # key + click: the mouse hook handles those
        self._update_click_specs(keys)
        if self._click_pending and not any(winsys.key_down(v) for v in self._click_pending[1]):
            mode, self._click_pending = self._click_pending[0], None
            self.idle_tap.emit(mode)
        if self._hold_keys is not None and not any(winsys.key_down(v) for v in self._hold_keys):
            self._hold_keys = None
            self.peek_up.emit()
        down = {vk: winsys.key_down(vk) for vk in set().union(*combos.values())} if combos else {}
        held = {spec: all(down[v] for v in vks) for spec, vks in combos.items()}
        # a key that's part of a longer combination (Ctrl, when another wheel is Ctrl+Q) counts when it's let go
        # without the rest of that combination having been pressed
        subset = {spec for spec, vks in combos.items() if any(vks < o for o in combos.values())}
        lmb = winsys.mouse_down()

        # global hotkey: Ctrl+Alt+Space
        combo = winsys.key_down(0x11) and winsys.key_down(0x12) and winsys.key_down(winsys.VK_SPACE)
        if combo and not self.hotkey_latch:
            self.hotkey_latch = True
            if settings().value("hotkey", "true") == "true":
                self.hotkey.emit()
        elif not combo:
            self.hotkey_latch = False

        if lmb:
            pos = winsys.cursor_pos()
            if self.down_at is None:
                self.down_at = pos
                self.dragging = False
                self.source_hwnd = winsys.root_window_at(*pos)
            elif not self.dragging:
                dx, dy = pos[0] - self.down_at[0], pos[1] - self.down_at[1]
                if abs(dx) + abs(dy) > winsys.drag_threshold() * 2:
                    self.dragging = True
            if self.dragging:
                self.moved.emit()
                esc = winsys.key_down(winsys.VK_ESCAPE)
                if esc and not self.esc_prev:
                    self.cancelled.emit()
                self.esc_prev = esc
                pv = getattr(self, "peek_vks", [winsys.VK_SPACE])
                if set(pv) & hooked:
                    pv = []                            # File preview is a key + click: the mouse hook handles it
                space = bool(pv) and all(winsys.key_down(v) for v in pv) and (
                    len(pv) > 1 or pv[0] in (0x10, 0x11, 0x12) or not (winsys.key_down(0x11) or winsys.key_down(0x12)))
                if (space and not self.space_prev and self.peek_enabled and getattr(self, "trigger", "drag") == "drag"
                        and winsys.file_drag_active()):
                    self.peek.emit()
                elif not space and self.space_prev and self.peek_hold and getattr(self, "trigger", "drag") == "drag":
                    self.peek_up.emit()                # hold to show: let go closes it
                self.space_prev = space
                if self.shake_enabled and not self.shook and winsys.file_drag_active() and self._shake(pos):
                    self.shook = True
                    self.shaken.emit()
                for spec in combos:                         # was a longer combination pressed meanwhile?
                    if any(held.get(o) for o in combos if combos[spec] < combos[o]):
                        self.spoiled.add(spec)
                for m, name in keys.items():
                    if name not in combos:
                        continue
                    if name in subset:
                        fire = (not held.get(name) and self.prev.get(name) and name not in self.spoiled)
                    else:
                        fire = held.get(name) and not self.prev.get(name)
                    if not held.get(name) and not self.prev.get(name):
                        self.spoiled.discard(name)
                    if fire and getattr(self, "trigger", "drag") == "drag" and (any_drag or winsys.file_drag_active()):
                        self.tapped.emit(m)
                    if fire or (not held.get(name) and self.prev.get(name)):
                        self.spoiled.discard(name)
        else:
            if self.down_at is not None and self.dragging:
                self.released.emit()
            self.down_at = None
            self.dragging = False
            self.trail = []
            self.shook = False
            self.shake_detector.reset()
            self.space_prev = False
        # Trigger on hover / selection: a clean tap of a wheel key (nothing else pressed meanwhile, no click)
        if getattr(self, "trigger", "drag") != "drag":
            clean = getattr(self, "clean", {})
            pv = getattr(self, "peek_vks", [])
            if pv and not set(pv) & hooked:            # File preview follows the same choice
                combos["__peek__"] = set(pv)
                held["__peek__"] = all(winsys.key_down(v) for v in pv)
            else:
                pv = []
            for m, name in list(keys.items()) + ([("peek", "__peek__")] if pv else []):
                vks = combos.get(name)
                if not vks:
                    continue
                hold = m == "peek" and self.peek_hold
                if held.get(name) and not self.prev.get(name):
                    clean[name] = not lmb
                    if hold and clean[name] and not self.dragging and not winsys.other_keys_down(vks):
                        self.idle_tap.emit(m)          # hold to show: open on press…
                        clean[name] = "open"
                elif held.get(name) and clean.get(name) is True and (lmb or winsys.other_keys_down(vks)):
                    clean[name] = False
                elif not held.get(name) and self.prev.get(name):
                    if clean.get(name) == "open":
                        self.peek_up.emit()            # …and close on release
                    elif clean.get(name) and not lmb and not self.dragging and not hold:
                        self.idle_tap.emit(m)
                    clean[name] = False
            self.clean = clean
        self.prev = held
        self.timer.setInterval(16 if lmb else 48)

    def _shake(self, pos) -> bool:
        """Three or more quick left-right turns of at least 40 px within 0.8 s."""
        import time
        now=time.monotonic();self.trail.append((now,pos[0]))
        self.trail=[sample for sample in self.trail if now-sample[0]<=.8]
        return self.shake_detector.add(now,pos[0])


# ============================================================================
# App
# ============================================================================
def asset(name) -> str:
    return str(Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / name)


_ICON = None


def app_icon() -> QIcon:
    global _ICON
    if _ICON is None:
        _ICON = QIcon(asset("convertanny.ico")) if os.path.exists(asset("convertanny.ico")) else QIcon()
    return _ICON


class ConvertANNYApp(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(max(2, (os.cpu_count() or 4) // 2))
        self.actions = Actions(self)
        global _APP
        _APP = self
        self.floats = []
        self.out_override = {}           # temp file -> folder its results go to (clipboard "save here")
        self._media_down = {}
        self._media_timer = QTimer(self, interval=60, timeout=self._media_tick)
        self.wheel = Wheel(self)
        self.toast = ToastManager(reveal=winsys.reveal,play_sound=play_finish_sound,settings=settings)
        self.running = set()
        self.waiting = []                # jobs in line (Settings → one at a time)
        engine.OUTPUT_DIR = (settings().value("output_dir", "") or None) \
            if settings().value("output_mode", "folder") == "folder" else None

        self.watcher = DragWatcher()
        self.watcher.tapped.connect(self.on_tap)
        self.watcher.released.connect(self.on_release)
        self.watcher.hotkey.connect(self.on_hotkey)
        self.watcher.idle_tap.connect(self.on_idle_tap)
        self.watcher.moved.connect(self.on_drag_move)
        self.watcher.scrolled.connect(self.on_scroll)
        self.watcher.ctrl_open.connect(self.on_ctrl_open)
        self.watcher.cancelled.connect(self.on_drag_cancel)
        self.watcher.peek.connect(self.on_peek)
        self.watcher.volume_key.connect(self.on_volume_key, Qt.QueuedConnection)
        self.watcher.shaken.connect(self.on_shake)
        self.watcher.released.connect(self._close_peek)
        self.watcher.peek_up.connect(self._peek_let_go)
        self.watcher.click_drag.connect(self.on_click_drag)
        self.watcher.start()
        self._peek = None
        self._peek_held = False
        self.watch = FolderWatch(self,rules=watch_folders,operations=_watch_ops,log=winsys.log)
        try:
            _tick_effect()                       # load the click sounds now
            _tick_effect("select")
        except Exception as e:
            winsys.log(f"tick sound: {e}")
        self.cursor_busy = CursorBusy()
        self._busy_timer = QTimer(self, interval=250, timeout=self._update_cursor_busy)
        self._busy_timer.start()

        self.pending: list[str] = []
        self.pending_timer = QTimer(self, singleShot=True, interval=600, timeout=self._flush_pending)

        self.tray = QSystemTrayIcon(app_icon())
        self.tray.activated.connect(lambda r: self.show_settings() if r == QSystemTrayIcon.Trigger else None)
        self._build_tray_menu()
        self.tray.show()
        self._update_jobs = set()
        QTimer.singleShot(8000, self._auto_update_check)
        QTimer.singleShot(150, self.restore_pinned_floats)
        self.predownload()
        self._prebuild_settings(6000)
        QTimer.singleShot(3000, refresh_clouds)
        self._stall_watch = StallWatch(self)
        QApplication.instance().aboutToQuit.connect(self._end_shares)
        self._cloud_timer = QTimer(self, interval=10 * 60 * 1000, timeout=clean_cloud_shares)
        self._cloud_timer.start()
        QTimer.singleShot(20000, clean_cloud_shares)

    def restore_pinned_floats(self):
        """Reopen the floats that were open before an update, and those set to 'Open when Windows starts'."""
        try:
            resume = json.loads(settings().value("float_resume", "[]") or "[]")
        except (TypeError, ValueError):
            resume = []
        settings().remove("float_resume")
        ids = {r.get("id") for r in resume if r.get("id")}
        for pin in resume + [x for x in _float_pins() if x.get("id") not in ids]:
            self.open_float_state(pin)

    def open_float_state(self, pin):
        """Open a float from FloatWindow.state(): the same file or link, place, size and point in the video."""
        src = pin.get("src")
        if not src:
            return None
        if pin.get("link"):
            if not engine.model_ready("yt-dlp"):
                return None
            w = FloatWindow("", {"page": src, "title": pin.get("title") or src, "pending": True}, pin=pin)
            self.floats.append(w)
            self._sync_media_polling()
            w.closed.connect(lambda w=w: self._forget_float(w))
            w.show()
            self._resolve_and_play(src, w, pin=pin, quiet=True)
            return w
        if not os.path.exists(src):
            winsys.log(f"pinned float missing: {src}")
            return None
        w = FloatWindow(src, play=pin.get("playing", True), pin=pin)
        self.floats.append(w)
        self._sync_media_polling()
        w.closed.connect(lambda w=w: self._forget_float(w))
        w.show()
        return w

    def _build_tray_menu(self):
        ck = mode_keys()["convert"]
        self.tray.setToolTip(tr("{app} — drag a file and shake the mouse", app=APP) if ck == "None"
                             else tr("{app} — drag a file, tap {key}", app=APP, key=key_label(ck)))
        menu = QMenu()
        self._first_action = menu.addAction(tr("Convert files…"), self.pick_files)
        menu.addAction(tr("Save image from clipboard"), self.save_clipboard_image)
        menu.addAction(tr("Paste link to Float"), self.play_link)
        menu.addAction(tr("Read QR code on screen"), lambda: QTimer.singleShot(300, self.read_qr_on_screen))
        recent = menu.addMenu(tr("Recent results"))
        recent.aboutToShow.connect(lambda m=recent: self._fill_recent(m))
        self._qr_menu = menu.addMenu(tr("Send to phone — show QR code"))
        menu.addSeparator()
        menu.addAction(tr("How it works"), self.show_help)
        menu.addAction(tr("Settings…"), self.show_settings)
        menu.addAction(tr("Check for updates…"), lambda: self.check_updates(manual=True))
        menu.addSeparator()
        menu.addAction(tr("Quit {app}", app=APP), self.qapp.quit)
        self._cancel_actions = []
        menu.aboutToShow.connect(self._refresh_tray_menu)
        old = self.tray.contextMenu()
        self.tray.setContextMenu(menu)
        self._menu = menu
        if old:
            old.deleteLater()

    def _active_jobs(self):
        """Conversions/tools still running and not already being cancelled."""
        return [w for w in list(self.running) if not w.cancel_requested]

    def _fill_qr_menu(self):
        sub = self._qr_menu
        sub.clear()
        links = share_links()
        short = lambda n: n if len(n) <= 40 else n[:37] + "…"
        live = []
        for (mode, _k), w in list(getattr(self, "_live_phone", {}).items()):
            try:
                if not w.ended:
                    live.append(w)
            except RuntimeError:
                pass
        clouds = [x for x in cloud_shares() if x.get("url") and Path(x.get("path", "")).exists()
                  and (not x.get("expires") or x["expires"] > time.time())]
        sub.menuAction().setVisible(bool(links or live or clouds))   # only while something is shared
        for w in live:
            name = w.paths[0].name if len(w.paths) == 1 else tr("{n} files", n=len(w.paths))
            way = tr("Link from this PC") if w.mode == "tunnel" else tr("Same Wi-Fi")
            sub.addAction(f"{short(name)}   ·   {way}", lambda _=False, w=w: (w.show(), w.raise_(), w.activateWindow()))
        for it in links:
            sub.addAction(f"{short(it['name'])}   ·   {_time_left(it['expires'])}", lambda _=False, it=it: self._show_qr(it))
        for x in clouds:
            it = {"url": x["url"], "name": x.get("name") or Path(x["path"]).name, "expires": x.get("expires", 0),
                  "path": x["path"]}
            left = _time_left(it["expires"]) if it["expires"] else tr("Cloud link")
            sub.addAction(f"{short(it['name'])}   ·   {left}", lambda _=False, it=it: self._show_qr(it, tr("Cloud link")))

    def _show_qr(self, it, title=None):
        w = ShareQR(it, title)
        self._phone_windows = getattr(self, "_phone_windows", [])
        self._phone_windows.append(w)
        w.show()
        w.raise_()
        w.activateWindow()

    def _refresh_tray_menu(self):
        """Cancel entries go first in the tray menu, only while work is in progress."""
        self._fill_qr_menu()
        menu = self._menu
        for act in self._cancel_actions:
            menu.removeAction(act)
            act.deleteLater()
        self._cancel_actions = []
        jobs = self._active_jobs() + [w for w in self.waiting if not w.cancel_requested]
        if not jobs:
            return
        before = self._first_action
        for w in jobs:
            name = Path(w.paths[0]).name if len(w.paths) == 1 else tr("{n} files", n=len(w.paths))
            if len(name) > 40:
                name = name[:37] + "…"
            what = (tr("Converting to {fmt}…", fmt=tr(w.op.label)) if w.op.group == "convert"
                    else tr(w.op.label)).rstrip("…")
            act = QAction(tr("Cancel: {what} — {name}", what=what, name=name), menu)
            act.triggered.connect(lambda _=False, w=w: self._cancel_job(w))
            menu.insertAction(before, act)
            self._cancel_actions.append(act)
        if len(jobs) > 1:
            act = QAction(tr("Cancel all ({n})", n=len(jobs)), menu)
            act.triggered.connect(lambda: [self._cancel_job(w) for w in list(self.waiting) + self._active_jobs()])
            menu.insertAction(before, act)
            self._cancel_actions.append(act)
        sep = menu.insertSeparator(before)
        self._cancel_actions.append(sep)

    def apply_theme(self):
        theme.set_mode(settings().value("theme", "system"))
        sync_accent()
        self.toast.restyle()
        for c in self.toast.cards:
            c.update()
        for f in self.floats:
            f.update()
        self.wheel.update()

    def apply_language(self):
        i18n.set_language(settings().value("language", ""))
        self.qapp.setLayoutDirection(Qt.RightToLeft if i18n.is_rtl() else Qt.LeftToRight)
        from typography import ui_font
        self.qapp.setFont(ui_font())
        self.toast.restyle()
        self._build_tray_menu()
        self.wheel.update()

    # ---- ops for a mode
    def ops_for(self, mode, paths):
        if mode == "convert":
            ops = engine.conversions(paths)
        elif mode == "tool":
            ops = engine.tools(paths)
        else:
            ops = self.actions.ops(paths)
        try:
            ops = ops + custom_ops_for(mode, paths)                     # your presets, chains and commands
            ops = apply_wheel_layout(mode, engine.category_of(paths), ops)
        except Exception as e:
            winsys.log(f"wheel layout: {e}")
        if not ops:
            return [engine.Op("none", "No conversions" if mode == "convert" else "No tools", lambda *a: None,
                              hint="try Tools or Actions" if mode == "convert" else "try Convert or Actions")]
        return ops

    # ---- triggers
    def on_tap(self, mode):
        now = time.monotonic()
        if now - getattr(self, "_last_tap", 0.0) < 0.22:
            return                                    # one press is one toggle, never open-then-close
        self._last_tap = now
        if self.wheel.is_open():
            if mode == self.wheel.mode:
                self.wheel.dismiss()                 # the same key again closes the wheel
                return
            if mode != self.wheel.mode:
                play_tick()
                self.wheel.set_mode(mode)
            if not self.wheel.paths:
                self._fill_from_explorer()
            return
        self.wheel.popup(mode, click_mode=False)
        self._fill_from_explorer()
        QTimer.singleShot(0, self.wheel.begin_anim)

    def on_click_drag(self, mode):
        """A wheel key + right click while dragging a file."""
        if not winsys.file_drag_active():
            return
        if mode == "peek":
            self.on_peek()
        else:
            self.on_tap(mode)

    def on_peek(self):
        """Space while dragging: show (or hide) a quick preview of the file being dragged."""
        if self._peek is not None and self._peek.isVisible():
            if not peek_hold():
                self._peek.hide()                    # press to open, press again to close
            return
        paths = self.wheel.paths if self.wheel.is_open() and self.wheel.paths else []
        if not paths:
            hwnd = self.watcher.source_hwnd
            paths = [p for p in winsys.explorer_selection(hwnd) if p and os.path.exists(p)]
        if not paths:
            return
        if self._peek is None:
            self._peek = PeekWindow()
        self._peek.peek(paths)

    def _close_peek(self):
        if self._peek is not None:
            self._peek.hide()

    def _peek_let_go(self):
        """Hold to show: the key was let go — close it, or don't open it if it isn't up yet."""
        self._peek_held = False
        self._close_peek()

    def _fill_from_explorer(self):
        """Ask Explorer which files are being dragged, so the wheel works even if
        Windows never delivers the drag to it (security software, elevation, Qt quirks)."""
        hwnd = self.watcher.source_hwnd
        paths = [p for p in winsys.explorer_selection(hwnd) if p and os.path.exists(p)]
        winsys.log(f"tap: source={winsys.window_class(hwnd)!r} selection={len(paths)}")
        if paths and not self.wheel.paths:
            self.wheel.set_paths(paths)

    def on_shake(self):
        target = settings().value("shake_opens", "convert")
        if target == "peek":
            self.on_peek()
        elif not self.wheel.is_open():
            self.on_tap(target if target in MODES else "convert")

    def on_scroll(self, delta):
        w = self.wheel
        target = settings().value("scroll_opens", "convert")
        if not w.is_open() and target == "peek":
            if self._peek is None or not self._peek.isVisible():
                self.on_peek()
            return
        if not w.is_open():
            w.popup(target if target in MODES else "convert", click_mode=False)
            self._fill_from_explorer()
            QTimer.singleShot(0, w.begin_anim)
            return
        if not w.click_mode:
            w.scroll_step(1 if delta < 0 else -1)

    def on_drag_cancel(self):
        if self.wheel.is_open() and not self.wheel.click_mode:
            winsys.log("drag cancelled with Esc")
            self.wheel.dismiss()

    def on_drag_move(self):
        w = self.wheel
        if w.is_open() and not w.click_mode:
            w._track(QPointF(w.mapFromGlobal(QCursor.pos())))

    def on_release(self):
        w = self.wheel
        if w.is_open() and not w.click_mode:
            pos = QPointF(w.mapFromGlobal(QCursor.pos()))
            # give a real OLE drop time to arrive; if it doesn't, apply the slice under the cursor
            QTimer.singleShot(350, lambda: self._finish_drag(pos))

    def _finish_drag(self, pos):
        w = self.wheel
        if not w.is_open() or w.click_mode or w.dropped:
            return
        kind, val = w.hit(pos)
        if w.scroll_active and 0 <= w.hover < len(w.ops):
            kind, val = "item", w.hover
        paths = list(w.paths)
        if kind == "item" and paths and 0 <= val < len(w.ops):
            op = w.ops[val]
            winsys.log(f"applied via release fallback: {op.id} on {len(paths)} file(s)")
            w.dismiss()
            QTimer.singleShot(0, lambda: self.execute(op, paths))
        else:
            if kind == "item" and not paths:
                self.toast.show_msg(tr("Couldn't read the dragged file"),
                                    tr("Try again, or select it and press Ctrl+Alt+Space"), "err", 5000)
            w.dismiss()

    EXPLORER_CLASSES = ("CabinetWClass", "ExploreWClass", "Progman", "WorkerW")

    def on_idle_tap(self, mode):
        """Trigger on hover / selection: the wheel for the file under the mouse, or the files selected."""
        if mode == "peek":
            if self._peek is not None and self._peek.isVisible():
                if not peek_hold():
                    self._peek.hide()
                return
            self._peek_held = True
            self._idle_paths(lambda paths: self._show_peek(paths) if self._peek_held or not peek_hold() else None)
            return
        if self.wheel.is_open():
            if mode == self.wheel.mode:
                self.wheel.dismiss()
            else:
                play_tick()
                self.wheel.set_mode(mode)
            return
        self._idle_paths(lambda paths: self.wheel.popup(mode, paths, click_mode=True))

    def _show_peek(self, paths):
        if self._peek is None:
            self._peek = PeekWindow()
        self._peek.peek(paths)

    def _idle_paths(self, then):
        """The file under the mouse (Mouse hover) or the files selected (File selection), handed to `then`."""
        trig = trigger_mode()
        if trig == "select":
            hwnd = winsys.foreground_hwnd()
            if winsys.window_class(hwnd) not in self.EXPLORER_CLASSES:
                return
            paths = [p for p in winsys.explorer_selection(hwnd) if p and os.path.exists(p)]
            winsys.log(f"selection tap: {len(paths)} file(s)")
            if paths:
                then(paths)
        elif trig == "hover":
            pos = winsys.cursor_pos()
            root = winsys.root_window_at(*pos)
            if winsys.window_class(root) not in self.EXPLORER_CLASSES:
                return
            winsys.click_at_cursor()                   # selects the file under the mouse

            def after():
                paths = [p for p in winsys.explorer_selection(root) if p and os.path.exists(p)]
                winsys.log(f"hover tap: {len(paths)} file(s)")
                if paths:
                    then(paths[:1])
            QTimer.singleShot(180, after)

    def on_hotkey(self):
        if self.wheel.is_open():                   # Ctrl+Alt+Space again closes it
            self.wheel.dismiss()
            return
        paths = winsys.explorer_selection()
        if not paths:
            self.toast.show_msg(tr("Nothing selected"), tr("Select files in File Explorer, then press Ctrl+Alt+Space"))
            return
        self.open_paths(paths)

    def open_paths(self, paths, mode="convert"):
        paths = [str(Path(p)) for p in paths if os.path.exists(p)]
        if paths:
            self.wheel.popup(mode, paths, click_mode=True)

    def queue_paths(self, paths):
        self.pending += paths
        self.pending_timer.start()

    def _flush_pending(self):
        """Explorer starts ConvertANNY once per file when you right-click many files, and they arrive one by one:
        files that come in while that wheel is still open join it instead of replacing it."""
        paths, self.pending = list(dict.fromkeys(self.pending)), []
        now = time.monotonic()
        if (self.wheel.is_open() and self.wheel.click_mode and self.wheel.paths
                and now - getattr(self, "_last_batch", 0.0) < 8.0):
            merged = list(dict.fromkeys(self.wheel.paths + [str(Path(p)) for p in paths if os.path.exists(p)]))
            self.wheel.set_paths(merged)
            self.wheel.update()
            winsys.log(f"right-click batch: {len(merged)} files")
        elif (getattr(self, "_batch_op", None) and now - self._batch_op[1] < 10.0
              and now - getattr(self, "_last_batch", 0.0) < 10.0):
            # you already chose a slice while the rest of the files were still arriving: they get it too
            op = self._batch_op[0]
            late = [str(Path(p)) for p in paths if os.path.exists(p)]
            winsys.log(f"right-click batch: {len(late)} more files for {op.id}")
            if late:
                self.execute(op, late)
        else:
            self._batch_op = None
            self.open_paths(paths)
        self._last_batch = now

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(None, tr("Choose files to convert"))
        if files:
            self.open_paths(files)

    # ---- run
    def execute(self, op: engine.Op, paths: list[str]):
        if op.id == "none":
            return
        if (self.wheel.click_mode and time.monotonic() - getattr(self, "_last_batch", 0.0) < 10.0
                and not op.ui and not op.ask and (op.group != "action" or op.id == "unblock")):
            self._batch_op = (op, time.monotonic())        # files still arriving from a right-click get it too
        else:
            self._batch_op = None
        play_select()
        params = {}
        if getattr(op, "spec", None):
            params["_spec"] = op.spec
        if op.ui == "crop":
            from editor import CropResizeDialog
            for p in paths[:5]:           # one editor per image
                try:
                    dlg = CropResizeDialog(p, DIALOG_CSS, app_icon(), ensure_model=self._ensure_model)
                except Exception as e:
                    self.toast.show_msg(tr("Couldn't open image"), str(e), "err", 6000)
                    continue
                if dlg.exec() == QDialog.Accepted:
                    self._start(op, [p], dlg.params())
            return
        if op.ask:
            params = ask_params(op, paths)
            if params is None:
                return
        if op.model and not engine.model_ready(op.model):
            self._get_model(op, paths, params)
            return
        if op.group == "action":
            try:
                op.fn(paths, params)
            except Exception as e:
                self.toast.show_msg(tr("Couldn't do that"), str(e), "err", 6000)
            return
        self._start(op, paths, params)

    def _get_model(self, op, paths, params):
        """Ask once, then download the AI model `op` needs and run the op when it's ready."""
        self._ensure_model(op.model, tr(op.label).rstrip("…"), lambda: self._start(op, paths, params))

    def predownload(self):
        """Downloads ticked in the installer ("Optional downloads"), one after another, after ConvertANNY starts."""
        s = settings()
        s.beginGroup("predownload")
        names = [k for k in s.childKeys() if s.value(k) == "1"]
        s.endGroup()
        labels = {"isnet": tr("Remove background"), "whisper-small": tr("Transcribe…").rstrip("…"),
                  "yt-dlp": tr("Paste link to Float"), "cloudflared": tr("Link from this PC")}
        todo = [n for n in names if n in engine.MODELS]

        def nxt():
            while todo:
                name = todo.pop(0)
                if engine.model_ready(name):
                    settings().remove(f"predownload/{name}")
                    continue

                def done(name=name):
                    settings().remove(f"predownload/{name}")
                    QTimer.singleShot(500, nxt)
                self._ensure_model(name, labels.get(name, name), done, ask=False, on_fail=lambda: QTimer.singleShot(500, nxt))
                return
        if todo:
            winsys.log(f"optional downloads from the installer: {todo}")
            QTimer.singleShot(4000, nxt)

    def _ensure_model(self, name, what, on_ready, ask=True, on_fail=None):
        """Download a model or tool once (after asking), then call on_ready()."""
        if engine.model_ready(name):
            on_ready()
            return
        if not ask:
            return self._download_model(name, what, on_ready, on_fail)
        m = engine.MODELS[name]
        mb = m.get("mb") or m["size"] // 1048576
        box = QMessageBox()
        box.setWindowTitle(APP)
        box.setWindowIcon(app_icon())
        box.setStyleSheet(i18n.css(DIALOG_CSS))
        box.setIconPixmap(app_icon().pixmap(48, 48))
        if name == "yt-dlp":
            box.setText(tr("{what} needs a one-time download of the free yt-dlp tool ({mb} MB) to play links "
                           "from YouTube and other sites.", what=what, mb=mb))
        elif name == "cloudflared":
            box.setText(tr("{what} needs a one-time download of Cloudflare's free tunnel tool ({mb} MB). "
                           "It needs no account.", what=what, mb=mb))
        else:
            box.setText(tr("{what} needs a one-time download of its AI model ({mb} MB). It is saved on this PC, "
                           "and everything runs offline after that.", what=what, mb=mb))
        ok = box.addButton(tr("Download"), QMessageBox.AcceptRole)
        box.addButton(tr("Cancel"), QMessageBox.RejectRole)
        box.setDefaultButton(ok)
        box.exec()
        if box.clickedButton() is not ok:
            return
        self._download_model(name, what, on_ready, on_fail)

    def _download_model(self, name, what, on_ready, on_fail=None):
        job = ModelDownload(name)
        job.setAutoDelete(False)
        self._update_jobs.add(job)

        def cancel():
            job.stop = True
        job.card = self.toast.show_busy(tr("Downloading AI model…") if name not in ("yt-dlp", "cloudflared") else tr("Download") + "…",
                                        what, cancel)

        def progress(done, total, card=job.card):
            if total and card in self.toast.cards:
                card.body.setText(f"{what} — {done * 100 // total}%  ({done / 1048576:.0f} / {total / 1048576:.0f} MB)")

        def finished(path, err, job=job):
            self._update_jobs.discard(job)
            if job.card in self.toast.cards:
                job.card.close_card()
            if err == CANCELLED:
                if on_fail:
                    on_fail()
                return
            if err:
                self.toast.show_msg(tr("Couldn't download the AI model") if name not in ("yt-dlp", "cloudflared") else tr("Couldn't do that"),
                                    err, "err", 8000)
                if on_fail:
                    on_fail()
                return
            winsys.log(f"model {name} ready: {path}")
            on_ready()
        job.sig.progress.connect(progress, Qt.QueuedConnection)
        job.sig.downloaded.connect(finished, Qt.QueuedConnection)
        self.pool.start(job)

    def on_ctrl_open(self, hwnd):
        """Ctrl + double-click on a file in Explorer or on the desktop: open it in a float."""
        def go():
            paths = winsys.explorer_selection(hwnd, focused=True)
            winsys.log(f"ctrl+double-click: {paths}")
            if paths and os.path.exists(paths[0]):
                self.actions.float(paths[:1], {})
        QTimer.singleShot(120, go)

    def open_empty_float(self):
        """Right-click on the desktop → Open Float: an empty float to drop a file on or paste a link into."""
        w = FloatWindow("")
        self.floats.append(w)
        self._sync_media_polling()
        w.closed.connect(lambda w=w: self._forget_float(w))
        w.show()
        w.come_forward()
        w.activateWindow()
        w.setFocus()

    def read_qr_on_screen(self):
        """Tray or desktop right-click → Read QR code on screen: a still of each screen with its codes lit up."""
        if getattr(self, "_qr_overlays", None):
            return
        shots = []
        for sc in QGuiApplication.screens():
            pm = sc.grabWindow(0)
            try:
                codes = find_codes(pm.toImage())
            except Exception as e:
                winsys.log(f"read qr: {e}")
                codes = []
            shots.append((sc, pm, codes))
        winsys.log(f"read qr: {sum(len(c) for _s, _p, c in shots)} code(s) on {len(shots)} screen(s)")
        overlays = []

        def done(codes):
            for o in overlays:
                o.close()
            self._qr_overlays = None
            if codes:
                self.show_qr_result(codes)
        for sc, pm, codes in shots:
            overlays.append(QrScanOverlay(sc, pm, codes, done))
        self._qr_overlays = overlays
        under = QGuiApplication.screenAt(QCursor.pos())
        for o, (sc, _p, _c) in zip(overlays, shots):
            o.show()
            o.raise_()
            if sc is under:
                o.activateWindow()
                o.setFocus()
                winsys.bring_to_front(int(o.winId()))

    def _end_shares(self):
        """Quitting: shares that live in a window end without asking."""
        for w in list(getattr(self, "_phone_windows", [])):
            try:
                w._leaving = True
                if isinstance(w, PhoneShare) and not w.ended:
                    w.close()
            except RuntimeError:
                pass

    def show_qr_result(self, codes):
        winsys.log(f"read qr: {len(codes)} code(s) read")
        w = QrResult(codes)
        self._phone_windows = getattr(self, "_phone_windows", [])
        self._phone_windows.append(w)
        w.show()
        w.raise_()
        w.activateWindow()

    def play_link(self, target=None, url=None):
        """Play the link on the clipboard (YouTube and other sites, or a direct media link) in a float.
        The float opens straight away with the loading circle and plays when the link is ready."""
        if url is None and not engine.is_link(QGuiApplication.clipboard().text().strip()):
            f = _clipboard_media_file()               # a copied file or path: play it in Float too
            if f:
                if target is not None and target in self.floats:
                    target._play_now = True
                    target._load(f)
                    target._fade_to(1.0)
                    target.come_forward()
                else:
                    self.actions.float([f], {})
                return
        url = url or QGuiApplication.clipboard().text().strip()
        if not engine.is_link(url):
            self.toast.show_msg(tr("No link on the clipboard"), tr("Copy a link to a video or song first."), "info", 4000)
            return
        from urllib.parse import urlparse
        direct = urlparse(url).path.lower().endswith(engine.MEDIA_LINK_EXT)

        def go():
            t = target if target is not None and target in self.floats else None
            title = next((link_name(x) for x in saved_links() if x["url"] == url), None) or url
            pending = {"page": url, "title": title, "pending": True}
            restore = None
            if t is None:                                      # a new float, loading right away
                t = FloatWindow("", pending)
                self.floats.append(t)
                self._sync_media_polling()
                t.closed.connect(lambda w=t: self._forget_float(w))
                t.show()
                t.come_forward()
            elif settings().value("float_link_stops", "true") == "true" or t.kind == "empty":
                if t.kind != "empty":
                    restore = (t.path, t.link)                 # put back if the link doesn't open
                t._load("", pending)                           # stop what's playing, show the loading circle
            t._play_now = True
            self._resolve_and_play(url, t, show_card=False, restore=restore, new=target is None)
        if direct or engine.model_ready("yt-dlp"):
            go()
        else:
            self._ensure_model("yt-dlp", tr("Paste link"), go)

    def _resolve_and_play(self, url, target, pin=None, quiet=False, quality=None, show_card=True, restore=None, new=False):
        job = LinkResolve(url, quality)
        job.setAutoDelete(False)
        self._update_jobs.add(job)
        self.busy_links = getattr(self, "busy_links", 0) + 1
        card = None if (pin or quiet or not show_card) else self.toast.show_busy(tr("Opening link…"), url[:70])

        def done(info, err, job=job):
            self._update_jobs.discard(job)
            self.busy_links = max(0, getattr(self, "busy_links", 1) - 1)
            if card is not None and card in self.toast.cards:
                card.close_card()
            if not err and info:
                page = info.get("page") or url
                # a saved link stays under the address you saved (the site may answer with a longer one)
                saved_urls = [x["url"] for x in saved_links()]
                key = url if url in saved_urls else page
                info["saved"] = key
                if key in saved_urls:
                    refresh_link_title(key, info.get("title"))   # saved links keep their place and name
                if not quiet:
                    remember_played("link", key, info.get("title"))   # Recently played (saving is up to you)
            if err and pin is not None and pin.get("_tries", 0) < 4:     # at sign-in the network may not be up yet
                pin["_tries"] = pin.get("_tries", 0) + 1
                QTimer.singleShot(15000, lambda: self._resolve_and_play(url, None, pin=pin))
                return
            if err:
                winsys.log(f"link failed: {url}: {err}")
                self.toast.show_msg(tr("Couldn't open this link"), tr(err), "err", 8000)
                if target is not None and target in self.floats and (target.link or {}).get("pending") and not quiet:
                    if new:
                        target.close()                         # the float made just for this link
                    elif restore and (restore[0] or restore[1]):
                        target._play_now = False
                        target._load(*restore)                 # back to what it showed before
                    else:
                        target._load("")
                return
            if target is not None and target in self.floats:
                if quiet:                                  # live stream reconnect: keep size and controls as they are
                    target.restart_live(info)
                    return
                target._load(info["url"], info)
                target._fade_to(1.0)
                QTimer.singleShot(1600, target._maybe_hide_controls)
                return
            w = FloatWindow(info["url"], info, play=bool(pin.get("playing", True)) if pin else False, pin=pin)
            self.floats.append(w)
            self._sync_media_polling()
            w.closed.connect(lambda w=w: self._forget_float(w))
            w.show()
            if not pin:
                w.come_forward()
        job.sig.done.connect(done, Qt.QueuedConnection)
        self.pool.start(job)

    def save_clipboard_image(self, folder=None):
        """Save the image on the clipboard: the Convert wheel opens on it so you pick the file type, and the
        file is saved in `folder` (the folder you right-clicked in), or Pictures\\ConvertANNY from the tray.
        Files copied in Explorer open the wheel directly."""
        import datetime
        import tempfile
        cb = QGuiApplication.clipboard()
        md = cb.mimeData()
        files = [u.toLocalFile() for u in (md.urls() if md and md.hasUrls() else []) if u.isLocalFile()]
        if files:
            self.open_paths(files)
            return
        img = cb.image()
        if img.isNull():
            self.toast.show_msg(tr("No image on the clipboard"), tr("Copy a picture or take a screenshot first."), "info", 4000)
            return
        if not folder or not os.path.isdir(folder):
            folder = str(Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Pictures" / APP)
            Path(folder).mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.gettempdir()) / "ConvertANNY-clipboard"
        tmp.mkdir(exist_ok=True)
        path = tmp / f"Clipboard {datetime.datetime.now():%Y-%m-%d %H-%M-%S}.bmp"
        if not img.save(str(path), "BMP"):
            self.toast.show_msg(tr("Couldn't do that"), str(path), "err", 6000)
            return
        self.out_override[str(path)] = folder
        self.wheel.popup("convert", [str(path)], click_mode=True)

    def _media_tick(self):
        """Keyboard media keys control the float that was used last (or one that is playing)."""
        floats = [f for f in self.floats if getattr(f, "player", None)]
        if not floats:
            self._media_timer.stop()
            self._media_down.clear()
            return
        for vk, key in ((0xB3, "play"), (0xB0, "next"), (0xB1, "prev"), (0xB2, "stop")):
            down = winsys.key_down(vk)
            if down and not self._media_down.get(vk):
                target = FloatWindow.last_used if FloatWindow.last_used in floats else None
                target = target or next((f for f in floats if f._playing()), floats[-1])
                focused = target.isActiveWindow()
                shown = target.media_key(key)
                if shown and MediaOSD.wanted(focused):
                    MediaOSD.flash(shown, target)
            self._media_down[vk] = down

    def _sync_media_polling(self):
        """Poll Windows media keys only while a float owns a media player."""
        active = any(getattr(window, "player", None) is not None for window in self.floats)
        if active and not self._media_timer.isActive():
            self._media_timer.start()
        elif not active and self._media_timer.isActive():
            self._media_timer.stop()
            self._media_down.clear()

    def _forget_float(self, window):
        if window in self.floats:
            self.floats.remove(window)
        self._sync_media_polling()
    def _update_cursor_busy(self):
        busy = bool(self._active_jobs() or getattr(self, "busy_links", 0))
        self.cursor_busy.set_busy(busy and settings().value("cursor_busy", "true") == "true")

    def on_volume_key(self, vk):
        """Volume keys or a volume knob: Windows changes the volume; show it big while a float is playing.
        Every step refreshes the sign; it goes away 2 seconds after the last one."""
        playing = [f for f in self.floats if getattr(f, "player", None) and f._playing()]
        if not playing:
            return
        target = FloatWindow.last_used if FloatWindow.last_used in playing else playing[-1]
        if MediaOSD.wanted(target.isActiveWindow()):
            QTimer.singleShot(40, lambda t=target: self._show_volume(t))

    def _show_volume(self, target):
        v = winsys.system_volume()
        if v is not None:
            MediaOSD.flash("mute" if v[1] else "volume", target, level=v[0], hold=2000)

    def _start(self, op, paths, params):
        name = Path(paths[0]).name if len(paths) == 1 else tr("{n} files", n=len(paths))
        w = Worker(op, paths, params)
        w.output_dir = self.out_override.get(paths[0])     # e.g. clipboard image saved "here"
        cancel = lambda w=w: self._cancel_job(w)
        if op.group == "convert":
            w.card = self.toast.show_busy(tr("Converting to {fmt}…", fmt=tr(op.label)), name, cancel)
        else:
            w.card = self.toast.show_busy(tr(op.label).rstrip("…") + "…", name, cancel)
        w.setAutoDelete(False)
        w.sig.done.connect(self._done, Qt.QueuedConnection)
        w.sig.progress.connect(lambda wk, f, name=name: self._job_progress(wk, f, name), Qt.QueuedConnection)
        w.sig.count.connect(self._job_count, Qt.QueuedConnection)
        if settings().value("job_mode", "queue") == "queue" and self._active_jobs():
            self.waiting.append(w)                # one job at a time: wait for the ones before it
            w.card.body.setText(name + " — " + tr("waiting ({n} in line)", n=len(self.waiting)))
            return
        self._launch(w)

    def _launch(self, w):
        self.running.add(w)                       # keep Python refs alive until done
        self.pool.start(w)

    def _next_in_line(self):
        while self.waiting and not self._active_jobs():
            w = self.waiting.pop(0)
            if w.cancel_requested:
                continue
            if w.card is not None and w.card in self.toast.cards:
                w.card.body.setText(Path(w.paths[0]).name if len(w.paths) == 1 else tr("{n} files", n=len(w.paths)))
            self._launch(w)
        for i, w in enumerate(self.waiting):
            if w.card is not None and w.card in self.toast.cards:
                name = Path(w.paths[0]).name if len(w.paths) == 1 else tr("{n} files", n=len(w.paths))
                w.card.body.setText(name + " — " + tr("waiting ({n} in line)", n=i + 1))

    def _job_count(self, worker, done, total):
        worker.count = (done, total)

    def _job_progress(self, worker, frac, name):
        card = worker.card
        if card is not None and card in self.toast.cards and not worker.cancel_requested:
            done, total = worker.count
            if total > 1:                      # a batch: "12 of 40 done — 31%"
                card.body.setText(tr("{a} of {b} done", a=done, b=total) + f" — {int(frac * 100)}%")
            else:
                card.body.setText(f"{name} — {int(frac * 100)}%")

    # ---- updating: warn about running jobs, keep the open floats
    def _ask_jobs_before_update(self, installer_waiting):
        """None = no jobs. Otherwise the button chosen: "now" | "wait" | "cancel"."""
        jobs = self._active_jobs()
        if not jobs:
            return None
        box = QMessageBox()
        box.setWindowTitle(f"{APP} — " + tr("Update"))
        box.setWindowIcon(app_icon())
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        box.setStyleSheet(i18n.css(DIALOG_CSS))
        box.setIconPixmap(app_icon().pixmap(48, 48))
        names = "<br>".join(f"• {Path(w.paths[0]).name}" for w in jobs[:5])
        box.setText(f"<b>{tr('Jobs still running: {n}', n=len(jobs))}</b><br><br>{names}<br><br>"
                    + tr("Updating closes ConvertANNY and stops them; their unfinished files are removed."))
        now = box.addButton(tr("Stop them and update"), QMessageBox.DestructiveRole)
        wait = None if installer_waiting else box.addButton(tr("Update when they finish"), QMessageBox.AcceptRole)
        no = box.addButton(tr("Don't update now"), QMessageBox.RejectRole)
        box.setDefaultButton(wait or no)
        box.exec()
        b = box.clickedButton()
        return "now" if b is now else "wait" if (wait is not None and b is wait) else "cancel"

    def save_open_floats(self):
        states = []
        for f in list(self.floats):
            try:
                states.append(f.state())
            except Exception as e:
                winsys.log(f"float state: {e}")
        settings().setValue("float_resume", json.dumps(states))
        settings().sync()
        winsys.log(f"saved {len(states)} open floats for after the update")

    def prepare_for_update(self) -> bool:
        """The installer is about to replace ConvertANNY (asked over the local socket). False = the user said not now."""
        if not getattr(self, "_update_confirmed", False):
            choice = self._ask_jobs_before_update(installer_waiting=True)
            if choice == "cancel":
                return False
        for w in self._active_jobs():
            self._cancel_job(w)
        self.save_open_floats()
        return True

    def quit_for_update(self, started=None):
        """Quit once cancelled jobs have cleaned up (at most ~6 s)."""
        import time
        started = started or time.monotonic()
        if self.running and time.monotonic() - started < 6:
            QTimer.singleShot(200, lambda: self.quit_for_update(started))
            return
        for f in list(self.floats):
            if f.player:
                f.player.stop()
        self.qapp.quit()

    def _cancel_job(self, worker):
        if worker.cancel_requested:
            return
        play_finish_sound("err")
        if worker in self.waiting:                 # not started yet: just take it out of the line
            self.waiting.remove(worker)
            worker.cancel()
            if worker.card is not None and worker.card in self.toast.cards:
                worker.card.show_msg(tr("Cancelled"), tr("Nothing was saved."), "info", 3000)
            self._next_in_line()
            return
        worker.cancel()
        if worker.card is not None and worker.card in self.toast.cards:
            worker.card.show_busy(tr("Cancelling…"), Path(worker.paths[0]).name)

    def _done(self, worker, outs, err):
        self.running.discard(worker)
        QTimer.singleShot(0, self._next_in_line)
        op = worker.op
        card = worker.card if worker.card is not None and worker.card in self.toast.cards else None
        target = card or self.toast
        if card is not None and err != CANCELLED:
            card._sound_for_this = True            # finish sound (when turned on)
        elif card is None and err != CANCELLED and not err:
            play_finish_sound("ok")
        if err == CANCELLED:
            target.show_msg(tr("Cancelled"), tr("Nothing was saved."), "info", 3000)
        elif err:
            winsys.log(f"job failed: {op.group}/{op.id} on {worker.paths[:3]}: {err}")
            target.show_msg(tr("{what} failed", what=tr(op.label).rstrip("…")), tr(err), "err", 8000)
        elif op.id == "install" and outs:
            names = [json.loads(str(o)[5:]).get("font", "") for o in outs if str(o).startswith("info:")]
            target.show_msg(tr("Font installed"), ", ".join(names) + "<br>" + tr("Ready in your apps (restart an app if it was open)."), "ok", 8000)
        elif op.id == "count" and outs:
            infos = [json.loads(str(o)[5:]) for o in outs if str(o).startswith("info:")]
            tot = {k: sum(i.get(k, 0) for i in infos) for k in ("words", "chars", "chars_spaces", "pages")}
            title = infos[0]["name"] if len(infos) == 1 else tr("{n} files", n=len(infos))
            lines = [tr("Words: {n}", n=f"{tot['words']:,}"),
                     tr("Characters: {n} ({m} with spaces)", n=f"{tot['chars']:,}", m=f"{tot['chars_spaces']:,}")]
            if any("pages" in i for i in infos):
                lines.append(tr("Pages: {n}", n=f"{tot['pages']:,}"))
            minutes = max(1, round(tot["words"] / 200))
            lines.append(tr("About {n} min to read", n=minutes))
            QGuiApplication.clipboard().setText("\n".join([title] + lines))
            target.show_msg(title, "<br>".join(lines), "ok", 12000)
        elif op.id == "ocr" and outs:
            try:
                QGuiApplication.clipboard().setText(Path(outs[0]).read_text(encoding="utf-8").strip())
                target.show_result(tr("Copied to clipboard"), outs)
            except Exception as e:
                target.show_msg(tr("Couldn't do that"), str(e), "err", 6000)
        else:
            outs = self._place_results(worker, outs)
            if outs is None:
                if card is not None:
                    card.close_card()
                return
            title = tr("Done") if op.group == "tool" else tr("Converted to {fmt}", fmt=tr(op.label))
            if worker.failed:
                names = ", ".join(n for n, _e in worker.failed[:3]) + ("…" if len(worker.failed) > 3 else "")
                winsys.log(f"batch: {len(worker.failed)} failed: " + " | ".join(f"{n}: {e}" for n, e in worker.failed[:10]))
                c = target.show_msg(title, tr("{a} of {b} done. These couldn't be done: {names}",
                                              a=len(worker.paths) - len(worker.failed), b=len(worker.paths), names=names),
                                    "err", 12000) or target
                c.target = [str(o) for o in outs]
                c.btn.setVisible(bool(outs))
                c.set_undo(self._undo_for(outs, worker))
            else:
                c = target.show_result(title, outs) or target
                c.set_undo(self._undo_for(outs, worker))
            self._remember(outs, worker)

    def _undo_for(self, outs, worker):
        """Undo for files a job just made — not when they replaced the originals or went to the clipboard."""
        outs = [Path(o) for o in outs or [] if o]
        if not outs or settings().value("output_mode", "next") in ("replace", "clipboard"):
            return None
        srcs = {str(Path(p)).lower() for p in worker.paths}
        if any(str(o).lower() in srcs for o in outs):            # edited in place: nothing to take back safely
            return None

        def undo():
            ok = True
            for o in outs:
                try:
                    if o.exists():
                        winsys.recycle(str(o))
                except Exception as e:
                    winsys.log(f"undo: {o}: {e}")
                    ok = False
            self._forget(outs)
            winsys.log(f"undo: {len(outs)} result(s) to the Recycle Bin")
            return ok
        return undo

    # ---- recent results (tray menu)
    def _remember(self, outs, worker):
        try:
            recent = json.loads(settings().value("recent_results", "[]") or "[]")
        except (TypeError, ValueError):
            recent = []
        what = tr("Converted to {fmt}", fmt=tr(worker.op.label)) if worker.op.group == "convert" else tr(worker.op.label).rstrip("…")
        for o in outs or []:
            o = str(o)
            if not o or o.startswith("info:"):
                continue
            recent = [r for r in recent if r.get("path") != o]
            recent.insert(0, {"path": o, "what": what})
        settings().setValue("recent_results", json.dumps(recent[:10], ensure_ascii=False))

    def _forget(self, outs):
        try:
            recent = json.loads(settings().value("recent_results", "[]") or "[]")
        except (TypeError, ValueError):
            return
        gone = {str(o) for o in outs}
        settings().setValue("recent_results", json.dumps([r for r in recent if r.get("path") not in gone], ensure_ascii=False))

    def _fill_recent(self, sub):
        sub.clear()
        try:
            recent = json.loads(settings().value("recent_results", "[]") or "[]")
        except (TypeError, ValueError):
            recent = []
        recent = [r for r in recent if os.path.exists(r.get("path", ""))]
        if not recent:
            a = sub.addAction(tr("Nothing yet"))
            a.setEnabled(False)
            return
        from PySide6.QtCore import QFileInfo
        from PySide6.QtWidgets import QFileIconProvider
        prov = QFileIconProvider()
        for r in recent:
            p = Path(r["path"])
            name = p.name if len(p.name) <= 46 else p.name[:43] + "…"
            m = sub.addMenu(prov.icon(QFileInfo(str(p))), name)
            m.setToolTipsVisible(True)
            m.addAction(tr("Open"), lambda _=False, p=p: os.startfile(str(p)) if hasattr(os, "startfile") else None)
            m.addAction(tr("Show in folder"), lambda _=False, p=p: winsys.reveal([str(p)]))
            m.addAction(tr("Open in Float"), lambda _=False, p=p: self.actions.float([str(p)], {}))
            info = m.addAction(r.get("what", ""))
            info.setEnabled(False)
        sub.addSeparator()
        sub.addAction(tr("Clear this list"), lambda: settings().setValue("recent_results", "[]"))

    def _place_results(self, worker, outs):
        """Where results go (Settings → Output): replace the original (asks first) or copy to the clipboard.
        Returns the final paths, or None when the clipboard took them."""
        mode = settings().value("output_mode", "next")
        outs = [Path(o) for o in outs if o]
        if worker.paths and worker.paths[0] in self.watch.done:
            if worker.paths[0] in self.watch.overwrite:
                return self._watch_overwrite(worker.paths[0], outs)
            return outs                                  # watch folders keep results in their own folder
        if not outs or mode not in ("replace", "clipboard"):
            return outs
        if mode == "clipboard":
            import tempfile
            dest = Path(tempfile.gettempdir()) / "ConvertANNY clipboard"
            dest.mkdir(exist_ok=True)
            moved = []
            for o in outs:
                t = engine.unique_path(dest / o.name)
                shutil.move(str(o), str(t))
                moved.append(t)
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(str(m)) for m in moved])
            if len(moved) == 1 and engine.EXT_CATEGORY.get(engine.ext_of(str(moved[0]))) == "image":
                img = QImage(str(moved[0]))
                if not img.isNull():
                    md.setImageData(img)                      # paste works in chat apps and editors too
            QGuiApplication.clipboard().setMimeData(md)
            self.toast.show_msg(tr("Copied to clipboard"), moved[0].name if len(moved) == 1 else
                                tr("{n} files", n=len(moved)), "ok", 4000)
            return None
        # replace: only when each result clearly belongs to one original
        src = [Path(p) for p in worker.paths]
        if worker.op.multi or len(src) != len(outs) or any(o.is_dir() for o in outs):
            return outs
        if settings().value("replace_no_ask", "false") != "true":
            box = QMessageBox()
            box.setWindowTitle(f"{APP} — " + tr("Replace the original"))
            box.setWindowIcon(app_icon())
            box.setStyleSheet(i18n.css(DIALOG_CSS))
            box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            pairs = "<br>".join(f"{a.name} → {b.name}" for a, b in list(zip(src, outs))[:6])
            box.setText(tr("Replace the original file(s) with the new one(s)? The originals go to the Recycle Bin.")
                        + "<br><br>" + pairs)
            again = QCheckBox(tr("Don't ask again"))
            box.setCheckBox(again)
            yes = box.addButton(tr("Replace"), QMessageBox.AcceptRole)
            box.addButton(tr("Keep both"), QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                return outs
            if again.isChecked():
                settings().setValue("replace_no_ask", "true")
        final = []
        for a, b in zip(src, outs):
            try:
                winsys.recycle(str(a))
                target = a.with_suffix(b.suffix) if a.suffix.lower() != b.suffix.lower() else a
                if target.exists():
                    target = engine.unique_path(target)
                shutil.move(str(b), str(target))
                final.append(target)
            except Exception as e:
                winsys.log(f"replace failed for {a}: {e}")
                final.append(b)
        return final

    def _watch_overwrite(self, original, outs):
        """Auto Convert set to 'Overwrite original': the result takes the original's place (original to the Recycle Bin)."""
        self.watch.overwrite.discard(original)
        a = Path(original)
        if len(outs) != 1 or outs[0].is_dir():
            return outs                                  # several results: keep them in "Converted"
        b = outs[0]
        try:
            target = a.with_suffix(b.suffix)
            if target.exists() and target != a:
                target = engine.unique_path(target)
            self.watch.done.add(str(target))             # don't convert our own result again
            winsys.recycle(str(a))
            shutil.move(str(b), str(target))
            try:
                b.parent.rmdir()                         # "Converted" only if it is now empty
            except OSError:
                pass
            winsys.log(f"auto convert: {a.name} overwritten by {target.name}")
            return [target]
        except Exception as e:
            winsys.log(f"auto convert overwrite failed for {a}: {e}")
            return outs

    # ---- updates
    def _auto_update_check(self):
        import time
        s = settings()
        if s.value("check_updates", "true") != "true":
            return
        if time.time() - float(s.value("last_update_check", 0) or 0) < 20 * 3600:
            return
        self.check_updates(manual=False)

    def check_updates(self, manual=True):
        import time
        settings().setValue("last_update_check", time.time())
        job = UpdateCheck(manual)
        job.setAutoDelete(False)
        self._update_jobs.add(job)
        job.sig.checked.connect(lambda rel, err, m, job=job: self._update_checked(job, rel, err, m), Qt.QueuedConnection)
        repo_url = updater.releases_url()
        job.card = self.toast.show_busy(tr("Checking for updates…"), repo_url) if manual and repo_url else None
        self.pool.start(job)

    def _update_checked(self, job, rel, err, manual):
        self._update_jobs.discard(job)
        card = getattr(job, "card", None) if job is not None else None
        card = card if card is not None and card in self.toast.cards else None
        target = card or self.toast
        winsys.log(f"update check: latest={getattr(rel, 'version', None)} err={err}")
        if err:
            if manual:
                target.show_msg(tr("Couldn't check for updates"), err, "err", 6000)
            return
        if not updater.is_newer(rel.version, VERSION):
            if manual:
                target.show_msg(tr("You're up to date"), tr("{app} {v} is the latest version.", app=APP, v=VERSION), "ok", 4000)
            return
        if not manual and settings().value("skip_version", "") == rel.version:
            return
        if card:
            card.close_card()
        self._offer_update(rel)

    def _offer_update(self, rel):
        box = QMessageBox()
        box.setWindowTitle(tr("{app} update", app=APP))
        box.setWindowIcon(app_icon())
        box.setStyleSheet(i18n.css(DIALOG_CSS))
        box.setIconPixmap(app_icon().pixmap(48, 48))
        box.setTextFormat(Qt.RichText)
        notes = rel.notes.split("\n\n")[0][:400].replace("**", "") if rel.notes else ""
        dimc = theme.hexc("dim")
        box.setText(f"<b>{tr('{app} {v} is available', app=APP, v=rel.version)}</b><br>"
                    f"<span style='color:{dimc}'>{tr('You have {v}.', v=VERSION)}</span><br><br>{notes}")
        install = box.addButton(tr("Download && install"), QMessageBox.AcceptRole) if rel.installer_url else None
        page = box.addButton(tr("Open release page"), QMessageBox.ActionRole)
        skip = box.addButton(tr("Skip this version"), QMessageBox.RejectRole)
        later = box.addButton(tr("Later"), QMessageBox.RejectRole)
        box.setDefaultButton(install or page)
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        box.exec()
        clicked = box.clickedButton()
        if clicked is install:
            self._download_update(rel)
        elif clicked is page:
            QDesktopServices.openUrl(QUrl(rel.page))
        elif clicked is skip:
            settings().setValue("skip_version", rel.version)

    def _download_update(self, rel):
        job = UpdateDownload(rel)
        job.setAutoDelete(False)
        self._update_jobs.add(job)

        def cancel():
            job.stop = True
        name = rel.installer_name or "ConvertANNY-Setup.exe"
        job.card = self.toast.show_busy(tr("Downloading update…"), name, cancel)

        def progress(done, total, card=job.card):
            if total and card in self.toast.cards:
                card.body.setText(f"{name} — {done * 100 // total}%  ({done / 1048576:.0f} / {total / 1048576:.0f} MB)")
        job.sig.progress.connect(progress, Qt.QueuedConnection)
        job.sig.downloaded.connect(lambda path, err, job=job: self._update_downloaded(job, path, err), Qt.QueuedConnection)
        self.pool.start(job)

    def _update_downloaded(self, job, path, err):
        self._update_jobs.discard(job)
        card = job.card if job.card in self.toast.cards else None
        if card:
            card.close_card()
        if err == CANCELLED:
            self.toast.show_msg(tr("Cancelled"), tr("The update was not downloaded."), "info", 3000)
            return
        if err:
            self.toast.show_msg(tr("Couldn't download the update"), err, "err", 8000)
            return
        choice = self._ask_jobs_before_update(installer_waiting=False)
        if choice == "cancel":
            self.toast.show_msg(tr("Update postponed"), tr("Check for updates again from the tray when you're ready."), "info", 5000)
            return
        if choice == "wait":
            self.toast.show_msg(tr("Update waiting"), tr("It installs when the running jobs finish."), "info", 5000)
            self._install_when_idle(path)
            return
        self._update_confirmed = choice == "now"
        self._launch_installer(path)

    def _install_when_idle(self, path):
        if self._active_jobs():
            QTimer.singleShot(1500, lambda: self._install_when_idle(path))
            return
        self._launch_installer(path)

    def _launch_installer(self, path):
        winsys.log(f"launching installer {path}")
        try:
            os.startfile(str(path))          # Windows asks for admin
        except Exception as e:
            self.toast.show_msg(tr("Couldn't start the installer"), str(e), "err", 8000)
            return
        self.toast.show_msg(tr("Installing update…"), tr("Finish the steps in the setup window."), "info", 4000)
        # Keep running: the installer closes ConvertANNY itself when Install is pressed
        # (and cancelling setup leaves the app running).

    # ---- windows
    # Settings has eight pages of controls; building them takes about a second, and everything else (a playing
    # float too) waits meanwhile. So a copy is built ahead of time, while no float is playing, and shown at once.
    _VOLATILE = ("float_resume", "float_recent", "recent_results", "float_volume", "geometry",
                 "share_links", "float_pins", "last_dir", "float_links", "float_repeat", "link_quality",
                 "share_way", "share_minutes", "sign_mode", "pdf_watermark", "InstallerLanguage")

    def _settings_snapshot(self):
        s = settings()
        return hash(tuple((k, str(s.value(k))) for k in sorted(s.allKeys()) if not k.startswith(self._VOLATILE)))

    def _prebuild_settings(self, delay=4000):
        t = getattr(self, "_prebuild_timer", None)
        if t is None:
            t = self._prebuild_timer = QTimer(self, singleShot=True, timeout=self._do_prebuild_settings)
        t.start(delay)

    def _do_prebuild_settings(self):
        if getattr(self, "_settings_dlg", None) is not None or getattr(self, "_settings_spare", None) is not None:
            return
        if self.wheel.is_open():
            self._prebuild_settings(15000)          # not while the wheel is up
            return
        try:
            dlg = SettingsDialog(self, lazy=True)   # page by page, so a playing video doesn't stop
        except Exception as e:
            winsys.log(f"settings prebuild: {e}")
            return
        self._settings_spare = (dlg, self._settings_snapshot(), i18n.language(), theme.mode())

    def show_settings(self):
        open_one = getattr(self, "_settings_dlg", None)
        if open_one is not None:                    # already open: bring it forward instead of a second one
            open_one.raise_()
            open_one.activateWindow()
            return
        spare, self._settings_spare = getattr(self, "_settings_spare", None), None
        dlg = None
        if spare is not None:
            if spare[1:] == (self._settings_snapshot(), i18n.language(), theme.mode()):
                dlg = spare[0]                      # built ahead of time, nothing changed since: shows at once
            else:
                spare[0].deleteLater()
        if dlg is None:
            dlg = SettingsDialog(self)
        dlg.setModal(False)                         # the wheel and floats keep working while Settings is open
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.finished.connect(lambda _r: setattr(self, "_settings_dlg", None))
        dlg.finished.connect(lambda _r: self._prebuild_settings())   # ready for next time
        self._settings_dlg = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def show_tour(self, parent=None):
        if parent is not None:                 # from Settings: on top of it, and usable while it's open
            TourDialog(self, parent).exec()
            return
        d = TourDialog(self)
        d.show()
        d.raise_()
        d.activateWindow()
        self._tour = d

    def show_help(self):
        k = {m: key_label(v) for m, v in mode_keys().items()}
        message(tr("{app} — How it works", app=APP), tr("HELP_HTML", app=APP, convert=k["convert"],
                                                         tool=k["tool"], action=k["action"])
                + "<br><br>" + tr("HELP_SCROLL"))


# ============================================================================
# Crash reports — off by default. When turned on, ConvertANNY shows the report and asks before anything is sent;
# sending opens a GitHub issue in your browser that you can read and edit first. Nothing is sent by itself.
# ============================================================================
def _crash_dir() -> Path:
    d = winsys.log_path().parent / "crash"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _anonymize(text: str) -> str:
    """Hide the Windows user name and home folder in a report."""
    import getpass
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    from convertanny_core.crash_reporting import anonymize_report
    return anonymize_report(text, home=str(Path.home()), username=user)


def crash_report_text(kind, details) -> str:
    import platform
    try:
        from PySide6 import __version__ as qt
    except Exception:
        qt = "?"
    tail = []
    try:                                                           # the last lines of the log help a lot
        tail = winsys.log_path().read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
    except OSError:
        pass
    import getpass
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    from convertanny_core.crash_reporting import compose_report
    return compose_report(app_version=VERSION, installed=getattr(sys, "frozen", False),
                          os_version=platform.version(), python_version=platform.python_version(), qt_version=qt,
                          language=settings().value("language", "") or "system", kind=kind, details=details,
                          log_lines=tail, home=str(Path.home()), username=user)


class CrashDialog(QDialog):
    """Shows exactly what a report contains, then lets you send it (on GitHub), copy it, or close."""

    def __init__(self, text):
        super().__init__(None, Qt.WindowStaysOnTopHint)
        self.text = text
        self.setWindowTitle(f"{APP} — " + tr("Something went wrong"))
        self.setWindowIcon(app_icon())
        self.setStyleSheet(i18n.css(DIALOG_CSS))
        self.resize(620, 460)
        lay = QVBoxLayout(self)
        head = QLabel("<b>" + tr("Something went wrong in ConvertANNY") + "</b><br>" +
                      tr("Sending this report helps fix it. This is everything it contains — your user name is hidden. "
                         "Send opens GitHub in your browser, where you can read it again and change it before posting."))
        head.setWordWrap(True)
        lay.addWidget(head)
        from PySide6.QtWidgets import QPlainTextEdit
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        box.setStyleSheet(f"background:{theme.hexc('surface')};color:{theme.hexc('text')};font:9pt Consolas")
        lay.addWidget(box, 1)
        row = QHBoxLayout()
        b = QPushButton(tr("Copy"))
        b.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text))
        row.addWidget(b)
        row.addStretch(1)
        b = QPushButton(tr("Don't send"))
        b.clicked.connect(self.reject)
        row.addWidget(b)
        send = QPushButton(tr("Send report"))
        send.setDefault(True)
        send.clicked.connect(self._send)
        row.addWidget(send)
        lay.addLayout(row)

    def _send(self):
        from urllib.parse import quote
        first = next((ln for ln in reversed(self.text.splitlines()) if "Error" in ln or "Exception" in ln), "Crash report")
        body = self.text if len(self.text) < 6000 else self.text[:6000] + "\n…"
        repo_url = updater.releases_url()
        if not repo_url:
            QMessageBox.information(self, tr("Crash report saved"),
                                    tr("The report is saved locally. Configure a ConvertANNY release repository in Preferences to open an online report."))
            self.accept()
            return
        repo_url = repo_url.removesuffix("/releases/latest")
        url = (f"{repo_url}/issues/new?title={quote('Crash: ' + first.strip()[:90])}"
               f"&labels=crash&body={quote('```\n' + body + '\n```')}")
        QDesktopServices.openUrl(QUrl(url))
        winsys.log("crash report: opened on GitHub")
        self.accept()


_CRASH_SEEN = set()
_CRASH_LOGGED = set()


def report_crash(kind, details):
    """Every crash goes to the log and the crash folder (once per kind of error per session); the report window
    only when crash reports are on."""
    key = (details.strip().splitlines()[-1] if details.strip() else kind) + "|" + \
        next((ln.strip() for ln in reversed(details.splitlines()) if ln.strip().startswith("File ")), "")
    if key in _CRASH_LOGGED:
        return
    _CRASH_LOGGED.add(key)
    text = crash_report_text(kind, details)
    import time
    try:
        (_crash_dir() / time.strftime("crash-%Y%m%d-%H%M%S.txt")).write_text(text, encoding="utf-8")
    except OSError:
        pass
    winsys.log(f"crash: {kind}: {details.strip().splitlines()[-1] if details.strip() else ''}")
    if settings().value("crash_reports", "false") != "true" or key in _CRASH_SEEN:
        return
    _CRASH_SEEN.add(key)
    app = QApplication.instance()
    if app is not None:
        QTimer.singleShot(0, lambda: CrashDialog(text).exec())


def install_crash_handlers():
    import faulthandler
    import threading as _th
    import traceback as _tb

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        report_crash(exc_type.__name__, "".join(_tb.format_exception(exc_type, exc, tb)))
    sys.excepthook = hook
    _th.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)
    # a hard crash (inside Qt or a library) can't be caught: faulthandler writes it down, and the next start offers it
    d = _crash_dir()
    native, running = d / "last-session.txt", d / "running"
    if running.exists() and native.exists() and native.stat().st_size > 0:
        QTimer.singleShot(3000, lambda t=native.read_text(encoding="utf-8", errors="replace"):
                          report_crash("ConvertANNY closed unexpectedly last time", t))
    running.write_text(str(os.getpid()), encoding="utf-8")
    global _FAULT_FILE
    _FAULT_FILE = open(native, "w", encoding="utf-8")
    faulthandler.enable(_FAULT_FILE, all_threads=True)


def crash_handlers_clean_exit():
    try:
        (_crash_dir() / "running").unlink(missing_ok=True)
    except OSError:
        pass


_FAULT_FILE = None


# ============================================================================
# Single instance
# ============================================================================
SERVER_NAME = f"convertanny-{getpass.getuser()}"


def send_to_running(args) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(400):
        return False
    sock.write(json.dumps(args).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def ask_running_to_close() -> int:
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(1000):
        return 0                                   # not running
    sock.write(json.dumps({"paths": [], "flags": ["--prepare-update"]}).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    reply = b""
    import time
    end = time.monotonic() + 15 * 60               # the user may take a while to answer the jobs warning
    while time.monotonic() < end and not reply:
        if sock.waitForReadyRead(500):
            reply = bytes(sock.readAll())
        elif sock.state() != QLocalSocket.ConnectedState:
            break
    if reply.startswith(b"no"):
        return 1
    # wait for ConvertANNY to finish closing (cancelled jobs clean up first)
    while time.monotonic() < end:
        probe = QLocalSocket()
        probe.connectToServer(SERVER_NAME)
        if not probe.waitForConnected(300):
            break
        probe.disconnectFromServer()
        time.sleep(0.4)
    return 0


def parse_args(argv):
    paths, flags = [], set()
    for a in argv:
        (flags.add(a) if a.startswith("--") else paths.append(a))
    return flags, paths


def selftest() -> int:
    """Diagnostics for the packaged app: runs a job in a worker process, then cancels one.
    Results go to the log file (%LOCALAPPDATA%\\ConvertANNY\\convertanny.log)."""
    import tempfile
    import time
    from convertanny_core.jobs import ConversionJob
    d = Path(tempfile.mkdtemp(prefix="convertanny-job-check-"))
    (d / "data").mkdir()
    (d / "data" / "a.txt").write_text("hello", encoding="utf-8")
    t0 = time.monotonic()
    res = ConversionJob("convert", "to_zip", [str(d / "data")], {}, None).run(lambda: False)
    winsys.log(f"selftest job: {res} in {time.monotonic() - t0:.1f}s")
    big = d / "big"
    big.mkdir()
    with open(big / "blob.bin", "wb") as fh:
        fh.write(os.urandom(80 * 1024 * 1024))
    start = time.monotonic()
    res = ConversionJob("convert", "to_7z", [str(big)], {}, None).run(lambda: time.monotonic() - start > 3)
    left = [p.name for p in d.iterdir()]
    winsys.log(f"selftest cancel: {res} after {time.monotonic() - start:.1f}s, folder={left}")
    try:                                     # PDF → Word (same look) works in the packaged app
        import pymupdf
        pdf = pymupdf.open()
        pg = pdf.new_page()
        pg.insert_text((72, 90), "Hello ConvertANNY", fontsize=14)
        pg.draw_rect(pymupdf.Rect(60, 60, 300, 110), color=(0, 0, 0))
        pdf.save(str(d / "letter.pdf"))
        pdf.close()
        res = ConversionJob("convert", "to_docx", [str(d / "letter.pdf")], {}, None).run(lambda: False)
        winsys.log(f"selftest pdf→docx: {res}")
    except Exception as e:
        winsys.log(f"selftest pdf→docx failed: {e}")
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    return 0


def main():
    global Wheel
    from orbit import OrbitWheel
    Wheel=OrbitWheel
    import multiprocessing
    multiprocessing.freeze_support()      # worker processes of the frozen exe start here and exit
    args = sys.argv[1:]
    if args and args[0] == "--cli":                  # convertanny.cmd
        args = args[1:] or ["help"]
    if args and args[0].lower() in ("convert", "tool", "list", "help", "/?", "-h"):
        import cli
        return cli.main(args)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ConvertANNY.App")
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setApplicationName(APP)
    qapp.setWindowIcon(app_icon())
    qapp.setFont(QFont(i18n.ui_font(), 9))
    _button_fix = ButtonPolish(qapp)
    qapp.installEventFilter(_button_fix)

    flags, paths = parse_args(sys.argv[1:])
    if "--selftest" in flags:
        return selftest()
    if "--prepare-update" in flags:            # run by the installer: 0 = go ahead, 1 = the user said not now
        return ask_running_to_close()
    if send_to_running({"paths": paths, "flags": sorted(flags)}):
        return 0

    i18n.set_language(settings().value("language", ""))
    theme.set_mode(settings().value("theme", "system"))
    sync_accent()
    qapp.setLayoutDirection(Qt.RightToLeft if i18n.is_rtl() else Qt.LeftToRight)
    qapp.setFont(QFont(i18n.ui_font(), 9))

    try:
        from PySide6 import __version__ as pyside_version
    except Exception:
        pyside_version = "?"
    winsys.log(f"start {APP} {VERSION} qt={pyside_version} frozen={getattr(sys, 'frozen', False)} "
               f"elevated={winsys.is_elevated()}")
    updater.cleanup(VERSION)          # the update installed fine: drop its downloaded installer
    try:
        winsys.ensure_cli_command()
    except Exception as e:
        winsys.log(f"cli command: {e}")
    try:
        if winsys.context_menu_enabled():
            winsys.set_context_menu(True, paste_label=tr("Save clipboard image here"), link_label=tr("Paste link to Float"),
                                    float_label=tr("Open Float"), qr_label=tr("Read QR code on screen"))
    except Exception as e:
        winsys.log(f"context menu refresh failed: {e}")

    try:
        install_crash_handlers()
        qapp.aboutToQuit.connect(crash_handlers_clean_exit)
    except Exception as e:
        winsys.log(f"crash handlers: {e}")

    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)
    app = ConvertANNYApp(qapp)

    def on_conn():
        sock = server.nextPendingConnection()

        def read():
            try:
                msg = json.loads(bytes(sock.readAll()).decode("utf-8") or "{}")
            except Exception:
                return
            if "--prepare-update" in msg.get("flags", []):
                ok = app.prepare_for_update()
                winsys.log(f"installer asked to close: {'ok' if ok else 'user said not now'}")
                sock.write(b"ok" if ok else b"no")
                sock.flush()
                sock.waitForBytesWritten(1000)
                if ok:
                    QTimer.singleShot(100, app.quit_for_update)
                return
            if "--open-float" in msg.get("flags", []):
                app.open_empty_float()
                return
            if "--play-link" in msg.get("flags", []):
                app.play_link()
                return
            if "--read-qr" in msg.get("flags", []):
                QTimer.singleShot(300, app.read_qr_on_screen)
                return
            if "--send-phone" in msg.get("flags", []) and msg.get("paths"):
                app.actions.phone(msg["paths"], {})
                return
            if "--paste-here" in msg.get("flags", []):
                app.save_clipboard_image((msg.get("paths") or [None])[0])
            elif msg.get("paths"):
                app.queue_paths(msg["paths"])
            elif "--tray" not in msg.get("flags", []):
                app.show_help()
        sock.readyRead.connect(read)
    server.newConnection.connect(on_conn)

    first_run = settings().value("first_run_done", "false") != "true"
    if first_run:
        settings().setValue("first_run_done", "true")
        if settings().value("installer", "") != "1":   # the installer already applied the user's choice
            try:
                winsys.set_context_menu(True, paste_label=tr("Save clipboard image here"), link_label=tr("Paste link to Float"),
                                    float_label=tr("Open Float"), qr_label=tr("Read QR code on screen"), sendto=True)
            except Exception:
                pass
        pass
    if (first_run or settings().value("tour_at_start", "true") == "true") and not paths and not (
            flags & {"--send-phone", "--play-link", "--paste-here", "--open-float", "--read-qr"}):
        QTimer.singleShot(600, app.show_tour)         # until "Don't show this again" is ticked
    if "--send-phone" in flags and paths:
        QTimer.singleShot(300, lambda: app.actions.phone(paths, {}))
    elif "--open-float" in flags:
        QTimer.singleShot(300, app.open_empty_float)
    elif "--play-link" in flags:
        QTimer.singleShot(400, app.play_link)
    elif "--read-qr" in flags:
        QTimer.singleShot(500, app.read_qr_on_screen)
    elif "--paste-here" in flags:
        QTimer.singleShot(300, lambda: app.save_clipboard_image(paths[0] if paths else None))
    elif paths:
        app.queue_paths(paths)
    elif "--tray" not in flags and not first_run:
        app.tray.showMessage(APP, tr("Running in the tray. Drag a file and shake the mouse.") if mode_keys()["convert"] == "None"
                             else tr("Running in the tray. Drag a file and tap {key}.", key=key_label(mode_keys()["convert"])),
                             app_icon(), 3000)
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
