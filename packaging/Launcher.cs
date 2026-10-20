using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

internal static class LauncherProgram
{
    private static readonly string BaseDirectory = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    private static Process server;
    private static int port;
    private static string dataDirectory;
    private static string logPath;
    private static string selfTestLogDirectory;
    private static CookieContainer selfTestCookies = new CookieContainer();
    private static string selfTestCsrfToken = String.Empty;
    private static readonly object logLock = new object();

    [STAThread]
    private static int Main(string[] args)
    {
        bool selfTest = Array.Exists(args, a => string.Equals(a, "--self-test", StringComparison.OrdinalIgnoreCase));
        try
        {
            if (selfTest) return RunSelfTest();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new LauncherForm());
            return 0;
        }
        catch (Exception ex)
        {
            MessageBox.Show("Não foi possível iniciar o SPPtab.\n\n" + ex.Message,
                "SPPtab", MessageBoxButtons.OK, MessageBoxIcon.Error);
            StopServer();
            return 1;
        }
    }

    private static string PhpPath { get { return Path.Combine(BaseDirectory, "runtime", "php", "php.exe"); } }
    private static string IniPath { get { return Path.Combine(BaseDirectory, "runtime", "php", "php.ini"); } }
    private static string PythonPath { get { return Path.Combine(BaseDirectory, "runtime", "python", "python.exe"); } }
    private static string AppPath { get { return Path.Combine(BaseDirectory, "app"); } }

    private static bool CanWriteToDirectory(string path)
    {
        string probe = Path.Combine(path, ".tabwin2-write-" + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            Directory.CreateDirectory(path);
            using (FileStream stream = new FileStream(probe, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                stream.WriteByte(0);
            File.Delete(probe);
            return true;
        }
        catch
        {
            try { if (File.Exists(probe)) File.Delete(probe); } catch { }
            return false;
        }
    }

    private static string ResolveDataDirectory()
    {
        string adjacent = Path.Combine(BaseDirectory, "data");
        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string current = Path.Combine(localAppData, "SPPtab", "data");
        string legacy = Path.Combine(localAppData, "TabWin2-Teste", "data");

        // Keep using an existing library when moving from the installer to the portable folder.
        if (Directory.Exists(adjacent) && CanWriteToDirectory(adjacent)) return adjacent;
        if (Directory.Exists(legacy) && CanWriteToDirectory(legacy)) return legacy;
        if (Directory.Exists(current) && CanWriteToDirectory(current)) return current;
        if (CanWriteToDirectory(adjacent)) return adjacent;
        if (CanWriteToDirectory(current)) return current;
        if (CanWriteToDirectory(legacy)) return legacy;
        return current;
    }

    private static void StartServer(bool selfTest)
    {
        if (!File.Exists(PhpPath) || !File.Exists(PythonPath) || !File.Exists(Path.Combine(AppPath, "index.php")) || !File.Exists(Path.Combine(AppPath, "bases.php")) || !File.Exists(Path.Combine(AppPath, "tabular.php")))
            throw new InvalidOperationException("A instalação está incompleta. Execute novamente o instalador do SPPtab.");

        if (selfTest)
            dataDirectory = Path.Combine(Path.GetTempPath(), "TabWin2-selftest-" + Guid.NewGuid().ToString("N"));
        else
            dataDirectory = ResolveDataDirectory();
        Directory.CreateDirectory(dataDirectory);
        string logDirectory;
        if (selfTest)
        {
            selfTestLogDirectory = Path.Combine(Path.GetTempPath(), "SPPtab-selftest-logs-" + Guid.NewGuid().ToString("N"));
            logDirectory = selfTestLogDirectory;
        }
        else
        {
            logDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SPPtab", "logs");
        }
        Directory.CreateDirectory(logDirectory);
        logPath = Path.Combine(logDirectory, "php-server.log");
        port = GetAvailablePort();

        ProcessStartInfo start = new ProcessStartInfo();
        start.FileName = PhpPath;
        start.Arguments = "-c " + Quote(IniPath) + " -S 127.0.0.1:" + port + " -t " + Quote(AppPath) + " " + Quote(Path.Combine(AppPath, "packaging", "router.php"));
        start.WorkingDirectory = AppPath;
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        start.EnvironmentVariables["TABWIN2_PYTHON"] = PythonPath;
        start.EnvironmentVariables["TABWIN2_DATA_DIR"] = dataDirectory;
        start.EnvironmentVariables["TABWIN2_ALLOWED_HOSTS"] = "127.0.0.1:" + port;
        start.EnvironmentVariables["PHPRC"] = IniPath;
        start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        start.EnvironmentVariables["PATH"] = Path.Combine(BaseDirectory, "runtime", "php") + ";" +
            Path.Combine(BaseDirectory, "runtime", "python") + ";" + Environment.SystemDirectory + ";" +
            Path.Combine(Environment.GetEnvironmentVariable("WINDIR") ?? "C:\\Windows", "System32");

        server = new Process();
        server.StartInfo = start;
        server.EnableRaisingEvents = true;
        server.OutputDataReceived += LogLine;
        server.ErrorDataReceived += LogLine;
        if (!server.Start()) throw new InvalidOperationException("O serviço local não iniciou.");
        server.BeginOutputReadLine();
        server.BeginErrorReadLine();
    }

    private static void LogLine(object sender, DataReceivedEventArgs e)
    {
        if (string.IsNullOrEmpty(e.Data) || string.IsNullOrEmpty(logPath)) return;
        try
        {
            lock (logLock) File.AppendAllText(logPath, DateTime.Now.ToString("s") + " " + e.Data + Environment.NewLine, Encoding.UTF8);
        }
        catch { }
    }

    private static int GetAvailablePort()
    {
        TcpListener listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        int selected = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return selected;
    }

    private static string Quote(string value) { return "\"" + value.Replace("\"", "\\\"") + "\""; }
    private static string BaseUrl { get { return "http://127.0.0.1:" + port + "/"; } }

    private static string Request(string relative, string method, string body, int timeout)
    {
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create(BaseUrl + relative);
        request.Method = method;
        request.Timeout = timeout;
        request.ReadWriteTimeout = timeout;
        request.Proxy = null;
        request.CookieContainer = selfTestCookies;
        if (body != null)
        {
            request.Headers["Origin"] = "http://127.0.0.1:" + port;
            if (!String.IsNullOrEmpty(selfTestCsrfToken)) request.Headers["X-SPPtab-CSRF"] = selfTestCsrfToken;
            byte[] bytes = Encoding.UTF8.GetBytes(body);
            request.ContentType = "application/json; charset=utf-8";
            request.ContentLength = bytes.Length;
            using (Stream stream = request.GetRequestStream()) stream.Write(bytes, 0, bytes.Length);
        }
        using (WebResponse response = request.GetResponse())
        using (Stream stream = response.GetResponseStream())
        using (StreamReader reader = new StreamReader(stream, Encoding.UTF8))
        {
            string content = reader.ReadToEnd();
            if (method == "GET" && relative == "")
            {
                Match match = Regex.Match(content, "name=\\\"csrf-token\\\" content=\\\"([a-f0-9]{64})\\\"", RegexOptions.IgnoreCase);
                if (match.Success) selfTestCsrfToken = match.Groups[1].Value;
            }
            return content;
        }
    }

    private static bool WaitForServer(int seconds)
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(seconds);
        while (DateTime.UtcNow < deadline)
        {
            if (server == null || server.HasExited) return false;
            try
            {
                string health = Request("__tabwin2_health", "GET", null, 800);
                if (health.Contains("\"ok\":true")) return true;
            }
            catch { Thread.Sleep(250); }
        }
        return false;
    }

    private static void OpenApp()
    {
        Process.Start(new ProcessStartInfo(BaseUrl) { UseShellExecute = true });
    }

    private static void StopServer()
    {
        try
        {
            if (server != null && !server.HasExited)
            {
                server.Kill();
                server.WaitForExit(3000);
            }
        }
        catch { }
        finally
        {
            try { if (server != null) server.Dispose(); } catch { }
            server = null;
        }
    }

    private static int RunSelfTest()
    {
        string resultFile = Path.Combine(Path.GetTempPath(), "TabWin2-selftest.log");
        try
        {
            selfTestCookies = new CookieContainer();
            selfTestCsrfToken = String.Empty;
            StartServer(true);
            if (!WaitForServer(12)) throw new InvalidOperationException("O serviço PHP não respondeu em 12 segundos.");
            string html = Request("", "GET", null, 5000);
            if (!html.ToLowerInvariant().Contains("spptab") || String.IsNullOrEmpty(selfTestCsrfToken)) throw new InvalidOperationException("A página inicial ou a proteção de sessão não carregou corretamente.");
            string css = Request("assets/app.css", "GET", null, 5000);
            string js = Request("assets/app.js", "GET", null, 5000);
            if (css.Length < 1000 || !css.Contains("{") || js.Length < 1000)
                throw new InvalidOperationException("Os arquivos visuais (CSS/JavaScript) não foram carregados corretamente.");
            string validCsrfToken = selfTestCsrfToken;
            selfTestCsrfToken = String.Empty;
            try
            {
                Request("api.php", "POST", "{\"action\":\"catalog\"}", 5000);
                throw new InvalidOperationException("A API aceitou uma chamada sem token CSRF.");
            }
            catch (WebException ex)
            {
                HttpWebResponse response = ex.Response as HttpWebResponse;
                if (response == null || response.StatusCode != HttpStatusCode.Forbidden)
                    throw new InvalidOperationException("A API não bloqueou a chamada sem token CSRF.");
                response.Close();
            }
            finally { selfTestCsrfToken = validCsrfToken; }
            string catalog = Request("api.php", "POST", "{\"action\":\"catalog\"}", 15000);
            if (!catalog.Contains("\"ok\":true") || !(catalog.Contains("\"files\": []") || catalog.Contains("\"files\":[]")))
                throw new InvalidOperationException("A API não conseguiu chamar o mecanismo Python: " + catalog);
            foreach (string blocked in new string[] { "engine/tabulation.py", "uploads/manifest.json", "packaging/router.php" })
            {
                try { Request(blocked, "GET", null, 3000); throw new InvalidOperationException("A rota privada ficou pública: " + blocked); }
                catch (WebException ex)
                {
                    HttpWebResponse response = ex.Response as HttpWebResponse;
                    if (response == null || response.StatusCode != HttpStatusCode.NotFound)
                        throw new InvalidOperationException("A rota privada não foi bloqueada: " + blocked);
                    response.Close();
                }
            }
            string success = "OK: PHP iniciado, tela e arquivos visuais carregados, PHP chamou o Python empacotado e caminhos internos retornaram 404.";
            File.WriteAllText(resultFile, success, Encoding.UTF8);
            Console.WriteLine(success);
            return 0;
        }
        catch (Exception ex)
        {
            string failure = "FALHA: " + ex.Message;
            if (!string.IsNullOrEmpty(logPath) && File.Exists(logPath)) failure += Environment.NewLine + File.ReadAllText(logPath);
            try { File.WriteAllText(resultFile, failure, Encoding.UTF8); } catch { }
            Console.Error.WriteLine(failure);
            return 1;
        }
        finally
        {
            StopServer();
            try { if (dataDirectory != null && dataDirectory.Contains("TabWin2-selftest-")) Directory.Delete(dataDirectory, true); } catch { }
            try
            {
                if (!string.IsNullOrEmpty(selfTestLogDirectory) && selfTestLogDirectory.StartsWith(Path.GetTempPath(), StringComparison.OrdinalIgnoreCase) && Directory.Exists(selfTestLogDirectory))
                    Directory.Delete(selfTestLogDirectory, true);
            }
            catch { }
        }
    }

    private sealed class LauncherForm : Form
    {
        private readonly Label status;
        private readonly Button open;
        private readonly Button close;
        private readonly NotifyIcon trayIcon;
        private bool startupStarted;
        private bool allowExit;
        private bool startupFailed;
        private bool trayNoticeShown;

        public LauncherForm()
        {
            Text = "SPPtab";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = true;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(410, 174);
            Font = new Font("Segoe UI", 9F);
            status = new Label { Left = 24, Top = 24, Width = 360, Height = 46, Text = "Iniciando o SPPtab…" };
            open = new Button { Left = 24, Top = 88, Width = 170, Height = 38, Text = "Abrir no navegador", Enabled = false };
            close = new Button { Left = 210, Top = 88, Width = 170, Height = 38, Text = "Encerrar SPPtab" };
            open.Click += delegate { try { OpenApp(); } catch (Exception ex) { MessageBox.Show(ex.Message); } };
            close.Click += delegate { allowExit = true; Close(); };
            Controls.Add(status); Controls.Add(open); Controls.Add(close);

            ContextMenuStrip trayMenu = new ContextMenuStrip();
            trayMenu.Items.Add("Abrir SPPtab no navegador", null, delegate { try { OpenApp(); } catch (Exception ex) { MessageBox.Show(ex.Message); } });
            trayMenu.Items.Add("Mostrar esta janela", null, delegate { RestoreLauncher(); });
            trayMenu.Items.Add(new ToolStripSeparator());
            trayMenu.Items.Add("Encerrar SPPtab", null, delegate { allowExit = true; Close(); });
            trayIcon = new NotifyIcon
            {
                Icon = SystemIcons.Application,
                Text = "SPPtab em execução",
                ContextMenuStrip = trayMenu,
                Visible = true
            };
            trayIcon.DoubleClick += delegate { RestoreLauncher(); };

            Load += delegate { if (!startupStarted) { startupStarted = true; StartInBackground(); } };
            FormClosing += delegate(object sender, FormClosingEventArgs e)
            {
                if (!allowExit && !startupFailed && e.CloseReason == CloseReason.UserClosing)
                {
                    e.Cancel = true;
                    Hide();
                    if (!trayNoticeShown)
                    {
                        trayIcon.BalloonTipTitle = "SPPtab continua ativo";
                        trayIcon.BalloonTipText = "O sistema segue aberto no navegador. Use o ícone do SPPtab perto do relógio para reabrir ou encerrar.";
                        trayIcon.ShowBalloonTip(3500);
                        trayNoticeShown = true;
                    }
                    return;
                }

                trayIcon.Visible = false;
                trayIcon.Dispose();
                StopServer();
            };
        }

        private void RestoreLauncher()
        {
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Show();
            Activate();
        }

        private void StartInBackground()
        {
            Thread worker = new Thread(delegate()
            {
                try
                {
                    StartServer(false);
                    if (!WaitForServer(15)) throw new InvalidOperationException("O serviço local não respondeu. Verifique o log em AppData\\Local\\SPPtab\\logs.");
                    BeginInvoke((MethodInvoker)delegate
                    {
                        status.Text = "SPPtab está funcionando neste computador.\nO X recolhe para a bandeja; use Encerrar para desligar.";
                        open.Enabled = true;
                        try { OpenApp(); } catch (Exception ex) { status.Text += "\nAbra pelo botão. " + ex.Message; }
                    });
                }
                catch (Exception ex)
                {
                    BeginInvoke((MethodInvoker)delegate
                    {
                        startupFailed = true;
                        trayIcon.Visible = false;
                        status.Text = "Não foi possível iniciar o SPPtab.\n" + ex.Message;
                        close.Text = "Fechar";
                    });
                }
            });
            worker.IsBackground = true;
            worker.Start();
        }
    }
}
