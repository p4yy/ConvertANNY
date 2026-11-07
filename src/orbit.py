"""Detached annular segments. Shares the tested input/drag dispatch with runtime."""
import math
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPainterPath, QPen, QFont, QFontMetrics
import runtime as rt
import theme


def _label_layout(label, width, height):
    """Choose a readable size that fits the wedge; elide only as a last resort."""
    flags = Qt.AlignCenter | Qt.TextWordWrap
    for points in (10, 9, 8, 7):
        font = QFont('ConvertANNY UI', points, QFont.DemiBold)
        metrics = QFontMetrics(font)
        bounds = metrics.boundingRect(0, 0, round(width), round(height), flags, label)
        if bounds.height() <= height:
            return label, font
    font = QFont('ConvertANNY UI', 7, QFont.DemiBold)
    metrics = QFontMetrics(font)
    low, high, best = 0, len(label), ''
    while low < high:
        middle = (low + high + 1) // 2
        prefix = label[:middle]
        if middle < len(label) and ' ' in prefix:
            prefix = prefix.rsplit(' ', 1)[0]
        candidate = prefix.rstrip(' .…') + '…'
        bounds = metrics.boundingRect(0, 0, round(width), round(height), flags, candidate)
        if bounds.height() <= height:
            low, best = middle, candidate
        else:
            high = middle - 1
    return best or metrics.elidedText(label, Qt.ElideRight, round(width)), font

class OrbitWheel(rt.Wheel):
    R_IN = 74
    R_OUT = 306
    PAD = 20

    @staticmethod
    def segment(c, inner, outer, start, span):
        path = QPainterPath()
        a = math.radians(start)
        path.moveTo(c.x()+outer*math.cos(a), c.y()-outer*math.sin(a))
        path.arcTo(QRectF(c.x()-outer,c.y()-outer,2*outer,2*outer),start,span)
        a = math.radians(start+span)
        path.lineTo(c.x()+inner*math.cos(a), c.y()-inner*math.sin(a))
        path.arcTo(QRectF(c.x()-inner,c.y()-inner,2*inner,2*inner),start+span,-span)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.center()
        t = max(0., min(1., self._t))
        p.setOpacity(t)
        p.translate(c)
        p.scale(.92+.08*t, .92+.08*t)
        p.translate(-c)
        idx = self.page * self.PAGE_SIZE
        for inner, outer, ops in self._rings():
            if not ops:
                continue
            step = 360/len(ops)
            for j, op in enumerate(ops):
                selected = idx == self.hover
                path = self.segment(c, inner, outer, 90-j*step+step/2-1.4, -step+2.8)
                p.setBrush(theme.color('accent') if selected else theme.color('panel'))
                p.setPen(QPen(theme.color('accent') if selected else theme.color('border'), 1.2))
                p.drawPath(path)
                a = math.radians(j*step)
                x,y = c.x()+math.sin(a)*(inner+outer)/2, c.y()-math.cos(a)*(inner+outer)/2
                ink = theme.color('on_accent') if selected else theme.color('text')
                p.setPen(ink)
                arc_width = min(176, (inner+outer)/2*math.radians(step)*.88)
                dy = abs(y-c.y())
                outer_half = math.sqrt(max(0., outer*outer-dy*dy))
                inner_half = math.sqrt(max(0., inner*inner-dy*dy)) if dy < inner else 0.
                radial_width = max(48., (outer_half-inner_half if dy < inner else 2*outer_half)-12)
                width = min(arc_width, radial_width)
                label = rt.tr(op.label).rstrip('…')
                font = QFont('ConvertANNY UI', 10, QFont.DemiBold)
                text_box = QRectF(x-width/2,y-38,width,76)
                label, font = _label_layout(label, text_box.width(), text_box.height())
                p.setFont(font)
                p.drawText(text_box,Qt.AlignCenter|Qt.TextWordWrap,label)
                idx += 1
        p.setBrush(theme.color('ring'))
        p.setPen(QPen(theme.color('border'),1))
        p.drawEllipse(c,66,66)
        icon=rt.app_icon().pixmap(30,30)
        p.drawPixmap(int(c.x()-15),int(c.y()-42),icon)
        p.setPen(theme.color('text'))
        p.setFont(QFont('ConvertANNY UI',10,QFont.DemiBold))
        p.drawText(QRectF(c.x()-65,c.y()-8,130,26),Qt.AlignCenter,rt.tr(rt.MODE_LABEL[self.mode]))
        p.setFont(QFont('ConvertANNY UI',9))
        p.setPen(theme.color('dim'))
        detail = f'{len(self.paths)} files' if len(self.paths)>1 else (rt.engine.category_of(self.paths).title() if self.paths else 'Drop a file')
        p.drawText(QRectF(c.x()-60,c.y()+16,120,23),Qt.AlignCenter,detail)
        p.setFont(QFont('ConvertANNY UI',8))
        if self.page_count()>1:
            p.drawText(QRectF(c.x()-24,c.y()+36,48,20),Qt.AlignCenter,f'{self.page+1}/{self.page_count()}')
            for step,rect in self._page_rects().items():
                p.drawText(rect,Qt.AlignCenter,'‹' if step<0 else '›')
        else:
            p.drawText(QRectF(c.x()-60,c.y()+38,120,19),Qt.AlignCenter,'Esc to close')
        for mode, rect in self._pill_rects().items():
            active = mode == self.mode
            p.setBrush(theme.color('accent') if active else theme.color('panel'))
            p.setPen(QPen(theme.color('border'),1))
            p.drawRoundedRect(rect,12,12)
            p.setPen(theme.color('on_accent') if active else theme.color('text'))
            p.setFont(QFont('ConvertANNY UI',9,QFont.DemiBold))
            p.drawText(rect,Qt.AlignCenter,rt.tr(rt.MODE_LABEL[mode]))
        p.end()
