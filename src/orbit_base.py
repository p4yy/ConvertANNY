"""ConvertANNY orbit input, geometry and action dispatch."""
import math
from PySide6.QtCore import Qt,QPointF,QRectF,QTimer,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QCursor,QGuiApplication
from PySide6.QtWidgets import QWidget


def _runtime():
    import runtime
    return runtime


class Wheel(QWidget):
    R_IN=74;R_OUT=306;PAD=20;PILL_H=40;PAGE_SIZE=12
    def __init__(self,app):
        super().__init__(None,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint)
        self.app=app;self.setAttribute(Qt.WA_TranslucentBackground);self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True);self.setMouseTracking(True)
        self.paths=[];self.ops=[];self.mode='convert';self.hover=-1;self.hover_pill=None
        self.page=0;self.click_mode=False;self.dropped=False;self.scroll_active=False;self.scroll_anchor=None
        self._t=1.;self._closing=False;self._style='circle';self._anchor=None
        self.t_anim=QVariantAnimation(self);self.t_anim.valueChanged.connect(self._frame);self.t_anim.finished.connect(self._animated)
        self.pill_timer=QTimer(self);self.pill_timer.setSingleShot(True);self.pill_timer.setInterval(380);self.pill_timer.timeout.connect(self._pill_dwell)
        side=2*(self.R_OUT+self.PAD);self.setFixedSize(side,side+self.PILL_H+12)
    def _frame(self,value):self._t=float(value);self.update()
    def _animated(self):
        if self._closing:self._finish_hide()
    def _animate(self,target):
        self.t_anim.stop();speed=max(.1,float(_runtime().anim_speed()))
        self.t_anim.setDuration(max(40,round((190 if target else 180)/speed)))
        self.t_anim.setEasingCurve(QEasingCurve.OutCubic if target else QEasingCurve.InCubic)
        self.t_anim.setStartValue(self._t);self.t_anim.setEndValue(float(target));self.t_anim.start()
    def center(self):return QPointF(self.width()/2,self.R_OUT+self.PAD)
    def page_count(self):return max(1,math.ceil(len(self.ops)/self.PAGE_SIZE))
    def _rings(self):
        visible=self.ops[self.page*self.PAGE_SIZE:(self.page+1)*self.PAGE_SIZE]
        if len(visible)<=6:return [(80,202,visible)]
        count=math.ceil(len(visible)/2)
        return [(80,188,visible[:count]),(196,306,visible[count:])]
    def _outer(self):return self._rings()[-1][1]
    def _pill_rects(self):
        left=(self.width()-340)/2;y=self.center().y()+self._outer()+14
        return {mode:QRectF(left+index*116,y,108,40) for index,mode in enumerate(('convert','tool','action'))}
    def _page_rects(self):
        center=self.center()
        return {-1:QRectF(center.x()-51,center.y()+34,28,24),1:QRectF(center.x()+23,center.y()+34,28,24)}
    def change_page(self,step):
        self.page=(self.page+step)%self.page_count();self.hover=-1;self.scroll_active=False;self.update()
    def hit(self,position):
        for mode,rectangle in self._pill_rects().items():
            if rectangle.contains(position):return 'pill',mode
        if self.page_count()>1:
            for step,rectangle in self._page_rects().items():
                if rectangle.contains(position):return 'page',step
        point=position-self.center();distance=math.hypot(point.x(),point.y())
        if distance<74:return 'center',None
        angle=math.degrees(math.atan2(point.x(),-point.y()))%360;offset=self.page*self.PAGE_SIZE
        for inner,outer,items in self._rings():
            if inner<=distance<=outer and items:
                increment=360/len(items);relative=(angle+increment/2)%360
                # The small visual gap between segments is not an action target.
                nearest=int(relative/increment)
                if min(relative%increment,increment-relative%increment)<1.4:return None,None
                return 'item',offset+nearest
            offset+=len(items)
        return None,None
    def set_mode(self,mode):
        if mode not in ('convert','tool','action'):return
        self.mode=mode;self.ops=list(self.app.ops_for(mode,self.paths)) if self.paths else []
        self.page=0;self.hover=-1;self.scroll_active=False;self.update()
        if self.isVisible():self._keep_on_screen()
    def set_paths(self,paths):self.paths=list(paths);self.set_mode(self.mode)
    def _keep_on_screen(self):
        anchor=self._anchor or QCursor.pos();screen=QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        if screen is None:return
        bounds=screen.availableGeometry();center=self.center();outer=self._outer()+18
        x=anchor.x()-center.x();y=anchor.y()-center.y()
        left=center.x()-outer;right=center.x()+outer;bottom=max(rect.bottom() for rect in self._pill_rects().values())+6
        x=max(bounds.left()-left,min(x,bounds.right()-right));y=max(bounds.top()-(center.y()-outer),min(y,bounds.bottom()-bottom))
        self.move(round(x),round(y))
    def popup(self,mode,paths=None,click_mode=False,at=None):
        runtime=_runtime()
        if not self.is_open():runtime.play_wheel_sound('open')
        self.t_anim.stop();self._closing=False;self.click_mode=click_mode;self.dropped=False;self.scroll_active=False
        self._anchor=at or QCursor.pos();self.paths=list(paths or []);self.set_mode(mode)
        self._style=runtime.wheel_anim();self._t=1. if self._style=='none' else 0.
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus,not click_mode);self._keep_on_screen();self.show()
        if click_mode:self.activateWindow();self.setFocus();self.begin_anim()
        elif self._style!='none':QTimer.singleShot(400,self.begin_anim)
    def begin_anim(self):
        if self.is_open() and self._style!='none' and self._t<1 and self.t_anim.state()!=QVariantAnimation.Running:self._animate(1)
    def dismiss(self):
        self.pill_timer.stop()
        if not self.is_open():return
        runtime=_runtime();runtime.play_wheel_sound('close');self._style=runtime.wheel_anim_close()
        if self._style=='none':self._finish_hide()
        else:self._closing=True;self._animate(0)
    def is_open(self):return self.isVisible() and not self._closing
    def _finish_hide(self):
        self.t_anim.stop();self.hide();self._closing=False;self._t=1.;self.paths=[];self.ops=[];self.hover=-1
    def _paths_from(self,mime):return [url.toLocalFile() for url in mime.urls() if url.isLocalFile() and url.toLocalFile()]
    def dragEnterEvent(self,event):
        paths=self._paths_from(event.mimeData())
        if self._closing or not paths:event.ignore();return
        if paths!=self.paths:self.set_paths(paths)
        event.setDropAction(Qt.CopyAction);event.accept();self._track(event.position())
    def dragMoveEvent(self,event):
        kind=self._track(event.position())
        if kind=='item':event.setDropAction(Qt.CopyAction);event.accept()
        else:event.ignore()
    def dragLeaveEvent(self,event):self.hover=-1;self.hover_pill=None;self.pill_timer.stop();self.update()
    def _execute(self,index,paths=None):
        if not 0<=index<len(self.ops):return
        operation=self.ops[index];selection=list(paths or self.paths);self.dismiss()
        QTimer.singleShot(0,lambda:self.app.execute(operation,selection))
    def dropEvent(self,event):
        self.dropped=True;kind,value=self.hit(event.position())
        if self.scroll_active and self.hover>=0:kind,value='item',self.hover
        paths=self._paths_from(event.mimeData()) or self.paths;event.setDropAction(Qt.CopyAction);event.accept()
        if kind=='item':self._execute(value,paths)
        else:self.dismiss()
    def scroll_step(self,step):
        if not self.ops:return
        self.hover=((self.hover+step)%len(self.ops)) if self.hover>=0 else (0 if step>0 else len(self.ops)-1)
        self.page=self.hover//self.PAGE_SIZE;self.scroll_active=True;self.scroll_anchor=self.hit(QPointF(self.mapFromGlobal(QCursor.pos())))
        _runtime().play_tick();self._announce();self.update()
    def wheelEvent(self,event):self.scroll_step(1 if event.angleDelta().y()<0 else -1)
    def _announce(self):
        runtime=_runtime();label=runtime.tr(self.ops[self.hover].label) if 0<=self.hover<len(self.ops) else runtime.tr(runtime.MODE_LABEL[self.mode])
        self.setAccessibleName('ConvertANNY · '+label)
    def _track(self,position):
        kind,value=self.hit(position)
        if self.scroll_active and ((kind,value)==self.scroll_anchor or kind=='center'):return 'item'
        self.scroll_active=False;pill=value if kind=='pill' else None
        if pill!=self.hover_pill:
            self.hover_pill=pill;self.pill_timer.stop()
            if pill and pill!=self.mode:self.pill_timer.start()
        hover=value if kind=='item' else -2 if kind=='center' else -1
        if hover!=self.hover:
            self.hover=hover
            if hover>=0:_runtime().play_tick()
            self._announce();self.update()
        return kind
    def _pill_dwell(self):
        if self.hover_pill:self.set_mode(self.hover_pill)
    def mouseMoveEvent(self,event):self._track(event.position())
    def mousePressEvent(self,event):
        if self._closing:return
        kind,value=self.hit(event.position())
        if kind=='pill':self.set_mode(value)
        elif kind=='page':self.change_page(value)
        elif kind=='item':self._execute(value)
        else:self.dismiss()
    def keyPressEvent(self,event):
        key=event.key();runtime=_runtime()
        if key==Qt.Key_Escape:self.dismiss()
        elif key in (Qt.Key_Left,Qt.Key_Up,Qt.Key_Right,Qt.Key_Down):self.scroll_step(-1 if key in (Qt.Key_Left,Qt.Key_Up) else 1)
        elif key in (Qt.Key_PageDown,Qt.Key_PageUp):self.change_page(1 if key==Qt.Key_PageDown else -1)
        elif key in (Qt.Key_Tab,Qt.Key_Backtab):
            modes=['convert','tool','action'];self.set_mode(modes[(modes.index(self.mode)+(1 if key==Qt.Key_Tab else -1))%3])
        elif key in (Qt.Key_Return,Qt.Key_Enter):self._execute(self.hover)
        else:
            name=runtime.qt_key_name(key)
            for mode,combo in runtime.mode_keys().items():
                keys=runtime.winsys.combo_vks(combo)
                if name and name in combo.split('+') and keys and all(runtime.winsys.key_down(code) for code in keys):
                    self.dismiss() if mode==self.mode else self.set_mode(mode);break
    def focusOutEvent(self,event):
        if self.click_mode:QTimer.singleShot(120,lambda:self.dismiss() if not self.isActiveWindow() else None)
