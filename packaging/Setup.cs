using System;
using System.IO;
using System.IO.Compression;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Windows.Forms;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Win32;

// Current-user installer. No install, registry or shell mutation occurs until Install is clicked.
class Setup : Form {
    static readonly Color Ink=Color.FromArgb(242,242,245), Muted=Color.FromArgb(155,157,166), Blue=Color.FromArgb(37,99,235);
    static readonly string Target=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","ConvertANNY");
    readonly PrivateFontCollection fonts=new PrivateFontCollection();
    readonly Panel page=new Panel();
    readonly Label heading=new Label(), description=new Label(), detail=new Label(), percent=new Label();
    readonly Toggle explorer=new Toggle(), desktop=new Toggle();
    readonly ActionButton primary=new ActionButton(), secondary=new ActionButton();
    readonly ProgressTrack progress=new ProgressTrack();
    AnimatedMark mark;
    volatile bool cancel;
    bool busy,installed;
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr hwnd,int attr,ref int value,int length);

    public Setup() {
        AutoScaleMode=AutoScaleMode.Dpi;
        Text="ConvertANNY Setup";
        Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        // Load the approved icon independently when instantiated by the test harness.
        using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("brand.ico")) if(stream!=null) using(var loaded=new Icon(stream)) Icon=(Icon)loaded.Clone();
        using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("Inter.ttf")) {
            if(stream!=null) { byte[] bytes=new byte[stream.Length];stream.Read(bytes,0,bytes.Length);IntPtr mem=Marshal.AllocCoTaskMem(bytes.Length);try{Marshal.Copy(bytes,0,mem,bytes.Length);fonts.AddMemoryFont(mem,bytes.Length);}finally{Marshal.FreeCoTaskMem(mem);} }
        }
        Font=new Font(fonts.Families.Length>0?fonts.Families[0]:new FontFamily("Segoe UI"),10);
        ClientSize=new Size(660,500);MinimumSize=Size;MaximumSize=Size;
        StartPosition=FormStartPosition.CenterScreen;FormBorderStyle=FormBorderStyle.FixedSingle;MaximizeBox=false;
        BackColor=Color.FromArgb(15,16,19);ForeColor=Ink;DoubleBuffered=true;
        page.SetBounds(0,0,660,500);page.BackColor=BackColor;page.ForeColor=Ink;Controls.Add(page);
        mark=new AnimatedMark{Image=LoadBrand(),SizeMode=PictureBoxSizeMode.Zoom,Bounds=new Rectangle(170,14,320,90)};page.Controls.Add(mark);
        mark.SetReveal(LoadRevealFrames(),LoadBrand());
        AddLabel(BuildInfo.Version,new Rectangle(554,40,74,24),9,FontStyle.Regular,Muted).TextAlign=ContentAlignment.MiddleRight;
        heading.SetBounds(32,130,596,42);heading.ForeColor=Ink;heading.Font=new Font(Font.FontFamily,23,FontStyle.Bold);heading.Text="Install";page.Controls.Add(heading);
        description.SetBounds(32,178,596,38);description.ForeColor=Muted;description.Text="Choose your Windows shortcuts and file actions.";page.Controls.Add(description);
        AddOption(explorer,"File Explorer menu","Right-click files or folders to open the conversion wheel.",224);
        AddOption(desktop,"Desktop shortcut","Open your ConvertANNY workspace from the Desktop.",298);
        detail.SetBounds(32,397,596,43);detail.Font=new Font(Font.FontFamily,9);detail.ForeColor=Muted;detail.Text="INSTALL LOCATION\n"+Target;detail.AutoEllipsis=true;page.Controls.Add(detail);
        progress.SetBounds(32,369,596,5);progress.Visible=false;page.Controls.Add(progress);
        percent.SetBounds(32,335,596,25);percent.ForeColor=Muted;percent.Visible=false;page.Controls.Add(percent);
        secondary.Text="Cancel";secondary.SetBounds(32,453,110,40);secondary.Click+=(s,e)=>{if(busy){cancel=true;secondary.Enabled=false;description.Text="Cancelling and removing temporary files…";}else Close();};page.Controls.Add(secondary);
        primary.Text="Install";primary.Primary=true;primary.SetBounds(410,453,218,40);primary.Click+=InstallClick;page.Controls.Add(primary);
        AcceptButton=primary;CancelButton=secondary;
        FormClosing+=(s,e)=>{if(busy){cancel=true;e.Cancel=true;secondary.Enabled=false;description.Text="Cancelling and removing temporary files…";}};
        Shown+=(s,e)=>{int dark=1;try{DwmSetWindowAttribute(Handle,20,ref dark,4);}catch{};mark.PlayReveal();};
        FormClosed+=(s,e)=>{fonts.Dispose();};
    }
    static Image LoadBrand(){var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("brand.png");if(stream==null)return new Bitmap(1,1);using(stream)using(var image=Image.FromStream(stream))return new Bitmap(image);}
    Image[] LoadRevealFrames(){var frames=new Image[64];for(int i=0;i<frames.Length;i++){var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("brand-frame-"+i+".png");if(stream==null){foreach(var image in frames)if(image!=null)image.Dispose();return new Image[0];}using(stream)using(var image=Image.FromStream(stream))frames[i]=new Bitmap(image);}return frames;}
    Label AddLabel(string text,Rectangle rect,float size,FontStyle style,Color color) {
        var label=new Label{Text=text,Bounds=rect,Font=new Font(Font.FontFamily,size,style),ForeColor=color,BackColor=Color.Transparent};page.Controls.Add(label);return label;
    }
    void AddOption(Toggle toggle,string title,string subtitle,int top) {
        var card=new Card{Bounds=new Rectangle(32,top,596,66)};page.Controls.Add(card);
        var titleLabel=new Label{Text=title,Bounds=new Rectangle(17,12,480,22),Font=new Font(Font.FontFamily,10,FontStyle.Bold),ForeColor=Ink,BackColor=Color.Transparent};card.Controls.Add(titleLabel);
        card.Controls.Add(new Label{Text=subtitle,Bounds=new Rectangle(17,35,480,20),Font=new Font(Font.FontFamily,9),ForeColor=Muted,BackColor=Color.Transparent});
        toggle.SetBounds(528,22,44,24);toggle.Checked=true;toggle.AccessibleName=title;card.Controls.Add(toggle);
        titleLabel.Click+=(s,e)=>toggle.Checked=!toggle.Checked;
    }
    void Transition(string title,string body) {
        heading.Text=title;description.Text=body;
    }
    void SetOptionsVisible(bool value) {foreach(Control c in page.Controls)if(c is Card)c.Visible=value;}
    async void InstallClick(object sender,EventArgs e) {
        if(installed){try{Process.Start(Path.Combine(Target,"ConvertANNY.exe"));Close();}catch(Exception ex){description.Text=ex.Message;}return;}
        bool shell=explorer.Checked,desk=desktop.Checked;
        busy=true;cancel=false;primary.Enabled=false;secondary.Enabled=true;SetOptionsVisible(false);progress.Visible=true;percent.Visible=true;progress.Value=0;
        Transition("Installing","Copying application files and bundled conversion engines.");
        try {
            await Task.Run(()=>InstallCore(shell,desk,(fraction,name)=>{if(IsDisposed)return;BeginInvoke(new Action(()=>{progress.Value=(float)Math.Min(.99,Math.Max(0,fraction));percent.Text=Math.Min(99,(int)(fraction*100))+"%   ·   "+name;}));},()=>cancel));
            busy=false;installed=true;secondary.Text="Close";secondary.Enabled=true;primary.Text="Open ConvertANNY";primary.Enabled=true;progress.Value=1;percent.Text="100%   ·   Installation complete";
            Transition("Installed",shell?"Right-click a file or folder and choose ConvertANNY to open the wheel.":"Open the app to convert files and configure your wheel.");
            detail.Text=Target;
        } catch(OperationCanceledException) {busy=false;Reset("Installation cancelled","Your existing application was kept.");}
          catch(Exception ex) {busy=false;Reset("Installation couldn't finish",ex.Message);}
    }
    void Reset(string title,string text) {SetOptionsVisible(true);progress.Visible=false;percent.Visible=false;primary.Text="Try again";primary.Enabled=true;secondary.Text="Close";secondary.Enabled=true;detail.Text="INSTALL LOCATION\n"+Target;Transition(title,text);}
    static void EnsureClosed(){foreach(var p in Process.GetProcessesByName("ConvertANNY"))try{if(String.Equals(p.MainModule.FileName,Path.Combine(Target,"ConvertANNY.exe"),StringComparison.OrdinalIgnoreCase))throw new IOException("Close ConvertANNY, then try again.");}catch(System.ComponentModel.Win32Exception){} }
    static void InstallCore(bool explorer,bool desktop,Action<double,string> report,Func<bool> cancelled) {
        EnsureClosed();Directory.CreateDirectory(Path.GetDirectoryName(Target));
        string stage=Path.Combine(Path.GetDirectoryName(Target),".ConvertANNY-stage-"+Guid.NewGuid()),backup=Target+".backup-"+Guid.NewGuid();bool committed=false,backed=false;
        Directory.CreateDirectory(stage);
        try {
            using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip")) {
                if(stream==null)throw new IOException("The application payload is missing.");
                using(var zip=new ZipArchive(stream,ZipArchiveMode.Read)) {
                    long total=0,done=0;foreach(var entry in zip.Entries)total+=entry.Length;
                    byte[] buffer=new byte[262144];var throttle=Stopwatch.StartNew();
                    foreach(var entry in zip.Entries) {
                        if(cancelled())throw new OperationCanceledException();
                        string path=Path.GetFullPath(Path.Combine(stage,entry.FullName));
                        if(!path.StartsWith(stage+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new IOException("Invalid package path.");
                        if(entry.FullName.EndsWith("/")){Directory.CreateDirectory(path);continue;}
                        Directory.CreateDirectory(Path.GetDirectoryName(path));
                        using(var input=entry.Open())using(var output=File.Create(path)){int n;while((n=input.Read(buffer,0,buffer.Length))>0){if(cancelled())throw new OperationCanceledException();output.Write(buffer,0,n);done+=n;if(throttle.ElapsedMilliseconds>80){report(total>0?(double)done/total*.94:0,Path.GetFileName(path));throttle.Restart();}}}
                    }
                }
            }
            if(cancelled())throw new OperationCanceledException();EnsureClosed();
            if(!File.Exists(Path.Combine(stage,"ConvertANNY.exe")))throw new IOException("The package does not contain ConvertANNY.exe.");
            File.WriteAllText(Path.Combine(stage,".convertanny-install"),BuildInfo.Version);
            if(Directory.Exists(Target)){Directory.Move(Target,backup);backed=true;}
            try{Directory.Move(stage,Target);committed=true;}catch{if(backed&&!Directory.Exists(Target))Directory.Move(backup,Target);throw;}
            report(.96,"Windows shortcuts");
            string exe=Path.Combine(Target,"ConvertANNY.exe");
            if(desktop)Shortcut(DesktopLink,exe,"");Shortcut(StartLink,exe,"");
            if(explorer){RegisterExplorer(exe);Shortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.SendTo),"ConvertANNY.lnk"),exe,"");Shortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.SendTo),"Send to Phone using ConvertANNY.lnk"),exe,"--send-phone");}
            using(var key=Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\ConvertANNY")){key.SetValue("DisplayName","ConvertANNY");key.SetValue("DisplayVersion",BuildInfo.Version);key.SetValue("InstallLocation",Target);key.SetValue("DisplayIcon",exe);key.SetValue("UninstallString","\""+Path.Combine(Target,"Uninstall.exe")+"\"");key.SetValue("NoModify",1);key.SetValue("NoRepair",1);}
            if(backed) {
                // This may be an older, large install. Keep the final wait visible instead of
                // leaving the progress display parked on 99% with no explanation.
                report(.975,"Removing previous installation files");
                try{Directory.Delete(backup,true);}catch{}
            }
            report(1,"Complete");
        } finally {if(!committed&&Directory.Exists(stage))try{Directory.Delete(stage,true);}catch{};}
    }
    internal static string ExplorerCommand(string exe) {return "\""+exe+"\" --open \"%1\"";}
    static void RegisterExplorer(string exe) {
        foreach(string keyName in new[]{@"Software\Classes\*\shell\ConvertANNY",@"Software\Classes\Directory\shell\ConvertANNY"}) {
            using(var key=Registry.CurrentUser.CreateSubKey(keyName)){key.SetValue("MUIVerb","ConvertANNY");key.SetValue("Icon",exe+",0");key.SetValue("MultiSelectModel","Player");}
            using(var command=Registry.CurrentUser.CreateSubKey(keyName+@"\command"))command.SetValue("",ExplorerCommand(exe));
        }
        try{SHChangeNotify(0x08000000,0,IntPtr.Zero,IntPtr.Zero);}catch{}
    }
    [DllImport("shell32.dll")] static extern void SHChangeNotify(uint eventId,uint flags,IntPtr item1,IntPtr item2);
    static string DesktopLink {get{return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"ConvertANNY.lnk");}}
    static string StartLink {get{return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),"ConvertANNY.lnk");}}
    static void Shortcut(string path,string exe,string arguments) {Type type=Type.GetTypeFromProgID("WScript.Shell");dynamic shell=Activator.CreateInstance(type);dynamic link=shell.CreateShortcut(path);link.TargetPath=exe;link.Arguments=arguments;link.WorkingDirectory=Target;link.IconLocation=exe+",0";link.Save();}
    [STAThread] static int Main(string[] args) {Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(true);Application.Run(new Setup());return 0;}
    internal void PreviewComplete(){installed=true;SetOptionsVisible(false);heading.Text="Installed";description.Text="Right-click a file or folder and choose ConvertANNY to open the wheel.";primary.Text="Open ConvertANNY";secondary.Text="Close";progress.Visible=true;progress.Value=1;percent.Visible=true;percent.Text="100%   ·   Installation complete";}
}

