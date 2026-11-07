from pathlib import Path
import sysconfig
import shutil,zipfile,subprocess,sys
import re
root=Path(__file__).resolve().parents[1];app=root/'dist/ConvertANNY';lic=app/'_internal/licenses/components';lic.mkdir(parents=True,exist_ok=True)
version=(root/'VERSION').read_text(encoding='ascii').strip()
if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?',version):raise ValueError('VERSION must be a semantic version such as 1.2.3')
build=root/'build';build.mkdir(exist_ok=True);version_cs=build/'BuildInfo.cs'
version_cs.write_text('internal static class BuildInfo { internal const string Version = "'+version+'"; }',encoding='ascii')
manifest=(root/'packaging/AppxManifest.xml').read_text(encoding='utf-8')
(build/'AppxManifest.xml').write_text(manifest.replace('__VERSION__',version),encoding='utf-8')
compiler=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
refs=['/reference:'+s for s in ['System.Windows.Forms.dll','System.Drawing.dll','System.IO.Compression.dll','System.IO.Compression.FileSystem.dll','Microsoft.CSharp.dll']]
subprocess.run([str(compiler),'/nologo','/target:winexe','/optimize+','/define:UNINSTALLER',f'/out:{root / "packaging/Uninstall.exe"}',f'/win32icon:{root / "src/assets/convertanny.ico"}']+refs+[str(version_cs),str(root/'packaging/Uninstall.cs')],check=True)
site_packages=Path(sysconfig.get_paths()['purelib'])
portable_packages=root/'.build-tools/python312/Lib/site-packages'
if not (root/'.venv').exists() and portable_packages.exists():site_packages=portable_packages
for info in site_packages.glob('*.dist-info'):
 for f in info.rglob('*'):
  if f.is_file() and ('license' in f.name.lower() or 'copying' in f.name.lower()):
   dest=lic/info.name/f.relative_to(info);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,dest)
shutil.copy2(root/'packaging/Uninstall.exe',app/'Uninstall.exe')
source=app/'Source';source.mkdir(exist_ok=True)
for name in ['src','scripts','packaging','docs','licenses']:
 shutil.copytree(root/name,source/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.exe','*.zip','adapt_reference.py','TestSetup.*','TestAnimation.*'))
shutil.copy2(root/'requirements.txt',source/'requirements.txt');shutil.copy2(root/'README.md',source/'README.md')
for name in ['requirements-build.txt', 'requirements-release.txt', 'ConvertANNY.spec', 'VERSION']:
 shutil.copy2(root/name,source/name)
for name in ['LICENSE','NOTICE','COPYRIGHT.md','THIRD_PARTY.md']:
 shutil.copy2(root/name,source/name);shutil.copy2(root/name,app/name)
payload=root/'packaging/payload.zip'
with zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
 for p in app.rglob('*'):
  if p.is_file():z.write(p,p.relative_to(app).as_posix())
args=[str(compiler),'/nologo','/target:winexe','/optimize+',f'/out:{root / f"dist/ConvertANNY-Setup-{version}.exe"}',f'/win32icon:{root / "src/assets/convertanny.ico"}',f'/resource:{payload},payload.zip',f'/resource:{root / "src/assets/fonts/Inter-Regular.ttf"},Inter.ttf',f'/resource:{root / "src/assets/convertanny.ico"},brand.ico']
args += refs
args += [f'/resource:{root / "src/assets/convertanny.png"},brand.png']
for i in range(64):args.append(f'/resource:{root / f"packaging/brand-frame-{i}.png"},brand-frame-{i}.png')
subprocess.run(args+[str(version_cs),str(root/'packaging/Setup.cs')],check=True)
print('Installer built',flush=True)
