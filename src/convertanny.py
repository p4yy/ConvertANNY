"""Frozen executable entry point; worker dispatch happens before Qt initialization."""
# Copyright 2026 Ace App Co. SPDX-License-Identifier: AGPL-3.0-only
import multiprocessing
import sys

def main():
    multiprocessing.freeze_support()
    if '--verify' in sys.argv:
        from verification import run
        index=sys.argv.index('--verify')
        return run(sys.argv[index+1])
    if len(sys.argv)>1 and sys.argv[1] in ('--cli','convert','tool','list','help','-h','--help','/?'):
        import cli
        return cli.main(sys.argv[2:] or ['help']) if sys.argv[1]=='--cli' else cli.main(sys.argv[1:])
    import json, os
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtNetwork import QLocalServer
    import runtime as rt
    import design, theme
    from orbit import OrbitWheel
    from preferences import Preferences
    from workspace import Controller
    design.install();rt.Wheel=OrbitWheel;rt.SettingsDialog=Preferences;rt.DIALOG_CSS=design.CSS;rt.SETTINGS_CSS=''
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp=QApplication(sys.argv);qapp.setStyle('Fusion');qapp.setQuitOnLastWindowClosed(False)
    qapp.setApplicationName('ConvertANNY');qapp.setOrganizationName('ConvertANNY');qapp.setWindowIcon(rt.app_icon())
    s=rt.settings()
    if not s.contains('onboarding/initialized'):
        s.setValue('tour_at_start','true');s.setValue('onboarding/initialized','true')
    for key,value in {'theme':'dark','check_updates':'false','tour_at_start':'true','tick_volume':35,'sound_pack':'soft'}.items():
        if not s.contains(key):s.setValue(key,value)
    rt.i18n.set_language(s.value('language',''));theme.set_mode(s.value('theme','dark'));rt.sync_accent()
    import typography
    typography.install(qapp)
    qapp.setPalette(design.palette());qapp.setStyleSheet(design.css())
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ConvertANNY.Desktop')
    flags,paths=rt.parse_args(sys.argv[1:])
    if rt.send_to_running({'flags':sorted(flags),'paths':paths}):return 0
    QLocalServer.removeServer(rt.SERVER_NAME);server=QLocalServer();server.listen(rt.SERVER_NAME)
    app=Controller(qapp)
    rt.install_crash_handlers();qapp.aboutToQuit.connect(rt.crash_handlers_clean_exit)
    def dispatch(flags,paths):
        if '--open-float' in flags:app.open_empty_float()
        elif '--play-link' in flags:app.play_link()
        elif '--read-qr' in flags:app.read_qr_on_screen()
        elif '--paste-here' in flags:app.save_clipboard_image(paths[0] if paths else None)
        elif '--send-phone' in flags and paths:app.actions.phone(paths,{})
        elif paths:app.wheel.popup('convert',paths,click_mode=True)
        elif '--tray' not in flags:app.show_home()
    def connection():
        sock=server.nextPendingConnection();buffer=bytearray()
        def read():
            buffer.extend(bytes(sock.readAll()))
            try:msg=json.loads(buffer.decode('utf-8'))
            except (ValueError,UnicodeDecodeError):return
            if '--prepare-update' in msg.get('flags',[]):
                ok=app.prepare_for_update();sock.write(b'ok' if ok else b'no');sock.flush()
                if ok:QTimer.singleShot(100,app.quit_for_update)
            else:dispatch(msg.get('flags',[]),msg.get('paths',[]))
        sock.readyRead.connect(read)
        if sock.bytesAvailable():read()
    server.newConnection.connect(connection)
    QTimer.singleShot(0,lambda:dispatch(flags,paths))
    if not flags and not paths and s.value('tour_at_start','true')=='true':
        QTimer.singleShot(400,app.show_tour)
    qapp.aboutToQuit.connect(lambda:s.sync())
    return qapp.exec()

if __name__=='__main__':
    sys.exit(main())