class Card : Panel {
    public Card(){DoubleBuffered=true;BackColor=Color.FromArgb(24,25,29);}
    protected override void OnPaint(PaintEventArgs e){base.OnPaint(e);e.Graphics.SmoothingMode=SmoothingMode.AntiAlias;using(var path=Shapes.Round(new RectangleF(.5f,.5f,Width-1,Height-1),12))using(var pen=new Pen(Color.FromArgb(44,46,53)))e.Graphics.DrawPath(pen,path);}
}
class ActionButton : Control, IButtonControl {
    public bool Primary; bool hover; DialogResult dialogResult;
    public DialogResult DialogResult {get{return dialogResult;}set{dialogResult=value;}}
    public void NotifyDefault(bool value){} public void PerformClick(){if(Enabled)OnClick(EventArgs.Empty);}
    public ActionButton(){Cursor=Cursors.Hand;TabStop=true;SetStyle(ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer|ControlStyles.ResizeRedraw|ControlStyles.Selectable,true);}
    protected override void OnMouseEnter(EventArgs e){hover=true;Invalidate();base.OnMouseEnter(e);}
    protected override void OnMouseLeave(EventArgs e){hover=false;Invalidate();base.OnMouseLeave(e);}
    protected override void OnKeyDown(KeyEventArgs e){if(e.KeyCode==Keys.Enter||e.KeyCode==Keys.Space){OnClick(EventArgs.Empty);e.Handled=true;}base.OnKeyDown(e);}
    protected override void OnPaint(PaintEventArgs e){e.Graphics.SmoothingMode=SmoothingMode.AntiAlias;e.Graphics.PixelOffsetMode=PixelOffsetMode.HighQuality;e.Graphics.CompositingQuality=CompositingQuality.HighQuality;Color fill=Primary?(Enabled?(hover?Color.FromArgb(57,117,247):Color.FromArgb(37,99,235)):Color.FromArgb(35,52,86)):(hover?Color.FromArgb(43,45,52):Color.FromArgb(27,29,34));using(var path=Shapes.Round(new RectangleF(.75f,.75f,Width-1.5f,Height-1.5f),10))using(var brush=new SolidBrush(fill))e.Graphics.FillPath(brush,path);TextRenderer.DrawText(e.Graphics,Text,Font,ClientRectangle,Enabled?Color.White:Color.FromArgb(145,153,170),TextFormatFlags.HorizontalCenter|TextFormatFlags.VerticalCenter|TextFormatFlags.SingleLine|TextFormatFlags.NoPadding);if(Focused){using(var pen=new Pen(Color.FromArgb(115,155,245),1))using(var path=Shapes.Round(new RectangleF(2,2,Width-4,Height-4),8))e.Graphics.DrawPath(pen,path);}}
}
class Toggle : Control {
    bool value;public bool Checked {get{return value;}set{this.value=value;Invalidate();}}
    public Toggle(){Cursor=Cursors.Hand;TabStop=true;AccessibleRole=AccessibleRole.CheckButton;SetStyle(ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer|ControlStyles.ResizeRedraw|ControlStyles.Selectable,true);Click+=(s,e)=>Checked=!Checked;}
    protected override void OnKeyDown(KeyEventArgs e){if(e.KeyCode==Keys.Enter||e.KeyCode==Keys.Space){OnClick(EventArgs.Empty);e.Handled=true;}base.OnKeyDown(e);}
    protected override void OnPaint(PaintEventArgs e){e.Graphics.SmoothingMode=SmoothingMode.AntiAlias;e.Graphics.PixelOffsetMode=PixelOffsetMode.HighQuality;e.Graphics.CompositingQuality=CompositingQuality.HighQuality;float inset=1.25f,h=Height-2*inset;using(var path=Shapes.Round(new RectangleF(inset,inset,Width-2*inset,h),h/2))using(var brush=new SolidBrush(Checked?Color.FromArgb(37,99,235):Color.FromArgb(65,67,75)))e.Graphics.FillPath(brush,path);float d=h-4;float x=Checked?Width-inset-2-d:inset+2;using(var brush=new SolidBrush(Color.White))e.Graphics.FillEllipse(brush,x,inset+2,d,d);}
}
class AnimatedMark : PictureBox {
    readonly System.Windows.Forms.Timer timer=new System.Windows.Forms.Timer();
    Image[] frames=new Image[0];Image finalImage;int index;
    public AnimatedMark(){SetStyle(ControlStyles.OptimizedDoubleBuffer,true);timer.Interval=45;timer.Tick+=Advance;}
    public void SetReveal(Image[] images,Image fallback){frames=images;if(Image!=null)Image.Dispose();if(frames.Length>0){finalImage=new Bitmap(frames[frames.Length-1]);fallback.Dispose();}else finalImage=fallback;Image=finalImage;}
    public void PlayReveal(){if(frames.Length==0)return;index=0;Image=frames[0];timer.Start();}
    void Advance(object sender,EventArgs e){index=(index+1)%frames.Length;Image=frames[index];Invalidate();}
    protected override void Dispose(bool disposing){if(disposing){timer.Stop();timer.Dispose();foreach(var frame in frames)frame.Dispose();Image=null;if(finalImage!=null)finalImage.Dispose();}base.Dispose(disposing);}
}
class ProgressTrack : Control {
    float currentValue;
    public float Value { get { return currentValue; } set { float next=float.IsNaN(value)?0:Math.Max(0,Math.Min(1,value)); if(currentValue==next)return; currentValue=next; Invalidate(); } }
    public ProgressTrack(){DoubleBuffered=true;}
    protected override void OnPaint(PaintEventArgs e){e.Graphics.SmoothingMode=SmoothingMode.AntiAlias;using(var path=Shapes.Round(new RectangleF(0,0,Width,Height),Height/2f))using(var brush=new SolidBrush(Color.FromArgb(43,46,54)))e.Graphics.FillPath(brush,path);float width=Math.Max(0,Math.Min(1,Value))*Width;if(width>Height)using(var path=Shapes.Round(new RectangleF(0,0,width,Height),Height/2f))using(var brush=new SolidBrush(Color.FromArgb(62,129,255)))e.Graphics.FillPath(brush,path);}
}
static class Shapes {
    public static GraphicsPath Round(RectangleF r,float radius){var p=new GraphicsPath();float d=radius*2;p.AddArc(r.X,r.Y,d,d,180,90);p.AddArc(r.Right-d,r.Y,d,d,270,90);p.AddArc(r.Right-d,r.Bottom-d,d,d,0,90);p.AddArc(r.X,r.Bottom-d,d,d,90,90);p.CloseFigure();return p;}
}
