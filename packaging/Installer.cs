using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

internal sealed class InstallerForm : Form
{
    private readonly Label detail;
    private readonly Label status;
    private readonly ProgressBar progress;
    private readonly Button closeButton;

    [STAThread]
    private static void Main(string[] args)
    {
        if (Array.Exists(args, a => string.Equals(a, "--self-test-package", StringComparison.OrdinalIgnoreCase)))
        {
            Environment.ExitCode = RunPackageSelfTest();
            return;
        }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new InstallerForm());
    }

    private InstallerForm()
    {
        Text = "Iniciando SPPtab";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = true;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(510, 272);
        Font = new Font("Segoe UI", 9F);

        Label title = new Label { Left = 28, Top = 22, Width = 450, Height = 32, Text = "SPPtab para Windows", Font = new Font("Segoe UI Semibold", 16F) };
        detail = new Label { Left = 30, Top = 68, Width = 448, Height = 66, Text = "O aplicativo e seus componentes estão dentro deste executável. Vamos preparar o SPPtab automaticamente para esta conta do Windows." };
        progress = new ProgressBar { Left = 30, Top = 153, Width = 448, Height = 20, Style = ProgressBarStyle.Continuous };
        status = new Label { Left = 30, Top = 182, Width = 448, Height = 22, Text = "Preparando o aplicativo…" };
        closeButton = new Button { Left = 360, Top = 216, Width = 118, Height = 34, Text = "Fechar", Visible = false };
        closeButton.Click += delegate { Close(); };
        Controls.Add(title); Controls.Add(detail); Controls.Add(progress); Controls.Add(status); Controls.Add(closeButton);
        Shown += delegate { BeginInstall(); };
    }

    private void BeginInstall()
    {
        status.Text = "Preparando os arquivos do SPPtab…";
        BackgroundWorker worker = new BackgroundWorker();
        worker.WorkerReportsProgress = true;
        worker.DoWork += delegate(object sender, DoWorkEventArgs e) { InstallPayload((BackgroundWorker)sender); };
        worker.ProgressChanged += delegate(object sender, ProgressChangedEventArgs e)
        {
            progress.Value = Math.Max(0, Math.Min(100, e.ProgressPercentage));
            status.Text = e.UserState as string ?? "Instalando…";
        };
        worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs e)
        {
            if (e.Error != null)
            {
                status.Text = "Não foi possível preparar o SPPtab.";
                detail.Text = "Confira se há espaço livre no computador e tente executar este arquivo novamente.";
                closeButton.Visible = true;
                MessageBox.Show("Não foi possível preparar o SPPtab.\n\n" + e.Error.Message, "SPPtab", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
            progress.Value = 100;
            status.Text = "Abrindo o SPPtab…";
            detail.Text = "O aplicativo está pronto. Esta janela fechará quando o SPPtab abrir no navegador.";
            try
            {
                Process.Start(new ProcessStartInfo(Path.Combine(InstallDirectory, "SPPtab.exe")) { UseShellExecute = true });
                Close();
            }
            catch (Exception ex)
            {
                status.Text = "O SPPtab foi preparado, mas não abriu automaticamente.";
                detail.Text = "Use o atalho do SPPtab criado na Área de Trabalho.\n" + ex.Message;
                closeButton.Visible = true;
                MessageBox.Show("O SPPtab foi preparado. Use o atalho criado na Área de Trabalho para abri-lo.\n\n" + ex.Message, "SPPtab", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        };
        worker.RunWorkerAsync();
    }

    private static string InstallDirectory
    {
        get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "SPPtab"); }
    }

    private static string DataDirectory
    {
        get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SPPtab", "data"); }
    }

    private static void InstallPayload(BackgroundWorker worker)
    {
        Directory.CreateDirectory(InstallDirectory);
        Directory.CreateDirectory(DataDirectory);
        ExtractPayload(InstallDirectory, worker);
        worker.ReportProgress(94, "Criando atalhos…");
        CreateShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "SPPtab.lnk"));
        string startMenu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs", "SPPtab");
        Directory.CreateDirectory(startMenu);
        CreateShortcut(Path.Combine(startMenu, "SPPtab.lnk"));
        File.WriteAllText(Path.Combine(InstallDirectory, "LEIA-ME.txt"),
            "SPPtab\r\n\r\n" +
            "Use o atalho SPPtab. A janela pequena do iniciador deve ficar aberta enquanto o sistema estiver em uso.\r\n" +
            "O app busca bases e definições oficiais pela internet. Arquivos e resultados ficam em %LOCALAPPDATA%\\SPPtab\\data.\r\n" +
            "Para encerrar o serviço local, feche a janela do iniciador.\r\n", System.Text.Encoding.UTF8);
        worker.ReportProgress(100, "Pronto.");
    }

    private static void ExtractPayload(string targetDirectory, BackgroundWorker worker)
    {
        using (Stream source = Assembly.GetExecutingAssembly().GetManifestResourceStream("SPPtab.Payload.zip"))
        {
            if (source == null) throw new InvalidOperationException("O pacote de instalação está incompleto.");
            using (ZipArchive archive = new ZipArchive(source, ZipArchiveMode.Read, false))
            {
                int total = Math.Max(1, archive.Entries.Count);
                for (int i = 0; i < archive.Entries.Count; i++)
                {
                    ZipArchiveEntry entry = archive.Entries[i];
                    string relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar);
                    string destination = Path.GetFullPath(Path.Combine(targetDirectory, relative));
                    string root = targetDirectory.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
                    if (!destination.StartsWith(root, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("O instalador contém um caminho inválido.");
                    if (entry.FullName.EndsWith("/", StringComparison.Ordinal) || entry.FullName.EndsWith("\\", StringComparison.Ordinal))
                        Directory.CreateDirectory(destination);
                    else
                    {
                        string parent = Path.GetDirectoryName(destination);
                        if (!Directory.Exists(parent)) Directory.CreateDirectory(parent);
                        using (Stream input = entry.Open())
                        using (FileStream output = new FileStream(destination, FileMode.Create, FileAccess.Write, FileShare.None)) input.CopyTo(output);
                    }
                    if (worker != null && i % 12 == 0) worker.ReportProgress((i + 1) * 92 / total, "Copiando arquivos do app…");
                }
            }
        }
    }

    private static int RunPackageSelfTest()
    {
        string testRoot = Path.Combine(Path.GetTempPath(), "TabWin2-package-test-" + Guid.NewGuid().ToString("N"));
        string logPath = Path.Combine(Path.GetTempPath(), "TabWin2-installer-selftest.log");
        try
        {
            Directory.CreateDirectory(testRoot);
            ExtractPayload(testRoot, null);
            ProcessStartInfo start = new ProcessStartInfo(Path.Combine(testRoot, "SPPtab.exe"), "--self-test");
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            using (Process process = Process.Start(start))
            {
                if (process == null || !process.WaitForExit(45000)) throw new InvalidOperationException("O teste do app extraído excedeu 45 segundos.");
                string appLog = Path.Combine(Path.GetTempPath(), "TabWin2-selftest.log");
                string result = File.Exists(appLog) ? File.ReadAllText(appLog) : "O iniciador não retornou o resultado do teste.";
                if (process.ExitCode != 0) throw new InvalidOperationException(result);
                File.WriteAllText(logPath, "OK: instalador abriu, extraiu os arquivos e iniciou a cópia portátil.\r\n" + result);
                return 0;
            }
        }
        catch (Exception ex)
        {
            File.WriteAllText(logPath, "FALHA: " + ex.Message);
            return 1;
        }
        finally
        {
            try { if (Directory.Exists(testRoot)) Directory.Delete(testRoot, true); } catch { }
        }
    }

    private static void CreateShortcut(string path)
    {
        Type shellType = Type.GetTypeFromProgID("WScript.Shell");
        if (shellType == null) throw new InvalidOperationException("O Windows não permitiu criar o atalho.");
        object shell = Activator.CreateInstance(shellType);
        object shortcut = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
        Type shortcutType = shortcut.GetType();
        shortcutType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { Path.Combine(InstallDirectory, "SPPtab.exe") });
        shortcutType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { InstallDirectory });
        shortcutType.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { "SPPtab — aplicativo de tabulação local" });
        shortcutType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { Path.Combine(Environment.SystemDirectory, "imageres.dll") + ",68" });
        shortcutType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
    }
}
