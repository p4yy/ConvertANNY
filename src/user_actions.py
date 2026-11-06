"""Persist user-defined orbit actions and launch their configured applications."""
from pathlib import Path
from copy import deepcopy
import json
import os
import re
import subprocess
from settings_backup import _write


MY_SLICES_TEMPLATE='''// ConvertANNY custom actions.
// Each entry has name, command, for (categories or *), and each (one launch per file).
// Command fields: {file}, {files}, {folder}, {name}, {stem}, {ext}.
// Full lines beginning with // are comments.
[]
'''


def _runtime():
    import runtime
    return runtime


def _jload(key,default):
    raw=_runtime().settings().value(key,None)
    if raw is None:return deepcopy(default)
    try:
        value=json.loads(raw)
        return value if isinstance(value,type(default)) else deepcopy(default)
    except (ValueError,TypeError):return deepcopy(default)


def custom_slices():
    return [value for value in _jload('custom_slices',[]) if isinstance(value,dict)]


def save_custom_slices(items):
    if not isinstance(items,list) or any(not isinstance(item,dict) for item in items):
        raise ValueError('Conversion profiles must be a list of objects')
    _runtime().settings().setValue('custom_slices',json.dumps(items,ensure_ascii=False))


def my_slices_file():
    import engine
    return Path(engine.models_dir()).parent/'my-slices.json'


def load_my_slices():
    import winsys
    path=my_slices_file()
    if not path.exists():return []
    try:
        text=path.read_text(encoding='utf-8-sig')
        value=json.loads('\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('//')))
        if not isinstance(value,list):raise ValueError('Expected an action list')
        return [item for item in value if isinstance(item,dict) and isinstance(item.get('name'),str)
                and item['name'].strip() and isinstance(item.get('command'),str) and item['command'].strip()]
    except (OSError,ValueError) as error:
        winsys.log(f'Custom actions could not be read: {error}');return []


def save_my_slices(items):
    if not isinstance(items,list) or any(not isinstance(item,dict) for item in items):
        raise ValueError('Custom actions must be a list of objects')
    comments=MY_SLICES_TEMPLATE.rsplit('[]',1)[0]
    _write(my_slices_file(),comments+json.dumps(items,ensure_ascii=False,indent=2)+'\n')


def slice_app(spec):
    command=str(spec.get('command','')).strip()
    if not command:return None
    if command.startswith('"'):
        closing=command.find('"',1)
        if closing<0:return None
        application=command[1:closing];argument=command[closing+1:].strip()
    else:
        parts=command.split(None,1)
        if len(parts)!=2:return None
        application,argument=parts
    if argument in ('{file}','"{file}"','{files}'):
        return application,argument!='{files}'
    return None


def run_my_slice(spec,paths):
    import winsys
    files=[str(Path(path)) for path in paths]
    if not files:return
    simple=slice_app(spec)
    groups=[[path] for path in files] if spec.get('each',True) else [files]
    for group in groups:
        if simple:
            executable=os.path.expandvars(simple[0])
            # Pass an argument vector for normal app actions. Ampersands and spaces
            # in selected filenames remain literal, rather than shell syntax.
            command=[executable,*(group if not simple[1] else group[:1])]
            shell=False
        else:
            first=Path(group[0])
            fields=dict(file=str(first),files=' '.join('"'+path+'"' for path in group),
                        folder=str(first.parent),name=first.name,stem=first.stem,ext=first.suffix.lstrip('.'))
            command=re.sub(r'\{(file|files|folder|name|stem|ext)\}',lambda match:fields[match[1]],spec['command'])
            shell=True
        winsys.log(f"Launching custom action: {spec.get('name','')}")
        subprocess.Popen(command,cwd=str(Path(group[0]).parent),shell=shell,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' and shell else 0)


def wheel_layout():
    return {**deepcopy(_runtime().DEFAULT_WHEEL_LAYOUT),**_jload('wheel_layout',{})}


def apply_wheel_layout(mode,category,ops):
    layouts=wheel_layout();config=layouts.get(f'{mode}/{category}')
    if not config and mode=='action':config=layouts.get('action/*')
    if not isinstance(config,dict):return ops
    hidden=set(config.get('hidden',[]));ranks={key:index for index,key in enumerate(config.get('order',[]))}
    selected=[(index,operation) for index,operation in enumerate(ops) if operation.id not in hidden]
    if not selected:return ops[:1]
    selected.sort(key=lambda pair:(ranks.get(pair[1].id,len(ranks)),pair[0]))
    return [operation for _,operation in selected]


def custom_ops_for(mode,paths):
    import engine,winsys
    category=engine.category_of(paths);result=[]
    for profile in custom_slices():
        group='tool' if profile.get('kind')=='chain' else 'convert'
        if group!=mode or profile.get('for',profile.get('kind')) not in (category,'*'):continue
        try:
            operation=engine.custom_op(profile,group);operation.spec=profile;result.append(operation)
        except Exception as error:winsys.log(f'Conversion profile could not be loaded: {error}')
    if mode=='action':
        for index,action in enumerate(load_my_slices()):
            categories=action.get('for') or ['*']
            if isinstance(categories,str):categories=[categories]
            if '*' not in categories and category not in categories:continue
            def launch(selected,parameters,definition=deepcopy(action)):
                return run_my_slice(definition,selected)
            result.append(engine.Op(f'mine:{index}',action['name'],launch,group='action',multi=True))
    return result
