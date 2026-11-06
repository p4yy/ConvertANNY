"""ConvertANNY Office automation and isolated LibreOffice conversion."""
from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from .model import ConversionError
from .paths import OutputPolicy,atomic_write

_WORD={'docx':16,'doc':0,'rtf':6,'txt':7,'html':10,'odt':23}
_EXCEL={'xlsx':51,'xls':56,'csv':62,'ods':60}
_SLIDES={'pptx':24,'ppt':1,'odp':35,'png':18,'jpg':17,'pdf':32}


def libreoffice_executable():
    executable=shutil.which('soffice') or shutil.which('libreoffice')
    if executable:return executable
    for root in (os.environ.get('ProgramFiles'),os.environ.get('ProgramFiles(x86)')):
        if root:
            candidate=Path(root)/'LibreOffice'/'program'/'soffice.exe'
            if candidate.is_file():return str(candidate)
    return None


def office_available():
    if libreoffice_executable():return True
    if os.name!='nt':return False
    import winreg
    for application in ('Word.Application','Excel.Application','PowerPoint.Application'):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,application):return True
        except OSError:pass
    return False


def _kind(source):
    if source.suffix.lower() in ('.xlsx','.xlsm','.xls','.ods','.csv','.tsv'):return 'sheet'
    if source.suffix.lower() in ('.pptx','.ppt','.odp','.key'):return 'slides'
    return 'word'


def _native(source,target,kind,format):
    if os.name!='nt':raise ConversionError('Microsoft Office automation requires Windows')
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize();application=None;document=None
    try:
        application=win32com.client.DispatchEx({'word':'Word.Application','sheet':'Excel.Application','slides':'PowerPoint.Application'}[kind])
        application.AutomationSecurity=3
        if kind!='slides':application.Visible=False
        if kind=='word':
            application.DisplayAlerts=0
            document=application.Documents.Open(str(source),ConfirmConversions=False,ReadOnly=True,AddToRecentFiles=False)
            if format=='pdf':
                document.ExportAsFixedFormat(OutputFileName=str(target),ExportFormat=17,OpenAfterExport=False,
                    OptimizeFor=0,Range=0,Item=0,IncludeDocProps=True,CreateBookmarks=1,
                    DocStructureTags=True,BitmapMissingFonts=True,UseISO19005_1=False)
            elif format in _WORD:document.SaveAs2(str(target),FileFormat=_WORD[format])
            else:raise ConversionError('Word does not support this output format')
        elif kind=='sheet':
            application.DisplayAlerts=False
            document=application.Workbooks.Open(str(source),ReadOnly=True,UpdateLinks=0)
            if format=='pdf':document.ExportAsFixedFormat(0,str(target),Quality=0,IncludeDocProperties=True,IgnorePrintAreas=False,OpenAfterPublish=False)
            elif format in _EXCEL:document.SaveAs(str(target),FileFormat=_EXCEL[format])
            else:raise ConversionError('Excel does not support this output format')
        else:
            document=application.Presentations.Open(str(source),ReadOnly=True,WithWindow=False)
            if format not in _SLIDES:raise ConversionError('PowerPoint does not support this output format')
            document.SaveAs(str(target),_SLIDES[format])
    finally:
        try:
            if document is not None:
                document.Close() if kind=='slides' else document.Close(False)
        finally:
            try:
                if application is not None:application.Quit()
            finally:pythoncom.CoUninitialize()


def _libreoffice(source,target,format,token):
    executable=libreoffice_executable()
    if not executable:raise ConversionError('LibreOffice is not installed')
    filters={'txt':'txt:Text (encoded):UTF8','csv':'csv:Text - txt - csv (StarCalc):44,34,76',
             'docx':'docx:MS Word 2007 XML','doc':'doc:MS Word 97','xls':'xls:MS Excel 97','ppt':'ppt:MS PowerPoint 97'}
    with tempfile.TemporaryDirectory(prefix='convertanny-office-profile-') as profile:
        command=[executable,'-env:UserInstallation='+Path(profile).as_uri(),'--headless','--norestore','--nodefault','--nofirststartwizard']
        if source.suffix.lower() in ('.html','.htm'):command.append('--infilter=HTML (StarWriter)')
        command += ['--convert-to',filters.get(format,format),'--outdir',str(target.parent),str(source)]
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                                 creationflags=0x08000000 if os.name=='nt' else 0)
        import time
        started=time.monotonic()
        try:
            while process.poll() is None:
                if token:token.check()
                if time.monotonic()-started>180:raise ConversionError('Office conversion timed out')
                try:process.wait(timeout=.2)
                except subprocess.TimeoutExpired:pass
            error=process.stderr.read().decode('utf-8','replace').strip()
            if process.returncode:raise ConversionError(error or 'LibreOffice conversion failed')
        finally:
            if process.poll() is None:process.kill();process.wait()
            if process.stderr:process.stderr.close()
    generated=target.parent/(source.stem+'.'+format)
    if generated!=target and generated.is_file():generated.rename(target)


def convert_office(source,format,*,directory=None,token=None,native_only=False):
    source=Path(source).resolve();format=str(format).lower().lstrip('.')
    if not source.is_file():raise ConversionError(f'File not found: {source.name}')
    if format not in {*_WORD,*_EXCEL,*_SLIDES}:raise ConversionError('Unsupported Office output format')
    if token:token.check()
    kind=_kind(source);parent=Path(directory) if directory else source.parent
    destination=OutputPolicy(directory=parent).destination(source,format)
    if kind=='slides' and format in ('png','jpg'):
        destination=parent/(source.stem+' '+format.upper());index=2
        while destination.exists():destination=parent/f'{source.stem} {format.upper()} ({index})';index+=1
    parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='convertanny-office-') as folder:
        staging=Path(folder)/destination.name
        try:_native(source,staging,kind,format)
        except Exception as native_error:
            if native_only:raise ConversionError(f'Microsoft Office conversion failed: {native_error}') from native_error
            if not libreoffice_executable():raise ConversionError('Microsoft Office or LibreOffice is required for this conversion') from native_error
            if staging.is_dir():shutil.rmtree(staging)
            else:staging.unlink(missing_ok=True)
            _libreoffice(source,staging,format,token)
        if token:token.check()
        if staging.is_dir():
            if not any(staging.iterdir()):raise ConversionError('Office produced no slide images')
            shutil.copytree(staging,destination)
        else:
            if not staging.is_file() or staging.stat().st_size==0:raise ConversionError('Office did not produce a complete output')
            # HTML exports may include adjacent image directories or resources.
            resources=[item for item in Path(folder).iterdir() if item!=staging]
            copied=[]
            try:
                for resource in resources:
                    target=parent/resource.name
                    if target.exists():raise ConversionError(f'Export resource already exists: {target.name}')
                    shutil.copytree(resource,target) if resource.is_dir() else shutil.copy2(resource,target)
                    copied.append(target)
                atomic_write(destination,lambda temporary:shutil.copyfile(staging,temporary),token)
            except Exception:
                for resource in copied:
                    shutil.rmtree(resource) if resource.is_dir() else resource.unlink(missing_ok=True)
                raise
    if token:token.report(1)
    return destination
