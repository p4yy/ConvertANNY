"""ConvertANNY's shared visual system. No runtime dependency on web rendering."""
import theme

def install():
    theme.DARK.update(bg='#101010', surface='#181818', border='#303030', button='#242424', hover='#303030',
                      text='#f2f2f2', dim='#a1a1a1', faint='#808080', side='#141414', canvas='#0b0b0b',
                      accent='#2563eb', accent2='#3b82f6', on_accent='#ffffff', link='#60a5fa')
    theme.LIGHT.update(bg='#f5f7f3', surface='#ffffff', border='#dce4df', button='#edf2ee', hover='#e0ebe4',
                       text='#18352f', dim='#637a71', faint='#73877e', side='#eef3ee', canvas='#e8eeea',
                       accent='#2563eb', accent2='#3b82f6', on_accent='#ffffff', link='#2563eb')
    theme.DARK_RGBA.update(panel=(20,20,20,252), ring=(28,28,28,255), ring_hover=(42,42,42,255), line=(255,255,255,35))
    theme.LIGHT_RGBA.update(panel=(245,247,243,252), ring=(255,255,255,255), ring_hover=(224,235,228,255), line=(25,125,104,45))
    theme.NAMES[:] = [('system','System'),('light','Light'),('dark','Dark'),('contrast','High contrast')]

CSS = '''
QWidget { font-family: 'ConvertANNY UI'; font-size: 14px; font-weight: 400; color: $text; }
QDialog, QMainWindow, QWidget#workspace, QWidget#page { background: $bg; }
QLabel { background: transparent; }
QLabel#eyebrow { color: $accent; font-size: 11px; font-weight: 700; letter-spacing: 0px; }
QLabel#hero { font-size: 22px; font-weight: 600; }
QLabel#pagetitle { font-size: 18px; font-weight: 600; padding: 8px 0; }
QLabel#pagesub, QLabel#dim, QLabel#muted { color: $dim; }
QLabel#pagesub { padding-bottom: 20px; }
QPushButton { background: $button; border: 1px solid transparent; border-radius: 9px; padding: 10px 17px; font-weight: 500; }
QPushButton:hover { background: $hover; border-color: $border; }
QPushButton:pressed { border-color: $accent; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus { border: 1px solid $accent; }
QPushButton:disabled { color: $faint; background: $side; }
QPushButton#primary, QPushButton:default { background: $accent; color: $on_accent; }
QPushButton#primary:hover { background: $accent2; }
QPushButton#nav { background: transparent; color: $dim; padding: 12px 16px; }
QPushButton#nav:checked { background: $surface; color: $text; border: 1px solid $border; }
QPushButton#action { text-align: left; background: $surface; border: 1px solid $border; padding: 15px; border-radius: 12px; }
QPushButton#action:hover { border-color: $accent; background: $hover; }
QFrame#card { background: $surface; border: 1px solid $border; border-radius: 10px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 9px; selection-background-color: $accent; }
QComboBox::drop-down { border: none; width: 25px; }
QComboBox QAbstractItemView { background: $surface; selection-background-color: $hover; }
QGroupBox { border: 1px solid $border; border-radius: 12px; margin-top: 27px; padding: 20px 14px 14px; background: $surface; }
QGroupBox::title { subcontrol-origin: margin; left: 4px; padding: 0 8px 5px; font-weight: 600; }
QListWidget { background: $surface; border: 1px solid $border; border-radius: 12px; padding: 8px; outline: none; }
QListWidget::item { padding: 12px; border-radius: 7px; }
QListWidget::item:selected { background: $hover; color: $text; }
QListWidget#nav { background: transparent; border: none; padding: 0; }
QListWidget#nav::item { padding: 12px 14px; margin-right: 5px; color: $dim; }
QListWidget#nav::item:selected { background: $surface; color: $text; border: 1px solid $border; }
QScrollArea, QStackedWidget { background: transparent; border: none; }
QWidget#operationList { background: $bg; }
QScrollBar:vertical { width: 7px; background: transparent; margin: 0; }
QScrollBar::handle:vertical { background: $border; min-height: 25px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QMenu { background: $surface; border: 1px solid $border; padding: 6px; }
QMenu::item { padding: 9px 24px; border-radius: 5px; }
QMenu::item:selected { background: $hover; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 6px; }
QSlider::groove:horizontal { height: 4px; background: $border; border-radius: 2px; }
QSlider::handle:horizontal { background: $accent; width: 15px; margin: -6px 0; border-radius: 7px; }
QProgressBar { background: $side; border: none; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
'''

def css():
    return theme.sheet(CSS)

def palette():
    from PySide6.QtGui import QPalette
    p=QPalette()
    for role,token in [(QPalette.Window,'bg'),(QPalette.WindowText,'text'),(QPalette.Base,'surface'),
                       (QPalette.AlternateBase,'side'),(QPalette.Text,'text'),(QPalette.Button,'button'),
                       (QPalette.ButtonText,'text'),(QPalette.Highlight,'accent'),(QPalette.HighlightedText,'on_accent'),
                       (QPalette.ToolTipBase,'surface'),(QPalette.ToolTipText,'text'),(QPalette.Link,'link')]:
        p.setColor(role,theme.color(token))
    for role in [QPalette.Text,QPalette.WindowText,QPalette.ButtonText]:p.setColor(QPalette.Disabled,role,theme.color('faint'))
    return p
