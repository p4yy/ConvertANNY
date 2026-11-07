"""Desktop catalog dispatch, batch failure reporting and cancellation cleanup."""
import json
from pathlib import Path
import shutil


def _results(value):
    if isinstance(value,(tuple,list)):
        for item in value:yield from _results(item)
    elif value is not None:yield value


def run_operation(operation,paths,parameters=None,token=None):
    import engine
    parameters=dict(parameters or {});paths=list(paths)
    protected={Path(path).resolve() for path in paths}
    previous=engine._token();engine._ctx.token=token
    completed=[];failures=[]
    def notify(kind,value):
        callback=getattr(token,'on_path',None)
        if callback:
            try:callback(kind,value)
            except Exception:pass
    def collect(value):
        for result in _results(value):
            completed.append(result)
            if token is not None and isinstance(result,(str,Path)):
                candidate=Path(result)
                if candidate.resolve() not in protected and candidate not in token.paths:
                    token.paths.append(candidate)
    try:
        engine.check_cancel()
        if operation.multi:
            collect(operation.fn(paths,parameters))
        else:
            for index,path in enumerate(paths):
                engine.check_cancel()
                if token is not None:token.batch=(index,len(paths))
                if len(paths)>1:notify('count',f'{index}/{len(paths)}')
                try:collect(operation.fn(path,parameters))
                except (engine.Cancelled,KeyboardInterrupt):raise
                except Exception as error:
                    if len(paths)==1 or (token is not None and token.cancelled):raise
                    detail=str(error) or type(error).__name__;failures.append(detail)
                    notify('failed',json.dumps([Path(path).name,detail]))
            if len(paths)>1:notify('count',f'{len(paths)}/{len(paths)}')
            if failures and not completed:raise engine.ConversionError(failures[0])
        engine.check_cancel()
        return completed
    except BaseException:
        if token is not None and token.cancelled:
            cleanup_outputs(token,protected)
            raise engine.Cancelled() from None
        raise
    finally:
        engine._ctx.token=previous
        engine.close_pdfs()


def cleanup_outputs(token,protected=()):
    protected={Path(path).resolve() for path in protected}
    for value in reversed(token.paths):
        path=Path(value)
        for candidate in (path,path.with_name(path.name+'.part')):
            resolved=candidate.resolve()
            if resolved in protected or any(resolved in item.parents for item in protected):continue
            try:
                if candidate.is_symlink() or candidate.is_file():candidate.unlink(missing_ok=True)
                elif candidate.is_dir():shutil.rmtree(candidate)
            except OSError:pass
