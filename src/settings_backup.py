"""Portable ConvertANNY preferences snapshots and validated restoration."""
import json
import os
from pathlib import Path
from uuid import uuid4
from i18n import tr


def _write(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        temporary.write_text(text,encoding='utf-8');os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def export_settings(path):
    import runtime as rt
    import winsys
    settings=rt.settings()
    values={key:settings.value(key) for key in settings.allKeys() if not key.startswith(rt.EXPORT_SKIP)}
    for key,value in rt.SETTINGS_DEFAULTS.items():values.setdefault(key,value)
    values.update({f'keys/{mode}':key for mode,key in rt.mode_keys().items()})
    values['keys/peek']=rt.peek_key();values['wheel_anim_close']=rt.wheel_anim_close()
    document=dict(app=rt.APP,version=rt.VERSION,settings=values,
                  windows=dict(startup=winsys.startup_enabled(),menu=winsys.context_menu_enabled(),
                               sendto=winsys.sendto_enabled(),full_menu=winsys.full_menu_enabled()))
    slices=rt.my_slices_file()
    if slices.is_file():document['my_slices']=slices.read_text(encoding='utf-8-sig')
    _write(path,json.dumps(document,ensure_ascii=False,indent=2,default=str))


def import_settings(path):
    import runtime as rt
    import winsys
    document=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(document,dict) or document.get('app')!=rt.APP or not isinstance(document.get('settings'),dict):
        raise ValueError(tr("This isn't a ConvertANNY settings file."))
    values=document['settings'];windows=document.get('windows') or {};slices=document.get('my_slices')
    if not isinstance(windows,dict) or any(not isinstance(value,bool) for value in windows.values()):
        raise ValueError('Invalid Windows integration settings')
    if any(not isinstance(key,str) or not key or key.startswith(rt.EXPORT_SKIP) for key in values):
        raise ValueError('Invalid or private preference key')
    if slices is not None:
        if not isinstance(slices,str):raise ValueError('Invalid custom application actions')
        content='\n'.join(line for line in slices.splitlines() if not line.lstrip().startswith('//'))
        parsed=json.loads(content)
        if not isinstance(parsed,list) or any(not isinstance(item,dict) for item in parsed):
            raise ValueError('Invalid custom application actions')
    settings=rt.settings();original={key:settings.value(key) for key in settings.allKeys()}
    destination=rt.my_slices_file();previous=destination.read_text(encoding='utf-8') if destination.exists() else None
    try:
        for key,value in values.items():settings.setValue(key,value)
        settings.sync()
        if settings.status()!=settings.Status.NoError:raise OSError('Could not save preferences')
        if slices is not None:_write(destination,slices)
    except Exception:
        settings.clear()
        for key,value in original.items():settings.setValue(key,value)
        settings.sync()
        if slices is not None:
            if previous is None:destination.unlink(missing_ok=True)
            else:_write(destination,previous)
        raise
    # Windows integration is applied only after the whole snapshot is validated.
    try:
        if 'startup' in windows:winsys.set_startup(windows['startup'])
        if 'menu' in windows or 'sendto' in windows:
            winsys.set_context_menu(windows.get('menu',winsys.context_menu_enabled()),
                sendto=windows.get('sendto',winsys.sendto_enabled()),
                paste_label=tr('Save clipboard image here'),link_label=tr('Paste link to Float'),
                float_label=tr('Open Float'),qr_label=tr('Read QR code on screen'))
        if 'full_menu' in windows and windows['full_menu']!=winsys.full_menu_enabled():
            winsys.set_full_menu(windows['full_menu']);winsys.restart_explorer()
    except Exception as error:winsys.log(f'Preferences restored; Windows integration could not be restored: {error}')
    return len(values)
