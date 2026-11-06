"""ConvertANNY preferences, settings persistence and customization entry points."""
from __future__ import annotations
import json,re
from pathlib import Path
from PySide6.QtCore import Qt,QSize,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QGroupBox,QLabel,
 QListWidget,QListWidgetItem,QListView,QStackedWidget,QScrollArea,QPushButton,QLineEdit,QComboBox,
 QSlider,QDialogButtonBox,QFileDialog,QMessageBox)
import design,theme,icons,i18n
from i18n import tr
from settings_controls import SwitchBox,KeyCapture


class Preferences(QDialog):
    def __init__(self,app,lazy=False):
        super().__init__();import runtime
        self.rt=runtime;self.app=app;self.s=runtime.settings();self.orig_theme=theme.mode();self.orig_lang=self.s.value('language','')
        self._switches={};self._choices={};self._numbers={};self._readers={};self._saved=False
        self._original_taskbar=self.s.value('float_taskbar','true')=='true'
        self.setWindowTitle('ConvertANNY · Preferences');self.setWindowIcon(runtime.app_icon());self.setStyleSheet(design.css());self.resize(1080,800)
        root=QVBoxLayout(self);root.setContentsMargins(28,20,28,20)
        title=QLabel(tr('Preferences'));title.setObjectName('hero');root.addWidget(title)
        self.nav=QListWidget();self.nav.setObjectName('nav');self.nav.setFlow(QListView.LeftToRight);self.nav.setWrapping(False);self.nav.setFixedHeight(60)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded);self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.nav.setIconSize(QSize(18,18))
        root.addWidget(self.nav);self.stack=QStackedWidget();root.addWidget(self.stack,1);self.tabs=self.nav
        self.pages=[]
        for name,icon in [('General','general'),('Wheel','wheel'),('Sound','sound'),('Files & jobs','files'),('Player','player'),('Customize','customize'),('Advanced','advanced'),('About','about')]:
            item=QListWidgetItem(icons.icon(icon),tr(name));item.setSizeHint(QSize(125 if name in ('Files & jobs','Customize','Advanced') else 110,48));self.nav.addItem(item)
            page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(4,4,8,8);layout.setSpacing(10)
            heading=QLabel(tr(name));heading.setObjectName('pagetitle');layout.addWidget(heading);self.pages.append(layout)
            area=QScrollArea();area.setWidgetResizable(True);area.setWidget(page);area.setFrameShape(QScrollArea.NoFrame);self.stack.addWidget(area)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self._general();self._wheel();self._sound();self._files();self._player();self._customize();self._advanced();self._about()
        for layout in self.pages:layout.addStretch()
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);root.addWidget(buttons);self.nav.setCurrentRow(0)

    def _group(self,page,title):
        group=QGroupBox(tr(title));layout=QVBoxLayout(group);self.pages[page].addWidget(group);return layout
    def _switch(self,layout,attribute,key,label,default=True,initial=None):
        control=SwitchBox(tr(label));control.setChecked(self.s.value(key,'true' if default else 'false')=='true' if initial is None else initial)
        layout.addWidget(control);setattr(self,attribute,control);self._switches[key]=control;return control
    def _choice(self,layout,attribute,key,label,values,default):
        control=QComboBox()
        for value,text in values:control.addItem(tr(text),value)
        control.setCurrentIndex(max(0,control.findData(self.s.value(key,default))));row=QHBoxLayout();row.addWidget(QLabel(tr(label)));row.addWidget(control,1);layout.addLayout(row)
        setattr(self,attribute,control);self._choices[key]=control;return control
    def _slider(self,layout,attribute,key,label,minimum,maximum,default):
        row=QHBoxLayout();row.addWidget(QLabel(tr(label)));control=QSlider(Qt.Horizontal);control.setRange(minimum,maximum)
        try:value=int(self.s.value(key,default))
        except (TypeError,ValueError):value=default
        control.setValue(value);number=QLabel(str(control.value()));control.valueChanged.connect(lambda value:number.setText(str(value)))
        row.addWidget(control,1);row.addWidget(number);layout.addLayout(row);setattr(self,attribute,control);self._numbers[key]=control;return control
    def _button(self,layout,label,callback):
        button=QPushButton(tr(label));button.clicked.connect(lambda checked=False:callback());layout.addWidget(button);return button
    def _general(self):
        layout=self._group(0,'Appearance')
        self._choice(layout,'lang','language','App language',[('', 'System default'),*i18n.LANGUAGES],'')
        self._choice(layout,'theme_box','theme','Theme',theme.NAMES,'dark')
        self.theme_box.currentIndexChanged.connect(self._theme_preview)
        layout=self._group(0,'Startup');self._switch(layout,'startup','startup','Start ConvertANNY when I sign in',initial=self.rt.winsys.startup_enabled())
        layout=self._group(0,'Right-click menu');self._switch(layout,'menu','menu','Add ConvertANNY to the context menu',initial=self.rt.winsys.context_menu_enabled())
        self._switch(layout,'sendto','sendto','Add ConvertANNY to Send To',initial=self.rt.winsys.sendto_enabled());self.full_menu=None
        if self.rt.winsys.windows_11():
            self.full_menu=self._switch(layout,'full_menu','full_menu','Use the full right-click menu (like Windows 10)',initial=self.rt.winsys.full_menu_enabled())
    def _wheel(self):
        layout=self._group(1,'Wheel keys');self.key_boxes={}
        for mode,label in [('convert','Convert'),('tool','Tools'),('action','Actions'),('peek','File preview')]:
            row=QHBoxLayout();row.addWidget(QLabel(tr(label)));capture=KeyCapture(self.s.value('keys/'+mode,{'convert':'Shift','tool':'Ctrl','action':'Alt','peek':'Space'}[mode]))
            self.key_boxes[mode]=capture;row.addWidget(capture,1);button=QPushButton(tr('None'));button.clicked.connect(lambda checked=False,capture=capture:capture.set_spec('None'));row.addWidget(button);layout.addLayout(row)
        self._choice(layout,'peek_hold','peek_hold','File preview opens',[('false','Press to open, press again to close'),('true','Hold to show, let go to close')],'false')
        self._choice(layout,'detect','trigger_mode','Trigger on',[('drag','File drag'),('hover','Mouse hover'),('select','File selection')],'drag')
        layout=self._group(1,'Mouse Control');modes=[('convert','Convert'),('tool','Tools'),('action','Actions'),('peek','File preview')]
        for attribute,key,label in [('shake','shake','Mouse Shake'),('scroll','scroll','Scroll Wheel')]:
            switch=self._switch(layout,attribute,key,label);choice=self._choice(layout,attribute+'_opens',key+'_opens','Opens',modes,'convert');choice.setEnabled(switch.isChecked());switch.toggled.connect(choice.setEnabled)
        self._switch(layout,'cursor_busy','cursor_busy','Loading Spin')
        layout=self._group(1,'Animations');self._choice(layout,'anim','wheel_anim','Opening',self.rt.WHEEL_ANIMS,'circle');self._switch(layout,'anim_same','anim_same','Same style for opening and closing')
        self._choice(layout,'anim_close','wheel_anim_close','Closing',self.rt.WHEEL_ANIMS,'circle');self.anim_close.setEnabled(not self.anim_same.isChecked());self.anim_same.toggled.connect(lambda value:self.anim_close.setEnabled(not value))
        self._slider(layout,'anim_speed','anim_speed','Speed (%)',25,250,100)
    def _sound(self):
        layout=self._group(2,'When a job finishes');self._switch(layout,'finish_anim','finish_anim','Animate the tick on the notification');self._switch(layout,'finish_sound','finish_sound','Enable notification sound')
        self._switch(layout,'tick_sound','tick_sound','Enable wheel sound');self._slider(layout,'tick_volume','tick_volume','Volume',0,100,35)
        self._choice(layout,'sound_pack','sound_pack','Sound style',self.rt.SOUND_PACKS,'soft')
        self._button(layout,'Listen',lambda:self.rt._play_wav('tick',self.tick_volume.value(),self.sound_pack.currentData()))
    def _files(self):
        layout=self._group(3,'Output');self._choice(layout,'out_mode','output_mode','Results go',[('next','Next to the original file'),('folder','In this folder'),('replace','Replace the original (asks first)'),('clipboard','Copy to the clipboard')],'next')
        self.out=QLineEdit(str(self.s.value('output_dir','')));row=QHBoxLayout();row.addWidget(self.out,1);button=QPushButton(tr('Browse…'));button.clicked.connect(lambda:self.out.setText(QFileDialog.getExistingDirectory(self,tr('Output folder')) or self.out.text()));row.addWidget(button);layout.addLayout(row)
        self.out.setEnabled(self.out_mode.currentData()=='folder');self.out_mode.currentIndexChanged.connect(lambda:self.out.setEnabled(self.out_mode.currentData()=='folder'))
        layout=self._group(3,'Jobs');self._choice(layout,'job_mode','job_mode','Several jobs',[('queue','One after another (a queue)'),('parallel','All at the same time')],'queue')
        layout=self._group(3,'Auto Convert');self.watch_list=QListWidget();self.watch_list.setMaximumHeight(140);layout.addWidget(self.watch_list)
        self._button(layout,'Add…',self._add_watch);self._button(layout,'Remove',self._remove_watch);self._fill_watch()
    def _player(self):
        layout=self._group(4,'Player')
        for attribute,key,label,default in [('autoplay','float_autoplay','Play files and links instantly',True),('on_top','float_on_top','Always on top',True),('ctrl_open','float_ctrl_open','Ctrl+Enter opens a file in Float',True),('link_stops','float_link_stops','Stop playing while loading',True),('taskbar','float_taskbar','Show in taskbar',True),('icon_only','float_icon_only','Remove float border',True),('hide_name','float_hide_name','Hide name',False),('media_osd','media_osd','Enable multimedia logos on screen',True)]:self._switch(layout,attribute,key,label,default)
        self._choice(layout,'media_osd_when','media_osd_when','Show controls',[('unfocused',"Only when the float isn't in focus"),('always','All the time')],'unfocused')
        self.hide_name.setEnabled(self.icon_only.isChecked());self.icon_only.toggled.connect(self.hide_name.setEnabled)
        self.media_osd_when.setEnabled(self.media_osd.isChecked());self.media_osd.toggled.connect(self.media_osd_when.setEnabled)
    def _customize(self):
        layout=self._group(5,'Wheel slices');self._button(layout,'Choose slices…',lambda:self.rt.WheelLayoutDialog(self).exec())
        layout=self._group(5,'Custom Slices');self.mine_list=QListWidget();self.mine_list.setMaximumHeight(100);layout.addWidget(self.mine_list)
        for label,callback in [('Add…',lambda:self._edit_mine(True)),('Edit',self._edit_mine),('Remove',self._remove_mine),('Advanced…',self._edit_my_slices)]:self._button(layout,label,callback)
        layout=self._group(5,'Presets and chains');self.custom_list=QListWidget();self.custom_list.setMaximumHeight(100);layout.addWidget(self.custom_list)
        for label,callback in [('New image preset',lambda:self._new_custom('image')),('New video preset',lambda:self._new_custom('video')),('New chain',lambda:self._new_custom('chain')),('Edit',self._edit_custom),('Delete',self._delete_custom)]:self._button(layout,label,callback)
        self._fill_mine();self._fill_custom()
    def _advanced(self):
        layout=self._group(6,'Command line');self._button(layout,'Open a Command Prompt',self.rt.winsys.open_cli_window)
        layout=self._group(6,'Settings Config');self._button(layout,'Export settings…',self._export);self._button(layout,'Import settings…',self._import);self._button(layout,'Restore defaults…',self._restore_defaults)
        layout=self._group(6,'Help');self._switch(layout,'tour_start','tour_at_start','Show the welcome tour when ConvertANNY starts');self._button(layout,'Show the quick tour again',lambda:self.app.show_tour(parent=self))
        self._switch(layout,'crash_reports','crash_reports','Offer a crash report when something goes wrong',False)
        self._button(layout,'Open the log',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.rt.winsys.log_path()))));self._button(layout,'Show the log folder',lambda:self.rt.winsys.reveal([str(self.rt.winsys.log_path())]))
    def _about(self):
        layout=self.pages[7];logo=QLabel();logo.setPixmap(self.rt.app_icon().pixmap(64,64));layout.addWidget(logo);layout.addWidget(QLabel('ConvertANNY · 0.1.0'))
        info=QLabel('Windows workspace for file conversion, file tools, and optional sharing.');info.setWordWrap(True);layout.addWidget(info)
        layout=self._group(7,'Updates');layout.addWidget(QLabel(tr('Release repository (owner/repository)')));self.release_repo=QLineEdit(str(self.s.value('updates/repository','')));layout.addWidget(self.release_repo)
        self._switch(layout,'auto_update','check_updates','Check for updates once a day',False);self._button(layout,'Check saved release channel',lambda:self.app.check_updates(manual=True))
        layout=self._group(7,'Components');note=QLabel('Office documents require Microsoft Office or LibreOffice. RAR creation requires WinRAR. Component notices are included with the application.');note.setWordWrap(True);layout.addWidget(note)
        self._button(layout,'Open licenses and attribution',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.rt.asset('')).parent/'licenses'))))
    def _theme_preview(self):
        self.s.setValue('theme',self.theme_box.currentData());theme.set_mode(self.theme_box.currentData());self.app.apply_theme();self.setStyleSheet(design.css())
    def _fill_watch(self):
        self.watch_list.clear()
        for rule in self.rt.watch_folders():self.watch_list.addItem(str(rule.get('folder',''))+' · '+str(rule.get('label','')))
    def _add_watch(self):
        dialog=self.rt.WatchRuleDialog(self,categories=self.rt.WHEEL_TYPES,operations=self.rt._watch_ops,css=design.css())
        if dialog.exec()==QDialog.Accepted:
            self.s.setValue('watch_folders',json.dumps([*self.rt.watch_folders(),dialog.rule]));self._fill_watch();self.app.watch.reload()
    def _remove_watch(self):
        rules=self.rt.watch_folders();row=self.watch_list.currentRow()
        if 0<=row<len(rules):rules.pop(row);self.s.setValue('watch_folders',json.dumps(rules));self._fill_watch();self.app.watch.reload()
    def _fill_mine(self):
        self.mine_list.clear()
        for spec in self.rt.load_my_slices():self.mine_list.addItem(str(spec.get('name',''))+' · '+str(spec.get('command','')))
    def _edit_mine(self,new=False):
        specs=self.rt.load_my_slices();row=self.mine_list.currentRow()
        if not new and not 0<=row<len(specs):return
        dialog=self.rt.CustomSliceDialog(None if new else specs[row],self)
        if dialog.exec()==QDialog.Accepted and dialog.spec:
            if new:specs.append(dialog.spec)
            else:specs[row]=dialog.spec
            self.rt.save_my_slices(specs);self._fill_mine()
    def _remove_mine(self):
        specs=self.rt.load_my_slices();row=self.mine_list.currentRow()
        if 0<=row<len(specs):specs.pop(row);self.rt.save_my_slices(specs);self._fill_mine()
    def _edit_my_slices(self):
        self.rt.load_my_slices();QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.rt.my_slices_file())))
    def _fill_custom(self):
        self.custom_list.clear()
        for spec in self.rt.custom_slices():
            item=QListWidgetItem(str(spec.get('name',''))+' · '+str(spec.get('kind','')));item.setData(Qt.UserRole,spec.get('uid'));self.custom_list.addItem(item)
    def _new_custom(self,kind,spec=None):
        dialog=self.rt.ChainDialog(spec,self) if kind=='chain' else self.rt.PresetDialog(kind,spec,self)
        if dialog.exec()!=QDialog.Accepted:return
        value=dialog.spec();specs=[item for item in self.rt.custom_slices() if item.get('uid')!=value['uid']];specs.append(value);self.rt.save_custom_slices(specs);self._fill_custom()
    def _edit_custom(self):
        item=self.custom_list.currentItem()
        if item:
            spec=next((spec for spec in self.rt.custom_slices() if spec.get('uid')==item.data(Qt.UserRole)),None)
            if spec:self._new_custom(spec['kind'],spec)
    def _delete_custom(self):
        item=self.custom_list.currentItem()
        if item:self.rt.save_custom_slices([spec for spec in self.rt.custom_slices() if spec.get('uid')!=item.data(Qt.UserRole)]);self._fill_custom()
    def _export(self):
        path,_=QFileDialog.getSaveFileName(self,tr('Export settings…'),'ConvertANNY-settings.json','JSON (*.json)')
        if path:
            try:self.rt.export_settings(path)
            except Exception as error:QMessageBox.warning(self,'ConvertANNY',str(error))
    def _import(self):
        path,_=QFileDialog.getOpenFileName(self,tr('Import settings…'),'','JSON (*.json)')
        if path:
            try:
                self.rt.import_settings(path);self.app.apply_theme();self.app.apply_language()
                if hasattr(self.app,'watch'):self.app.watch.reload()
                if hasattr(self.app,'watcher'):self.app.watcher.refresh_settings()
                self._saved=True;self.accept()
            except Exception as error:QMessageBox.warning(self,'ConvertANNY',str(error))
    def _restore_defaults(self):
        if QMessageBox.question(self,'ConvertANNY',tr('Restore defaults?'))==QMessageBox.Yes:self.s.clear();self.s.sync();self.app.apply_theme();self.app.apply_language();self.accept()
    def save(self):
        keys={mode:control.spec for mode,control in self.key_boxes.items()};used=[value for value in keys.values() if value!='None']
        if len(set(used))!=len(used):QMessageBox.warning(self,'ConvertANNY',tr('Each wheel and File preview need a different key.'));return
        repository=self.release_repo.text().strip()
        if repository and (not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) or repository.split('/')[1].casefold()!='convertanny'):
            QMessageBox.warning(self,'ConvertANNY',tr('Use an owner/ConvertANNY release repository.'));return
        if self.out_mode.currentData()=='folder' and (not self.out.text().strip() or not Path(self.out.text().strip()).is_dir()):QMessageBox.warning(self,'ConvertANNY',tr('Choose an existing output folder.'));return
        try:
            self.rt.winsys.set_startup(self.startup.isChecked());self.rt.winsys.set_context_menu(self.menu.isChecked(),sendto=self.sendto.isChecked())
            if self.full_menu is not None and self.full_menu.isChecked()!=self.rt.winsys.full_menu_enabled():self.rt.winsys.set_full_menu(self.full_menu.isChecked());self.rt.winsys.restart_explorer()
        except Exception as error:QMessageBox.warning(self,'ConvertANNY',str(error));return
        for key,control in self._switches.items():
            if key not in ('startup','menu','sendto','full_menu'):self.s.setValue(key,'true' if control.isChecked() else 'false')
        for key,control in self._choices.items():self.s.setValue(key,control.currentData())
        for key,control in self._numbers.items():self.s.setValue(key,control.value())
        for mode,value in keys.items():self.s.setValue('keys/'+mode,value)
        language_id=self.rt.INSTALLER_LANG_IDS.get(self.lang.currentData())
        if language_id:self.s.setValue('InstallerLanguage',str(language_id))
        self.s.setValue('output_dir',self.out.text().strip() if self.out_mode.currentData()=='folder' else '')
        self.s.setValue('updates/repository',repository);self.s.setValue('peek','false' if keys['peek']=='None' else 'true');self.s.setValue('detect_any',0);self.s.setValue('hotkey','false');self.s.sync()
        self.rt.engine.OUTPUT_DIR=self.out.text().strip() if self.out_mode.currentData()=='folder' else None
        for window in getattr(self.app,'floats',[]):
            if self.taskbar.isChecked()!=self._original_taskbar:window.set_taskbar(self.taskbar.isChecked())
            window.update()
        if hasattr(self.app,'watcher'):self.app.watcher.refresh_settings()
        self.app.apply_theme();self.app.apply_language();self._saved=True;self.accept()
    def reject(self):
        if not self._saved:
            self.s.setValue('theme',self.orig_theme);theme.set_mode(self.orig_theme);self.app.apply_theme()
        super().reject()
