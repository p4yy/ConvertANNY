using System; using System.IO; using System.IO.Compression; using System.Drawing; using System.Windows.Forms; using System.Diagnostics; using System.Reflection; using Microsoft.Win32;
class Setup : Form {
 static string target=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","ConvertANNY");
 Button install=new Button(); Label status=new Label(); bool installed=false;
 Setup(){ Text="ConvertANNY Setup"; Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath); ClientSize=new Size(500,260); StartPosition=FormStartPosition.CenterScreen; FormBorderStyle=FormBorderStyle.FixedDialog; MaximizeBox=false; BackColor=Color.FromArgb(17,17,17); ForeColor=Color.White; Font=new Font("Segoe UI",10);
 var picture=new PictureBox{Image=Icon.ToBitmap(),SizeMode=PictureBoxSizeMode.Zoom,Bounds=new Rectangle(28,28,48,48)};Controls.Add(picture);
 Controls.Add(new Label{Text="ConvertANNY",Font=new Font(Font.FontFamily,19,FontStyle.Bold),AutoSize=true,Location=new Point(92,32)});
 status.Text="Install for your Windows account.\n\n"+target;status.SetBounds(28,98,440,80);Controls.Add(status);
 install.Text="Install";install.SetBounds(340,200,128,34); install.BackColor=Color.FromArgb(37,99,235);install.ForeColor=Color.White;install.FlatStyle=FlatStyle.Flat;install.Click+=(s,e)=>Install();Controls.Add(install);}
 static string DesktopLink{get{return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"ConvertANNY.lnk");}}
 static string StartLink{get{return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),"ConvertANNY.lnk");}}
 static void Shortcut(string path,string exe){Type t=Type.GetTypeFromProgID("WScript.Shell");dynamic shell=Activator.CreateInstance(t);dynamic link=shell.CreateShortcut(path);link.TargetPath=exe;link.WorkingDirectory=target;link.IconLocation=exe+",0";link.Save();}
 void Install(){if(installed){Process.Start(Path.Combine(target,"ConvertANNY.exe"));Close();return;}install.Enabled=false;status.Text="Installing…";Application.DoEvents();try{DoInstall();installed=true;status.Text="Installed successfully.";install.Text="Open ConvertANNY";install.Enabled=true;}catch(Exception ex){status.Text="Installation failed: "+ex.Message;install.Enabled=true;}}
 static void DoInstall(){foreach(var p in Process.GetProcessesByName("ConvertANNY")){try{if(p.MainModule.FileName.StartsWith(target,StringComparison.OrdinalIgnoreCase))throw new IOException("Close ConvertANNY before installing.");}catch(System.ComponentModel.Win32Exception){}}
 Directory.CreateDirectory(target);using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip")){if(stream==null)throw new IOException("Missing application payload.");using(var zip=new ZipArchive(stream,ZipArchiveMode.Read)){foreach(var entry in zip.Entries){string path=Path.GetFullPath(Path.Combine(target,entry.FullName));if(!path.StartsWith(target+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new IOException("Invalid package path.");if(entry.FullName.EndsWith("/")){Directory.CreateDirectory(path);continue;}Directory.CreateDirectory(Path.GetDirectoryName(path));entry.ExtractToFile(path,true);}}}
 File.WriteAllText(Path.Combine(target,".convertanny-install"),BuildInfo.Version);Shortcut(DesktopLink,Path.Combine(target,"ConvertANNY.exe"));Shortcut(StartLink,Path.Combine(target,"ConvertANNY.exe"));using(var key=Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\ConvertANNY")){key.SetValue("DisplayName","ConvertANNY");key.SetValue("DisplayVersion",BuildInfo.Version);key.SetValue("InstallLocation",target);key.SetValue("DisplayIcon",Path.Combine(target,"ConvertANNY.exe"));key.SetValue("UninstallString","\""+Path.Combine(target,"Uninstall.exe")+"\"");}}
 [STAThread] static int Main(string[] args){Application.EnableVisualStyles();
#if UNINSTALLER
 if(args.Length>0&&args[0]=="--remove"){System.Threading.Thread.Sleep(1000);if(Directory.Exists(target)&&File.Exists(Path.Combine(target,".convertanny-install"))){Directory.Delete(target,true);if(File.Exists(DesktopLink))File.Delete(DesktopLink);if(File.Exists(StartLink))File.Delete(StartLink);Registry.CurrentUser.DeleteSubKeyTree(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\ConvertANNY",false);}return 0;}
 if(MessageBox.Show("Remove ConvertANNY? Your personal settings and converted files are kept.","ConvertANNY",MessageBoxButtons.OKCancel)!=DialogResult.OK)return 0;string copy=Path.Combine(Path.GetTempPath(),"ConvertANNY-Uninstall-"+Guid.NewGuid()+".exe");File.Copy(Application.ExecutablePath,copy);Process.Start(copy,"--remove");return 0;
#else
 if(args.Length>0&&args[0]=="--silent"){try{DoInstall();return 0;}catch{return 1;}}Application.Run(new Setup());return 0;
#endif
 }
}
