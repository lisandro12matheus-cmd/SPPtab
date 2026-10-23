using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

internal static class LauncherProgram
{
    private static readonly string BaseDirectory = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    private const string Repository = "lisandro12matheus-cmd/SPPtab";
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
            if (args.Length > 0 && string.Equals(args[0], "--apply-update", StringComparison.OrdinalIgnoreCase))
                return ApplyUpdate(args);
            if (selfTest) return RunSelfTest();
            RefreshShortcutIcons();
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

    private static void RefreshShortcutIcons()
    {
        try
        {
            string executable = Path.GetFullPath(Path.Combine(BaseDirectory, "SPPtab.exe"));
            string[] shortcuts = new string[]
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "SPPtab.lnk"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs", "SPPtab", "SPPtab.lnk")
            };
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            if (shellType == null) return;
            object shell = Activator.CreateInstance(shellType);
            foreach (string path in shortcuts)
            {
                if (!File.Exists(path)) continue;
                object shortcut = shellType.InvokeMember("CreateShortcut", System.Reflection.BindingFlags.InvokeMethod, null, shell, new object[] { path });
                Type shortcutType = shortcut.GetType();
                string target = shortcutType.InvokeMember("TargetPath", System.Reflection.BindingFlags.GetProperty, null, shortcut, null) as string;
                if (String.IsNullOrEmpty(target) || !String.Equals(Path.GetFullPath(target), executable, StringComparison.OrdinalIgnoreCase)) continue;
                string iconLocation = shortcutType.InvokeMember("IconLocation", System.Reflection.BindingFlags.GetProperty, null, shortcut, null) as string;
                string expectedIcon = executable + ",0";
                if (!String.Equals(iconLocation, expectedIcon, StringComparison.OrdinalIgnoreCase))
                {
                    shortcutType.InvokeMember("IconLocation", System.Reflection.BindingFlags.SetProperty, null, shortcut, new object[] { expectedIcon });
                    shortcutType.InvokeMember("Save", System.Reflection.BindingFlags.InvokeMethod, null, shortcut, null);
                }
            }
        }
        catch { }
    }

    private static string CurrentVersion
    {
        get
        {
            try { return File.ReadAllText(Path.Combine(BaseDirectory, "VERSION.txt")).Trim(); }
            catch { return "0.0.0"; }
        }
    }

    private static string DownloadText(string url, int timeoutMilliseconds)
    {
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
        request.Method = "GET";
        request.UserAgent = "SPPtab-Updater";
        request.Timeout = timeoutMilliseconds;
        request.ReadWriteTimeout = timeoutMilliseconds;
        request.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate;
        if (url.IndexOf("api.github.com", StringComparison.OrdinalIgnoreCase) >= 0)
            request.Accept = "application/vnd.github+json";
        using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
        using (Stream stream = response.GetResponseStream())
        using (StreamReader reader = new StreamReader(stream, Encoding.UTF8))
            return reader.ReadToEnd();
    }

    private static string ReleaseUrl(string tag, string asset)
    {
        return "https://github.com/" + Repository + "/releases/download/" + Uri.EscapeDataString(tag) + "/" + asset;
    }

    private static bool TryGetLatestVersion(out string tag, out string version)
    {
        tag = String.Empty;
        version = String.Empty;
        ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
        string json = DownloadText("https://api.github.com/repos/" + Repository + "/releases/latest", 10000);
        Match match = Regex.Match(json, "\"tag_name\"\\s*:\\s*\"([^\"]+)\"", RegexOptions.IgnoreCase);
        if (!match.Success) return false;
        tag = match.Groups[1].Value;
        string numeric = tag.StartsWith("v", StringComparison.OrdinalIgnoreCase) ? tag.Substring(1) : tag;
        Version parsed;
        if (!Version.TryParse(numeric, out parsed)) return false;
        version = parsed.ToString();
        return true;
    }

    private static bool IsNewerVersion(string latest, string current)
    {
        Version latestVersion, currentVersion;
        return Version.TryParse(latest, out latestVersion) && Version.TryParse(current, out currentVersion) && latestVersion > currentVersion;
    }

    private static string Sha256File(string path)
    {
        using (SHA256 sha = SHA256.Create())
        using (FileStream stream = File.OpenRead(path))
        {
            byte[] hash = sha.ComputeHash(stream);
            StringBuilder result = new StringBuilder(hash.Length * 2);
            foreach (byte value in hash) result.Append(value.ToString("x2"));
            return result.ToString();
        }
    }

    private static int ApplyUpdate(string[] args)
    {
        string log = Path.Combine(Path.GetTempPath(), "SPPtab-update.log");
        string stage = null;
        string backup = null;
        List<string> installedDirectories = new List<string>();
        List<string> installedFiles = new List<string>();
        List<string> backedUpDirectories = new List<string>();
        List<string> backedUpFiles = new List<string>();
        try
        {
            if (args.Length != 5) throw new InvalidOperationException("Os dados da atualização estão incompletos.");
            string archivePath = args[1];
            string expectedHash = args[2].Trim().ToLowerInvariant();
            int parentId;
            if (!Int32.TryParse(args[3], out parentId)) throw new InvalidOperationException("Não foi possível identificar o iniciador atual.");
            string destinationRoot = Path.GetFullPath(args[4]).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (!File.Exists(archivePath) || !Directory.Exists(destinationRoot)) throw new InvalidOperationException("O pacote ou a pasta do SPPtab não está disponível.");
            if (new FileInfo(archivePath).Length > 1024L * 1024 * 1024) throw new InvalidOperationException("O pacote de atualização excede o tamanho permitido.");
            if (!File.Exists(Path.Combine(destinationRoot, "SPPtab.exe"))) throw new InvalidOperationException("A pasta escolhida não parece conter uma instalação do SPPtab.");
            if (!Regex.IsMatch(expectedHash, "^[a-f0-9]{64}$") || !String.Equals(Sha256File(archivePath), expectedHash, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("A conferência de integridade do pacote falhou. O SPPtab não foi alterado.");

            try
            {
                using (Process parent = Process.GetProcessById(parentId))
                    if (!parent.WaitForExit(120000)) throw new InvalidOperationException("O SPPtab ainda está encerrando. Tente atualizar novamente.");
            }
            catch (ArgumentException) { }

            string id = Guid.NewGuid().ToString("N");
            stage = Path.Combine(destinationRoot, ".spptab-update-stage-" + id);
            backup = Path.Combine(destinationRoot, ".spptab-update-backup-" + id);
            string payloadRoot = Path.Combine(stage, "SPPtab");
            Directory.CreateDirectory(payloadRoot);
            Directory.CreateDirectory(backup);

            using (ZipArchive archive = ZipFile.OpenRead(archivePath))
            {
                if (archive.Entries.Count > 20000) throw new InvalidOperationException("O pacote de atualização contém itens demais.");
                long extractedBytes = 0;
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    if (entry.Length > 1024L * 1024 * 1024 || extractedBytes > 3L * 1024 * 1024 * 1024 - entry.Length)
                        throw new InvalidOperationException("O pacote de atualização excede o limite de extração.");
                    extractedBytes += entry.Length;
                    string name = entry.FullName.Replace('/', '\\');
                    if (name.IndexOf(':') >= 0 || name.IndexOf('\0') >= 0)
                        throw new InvalidOperationException("O pacote contém um nome de arquivo inválido.");
                    if (!name.StartsWith("SPPtab\\", StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException("O pacote contém um caminho inesperado.");
                    string relative = name.Substring("SPPtab\\".Length);
                    if (String.IsNullOrEmpty(relative)) continue;
                    string normalized = relative.Replace('\\', '/');
                    bool allowed = normalized.StartsWith("app/", StringComparison.OrdinalIgnoreCase) ||
                        normalized.StartsWith("runtime/", StringComparison.OrdinalIgnoreCase) ||
                        normalized.Equals("SPPtab.exe", StringComparison.OrdinalIgnoreCase) ||
                        normalized.Equals("VERSION.txt", StringComparison.OrdinalIgnoreCase) ||
                        normalized.Equals("LEIA-ME.txt", StringComparison.OrdinalIgnoreCase) ||
                        normalized.Equals("PHP-LICENSE.txt", StringComparison.OrdinalIgnoreCase) ||
                        normalized.Equals("PYTHON-LICENSE.txt", StringComparison.OrdinalIgnoreCase) ||
                        normalized.Equals("VC-RUNTIME-NOTICE.txt", StringComparison.OrdinalIgnoreCase);
                    if (!allowed) throw new InvalidOperationException("O pacote contém um arquivo fora da área atualizável.");
                    string output = Path.GetFullPath(Path.Combine(payloadRoot, relative));
                    string payloadPrefix = payloadRoot.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
                    if (!output.StartsWith(payloadPrefix, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException("O pacote contém um caminho inválido.");
                    if (entry.FullName.EndsWith("/", StringComparison.Ordinal) || entry.FullName.EndsWith("\\", StringComparison.Ordinal))
                    {
                        Directory.CreateDirectory(output);
                        continue;
                    }
                    Directory.CreateDirectory(Path.GetDirectoryName(output));
                    using (Stream input = entry.Open())
                    using (FileStream file = new FileStream(output, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                        input.CopyTo(file);
                }
            }

            foreach (string required in new string[] { "SPPtab.exe", "VERSION.txt", "runtime\\php\\php.exe", "runtime\\python\\python.exe", "app\\index.php" })
                if (!File.Exists(Path.Combine(payloadRoot, required))) throw new InvalidOperationException("O pacote está incompleto: " + required);

            string[] directoryNames = new string[] { "app", "runtime" };
            foreach (string name in directoryNames)
            {
                string current = Path.Combine(destinationRoot, name);
                string fresh = Path.Combine(payloadRoot, name);
                string saved = Path.Combine(backup, name);
                if (Directory.Exists(current) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidOperationException("A pasta " + name + " é um atalho de sistema e não pode ser atualizada com segurança.");
                if (Directory.Exists(current)) { Directory.Move(current, saved); backedUpDirectories.Add(name); }
                Directory.Move(fresh, current);
                installedDirectories.Add(name);
            }

            string[] fileNames = new string[] { "SPPtab.exe", "VERSION.txt", "LEIA-ME.txt", "PHP-LICENSE.txt", "PYTHON-LICENSE.txt", "VC-RUNTIME-NOTICE.txt" };
            foreach (string name in fileNames)
            {
                string current = Path.Combine(destinationRoot, name);
                string fresh = Path.Combine(payloadRoot, name);
                if (!File.Exists(fresh)) continue;
                string saved = Path.Combine(backup, name);
                if (File.Exists(current)) { File.Move(current, saved); backedUpFiles.Add(name); }
                File.Move(fresh, current);
                installedFiles.Add(name);
            }

            File.WriteAllText(log, "Atualização concluída para v" + File.ReadAllText(Path.Combine(destinationRoot, "VERSION.txt")).Trim(), Encoding.UTF8);
            Process.Start(new ProcessStartInfo(Path.Combine(destinationRoot, "SPPtab.exe"))
            {
                UseShellExecute = true,
                WorkingDirectory = destinationRoot
            });
            try { Directory.Delete(backup, true); } catch { }
            try { Directory.Delete(stage, true); } catch { }
            try { File.Delete(archivePath); } catch { }
            return 0;
        }
        catch (Exception ex)
        {
            for (int i = installedFiles.Count - 1; i >= 0; i--)
                try { File.Delete(Path.Combine(args.Length > 4 ? args[4] : BaseDirectory, installedFiles[i])); } catch { }
            for (int i = installedDirectories.Count - 1; i >= 0; i--)
                try { Directory.Delete(Path.Combine(args.Length > 4 ? args[4] : BaseDirectory, installedDirectories[i]), true); } catch { }
            for (int i = backedUpFiles.Count - 1; i >= 0; i--)
                try { File.Move(Path.Combine(backup, backedUpFiles[i]), Path.Combine(args[4], backedUpFiles[i])); } catch { }
            for (int i = backedUpDirectories.Count - 1; i >= 0; i--)
                try { Directory.Move(Path.Combine(backup, backedUpDirectories[i]), Path.Combine(args[4], backedUpDirectories[i])); } catch { }
            try { File.WriteAllText(log, "Falha ao atualizar: " + ex, Encoding.UTF8); } catch { }
            MessageBox.Show("Não foi possível concluir a atualização. Seus dados foram preservados.\n\n" + ex.Message + "\n\nO SPPtab anterior será iniciado novamente.", "Atualização do SPPtab", MessageBoxButtons.OK, MessageBoxIcon.Error);
            try
            {
                string root = args.Length > 4 ? Path.GetFullPath(args[4]) : BaseDirectory;
                string launcher = Path.Combine(root, "SPPtab.exe");
                if (File.Exists(launcher)) Process.Start(new ProcessStartInfo(launcher) { UseShellExecute = true, WorkingDirectory = root });
            }
            catch { }
            try { if (!String.IsNullOrEmpty(stage) && Directory.Exists(stage)) Directory.Delete(stage, true); } catch { }
            return 1;
        }
    }

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
        private readonly Label statusDetail;
        private readonly Label updateStatus;
        private readonly Panel statusDot;
        private readonly Button open;
        private readonly Button close;
        private readonly Button update;
        private readonly NotifyIcon trayIcon;
        private readonly Icon appIcon;
        private bool startupStarted;
        private bool allowExit;
        private bool startupFailed;
        private bool trayNoticeShown;
        private bool updateCheckRunning;
        private string availableTag;
        private string availableVersion;

        public LauncherForm()
        {
            Text = "SPPtab";
            appIcon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath) ?? SystemIcons.Application;
            Icon = appIcon;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = true;
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.Font;
            Font = new Font("Segoe UI", 9F);
            ClientSize = new Size(500, 320);
            BackColor = Color.FromArgb(245, 248, 252);

            Panel header = new Panel { Left = 0, Top = 0, Width = 500, Height = 101, BackColor = Color.White };
            PictureBox logo = new PictureBox { Left = 23, Top = 20, Width = 60, Height = 60, SizeMode = PictureBoxSizeMode.Zoom };
            try
            {
                using (Icon largeIcon = new Icon(Path.Combine(AppPath, "assets", "spptab-icon.ico"), new Size(64, 64)))
                    logo.Image = largeIcon.ToBitmap();
            }
            catch { logo.Image = appIcon.ToBitmap(); }
            Label title = new Label { Left = 96, Top = 25, Width = 250, Height = 35, Text = "SPPtab", ForeColor = Color.FromArgb(16, 47, 72), Font = new Font("Segoe UI", 19F, FontStyle.Bold) };
            Label tagline = new Label { Left = 98, Top = 61, Width = 250, Height = 20, Text = "SAÚDE EM DADOS", ForeColor = Color.FromArgb(111, 133, 153), Font = new Font("Segoe UI", 8F, FontStyle.Bold) };
            Label version = new Label { Left = 379, Top = 36, Width = 96, Height = 23, Text = "v" + CurrentVersion, TextAlign = ContentAlignment.MiddleRight, ForeColor = Color.FromArgb(77, 108, 137), Font = new Font("Segoe UI", 9F) };
            header.Controls.Add(logo);
            header.Controls.Add(title);
            header.Controls.Add(tagline);
            header.Controls.Add(version);
            Controls.Add(header);
            Controls.Add(new Panel { Left = 0, Top = 100, Width = 500, Height = 1, BackColor = Color.FromArgb(222, 232, 243) });

            statusDot = new Panel { Left = 25, Top = 131, Width = 8, Height = 8, BackColor = Color.FromArgb(51, 128, 229) };
            status = new Label { Left = 43, Top = 119, Width = 430, Height = 28, Text = "Preparando o SPPtab…", ForeColor = Color.FromArgb(17, 48, 71), Font = new Font("Segoe UI", 11F, FontStyle.Bold) };
            statusDetail = new Label { Left = 25, Top = 149, Width = 450, Height = 33, Text = "Iniciando seu espaço de trabalho neste computador.", ForeColor = Color.FromArgb(99, 120, 138) };
            Panel updatePanel = new Panel { Left = 24, Top = 190, Width = 452, Height = 62, BackColor = Color.White, BorderStyle = BorderStyle.FixedSingle };
            updateStatus = new Label { Left = 13, Top = 10, Width = 314, Height = 42, Text = "Verificando se há uma versão mais recente…", ForeColor = Color.FromArgb(76, 102, 127) };
            update = new Button { Left = 346, Top = 12, Width = 91, Height = 36, Text = "Atualizar", Visible = false, Enabled = false, FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(45, 112, 218), ForeColor = Color.White, Font = new Font("Segoe UI", 9F, FontStyle.Bold) };
            update.FlatAppearance.BorderSize = 0;
            updatePanel.Controls.Add(updateStatus);
            updatePanel.Controls.Add(update);
            open = new Button { Left = 24, Top = 267, Width = 289, Height = 42, Text = "Abrir SPPtab", Enabled = false, FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(45, 112, 218), ForeColor = Color.White, Font = new Font("Segoe UI", 10F, FontStyle.Bold) };
            open.FlatAppearance.BorderSize = 0;
            close = new Button { Left = 326, Top = 267, Width = 150, Height = 42, Text = "Encerrar", FlatStyle = FlatStyle.Flat, BackColor = Color.White, ForeColor = Color.FromArgb(48, 76, 102) };
            close.FlatAppearance.BorderColor = Color.FromArgb(209, 223, 237);
            open.Click += delegate { try { OpenApp(); } catch (Exception ex) { MessageBox.Show(ex.Message); } };
            AcceptButton = open;
            close.Click += delegate { allowExit = true; Close(); };
            update.Click += delegate { BeginUpdateDownload(); };
            Controls.Add(statusDot); Controls.Add(status); Controls.Add(statusDetail); Controls.Add(updatePanel); Controls.Add(open); Controls.Add(close);

            ContextMenuStrip trayMenu = new ContextMenuStrip();
            trayMenu.Items.Add("Abrir SPPtab no navegador", null, delegate { if (!open.Enabled) { RestoreLauncher(); return; } try { OpenApp(); } catch (Exception ex) { MessageBox.Show(ex.Message); } });
            trayMenu.Items.Add("Mostrar esta janela", null, delegate { RestoreLauncher(); });
            trayMenu.Items.Add("Verificar atualizações", null, delegate { CheckForUpdates(); RestoreLauncher(); });
            trayMenu.Items.Add(new ToolStripSeparator());
            trayMenu.Items.Add("Encerrar SPPtab", null, delegate { allowExit = true; Close(); });
            trayIcon = new NotifyIcon
            {
                Icon = appIcon,
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
                        trayIcon.BalloonTipText = "O SPPtab continua ativo. Use o ícone perto do relógio para abrir ou encerrar.";
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
                        status.Text = "Serviço local pronto";
                        statusDetail.Text = "Verificando a versão antes de liberar a abertura.";
                        statusDot.BackColor = Color.FromArgb(50, 163, 125);
                        CheckForUpdates();
                    });
                }
                catch (Exception ex)
                {
                    BeginInvoke((MethodInvoker)delegate
                    {
                        startupFailed = true;
                        trayIcon.Visible = false;
                        status.Text = "Não foi possível iniciar o SPPtab";
                        statusDetail.Text = ex.Message;
                        statusDot.BackColor = Color.FromArgb(205, 69, 69);
                        close.Text = "Fechar";
                    });
                }
            });
            worker.IsBackground = true;
            worker.Start();
        }

        private void CheckForUpdates()
        {
            if (updateCheckRunning || startupFailed || IsDisposed) return;
            updateCheckRunning = true;
            if (availableTag == null) updateStatus.Text = "Verificando se há uma versão mais recente…";
            Thread worker = new Thread(delegate()
            {
                try
                {
                    string tag, version;
                    if (!TryGetLatestVersion(out tag, out version)) throw new InvalidOperationException("Não foi possível ler a versão publicada.");
                    BeginInvoke((MethodInvoker)delegate
                    {
                        updateCheckRunning = false;
                        if (IsNewerVersion(version, CurrentVersion))
                        {
                            availableTag = tag;
                            availableVersion = version;
                            status.Text = "Atualização disponível";
                            statusDetail.Text = "Instale a nova versão ou abra a versão atual.";
                            updateStatus.Text = "Nova versão v" + version + " disponível. Seus dados locais serão preservados.";
                            updateStatus.ForeColor = Color.FromArgb(34, 91, 176);
                            update.Visible = true;
                            update.Enabled = true;
                            open.Enabled = true;
                        }
                        else
                        {
                            availableTag = null;
                            availableVersion = null;
                            status.Text = "SPPtab pronto para abrir";
                            statusDetail.Text = "O navegador abrirá quando você clicar em Abrir SPPtab.";
                            update.Visible = false;
                            updateStatus.Text = "Versão atualizada. Você já pode abrir o SPPtab.";
                            updateStatus.ForeColor = Color.DimGray;
                            open.Enabled = true;
                        }
                    });
                }
                catch
                {
                    try
                    {
                        BeginInvoke((MethodInvoker)delegate
                        {
                            updateCheckRunning = false;
                            availableTag = null;
                            availableVersion = null;
                            update.Visible = false;
                            update.Enabled = false;
                            status.Text = "SPPtab pronto para abrir";
                            statusDetail.Text = "A verificação falhou; você pode usar a versão instalada.";
                            updateStatus.Text = "Não foi possível verificar atualizações agora. Você ainda pode abrir o SPPtab.";
                            updateStatus.ForeColor = Color.DimGray;
                            open.Enabled = true;
                        });
                    }
                    catch { updateCheckRunning = false; }
                }
            });
            worker.IsBackground = true;
            worker.Start();
        }

        private void SetUpdateStatus(string message, int percent)
        {
            if (IsDisposed || !IsHandleCreated) return;
            try
            {
                BeginInvoke((MethodInvoker)delegate
                {
                    if (!IsDisposed) updateStatus.Text = percent >= 0 ? message + " " + percent + "%" : message;
                });
            }
            catch { }
        }

        private void BeginUpdateDownload()
        {
            if (String.IsNullOrEmpty(availableTag) || update.Enabled == false) return;
            update.Enabled = false;
            open.Enabled = false;
            close.Enabled = false;
            updateStatus.ForeColor = Color.FromArgb(34, 91, 176);
            updateStatus.Text = "Baixando o pacote oficial…";
            Thread worker = new Thread(delegate()
            {
                string archivePath = Path.Combine(Path.GetTempPath(), "SPPtab-update-" + Guid.NewGuid().ToString("N") + ".zip");
                try
                {
                    ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
                    Uri packageUri = new Uri(ReleaseUrl(availableTag, "SPPtab-Portable.zip"));
                    using (WebClient client = new WebClient())
                    using (ManualResetEvent completed = new ManualResetEvent(false))
                    {
                        Exception downloadError = null;
                        bool cancelled = false;
                        client.Headers[HttpRequestHeader.UserAgent] = "SPPtab-Updater";
                        client.DownloadProgressChanged += delegate(object sender, DownloadProgressChangedEventArgs e)
                        {
                            SetUpdateStatus("Baixando v" + availableVersion + "…", e.ProgressPercentage);
                        };
                        client.DownloadFileCompleted += delegate(object sender, AsyncCompletedEventArgs e)
                        {
                            downloadError = e.Error;
                            cancelled = e.Cancelled;
                            completed.Set();
                        };
                        client.DownloadFileAsync(packageUri, archivePath);
                        if (!completed.WaitOne(TimeSpan.FromMinutes(20)))
                        {
                            client.CancelAsync();
                            throw new TimeoutException("O download excedeu o tempo limite. Tente novamente quando a conexão estiver estável.");
                        }
                        if (downloadError != null) throw downloadError;
                        if (cancelled) throw new OperationCanceledException("O download da atualização foi cancelado.");
                    }

                    SetUpdateStatus("Conferindo a integridade do pacote…", -1);
                    string checksumText = DownloadText(ReleaseUrl(availableTag, "SPPtab-Portable-SHA256SUM.txt"), 30000);
                    Match hashMatch = Regex.Match(checksumText, "\\b([a-f0-9]{64})\\b", RegexOptions.IgnoreCase);
                    if (!hashMatch.Success || !String.Equals(Sha256File(archivePath), hashMatch.Groups[1].Value, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException("O pacote baixado não passou pela verificação de integridade. Nenhum arquivo foi alterado.");

                    string helperPath = Path.Combine(Path.GetTempPath(), "SPPtab-Updater-" + Guid.NewGuid().ToString("N") + ".exe");
                    File.Copy(Path.Combine(BaseDirectory, "SPPtab.exe"), helperPath);
                    ProcessStartInfo helper = new ProcessStartInfo(helperPath,
                        "--apply-update " + Quote(archivePath) + " " + Quote(hashMatch.Groups[1].Value) + " " + Process.GetCurrentProcess().Id + " " + Quote(BaseDirectory));
                    helper.UseShellExecute = true;
                    helper.WindowStyle = ProcessWindowStyle.Hidden;
                    helper.WorkingDirectory = Path.GetTempPath();
                    Process.Start(helper);
                    BeginInvoke((MethodInvoker)delegate
                    {
                        status.Text = "Atualização conferida. Reiniciando o SPPtab…";
                        allowExit = true;
                        Close();
                    });
                }
                catch (Exception ex)
                {
                    try { if (File.Exists(archivePath)) File.Delete(archivePath); } catch { }
                    try
                    {
                        BeginInvoke((MethodInvoker)delegate
                        {
                            close.Enabled = true;
                            open.Enabled = true;
                            update.Enabled = true;
                            updateStatus.Text = "Não foi possível atualizar: " + ex.Message;
                            updateStatus.ForeColor = Color.Firebrick;
                        });
                    }
                    catch { }
                }
            });
            worker.IsBackground = true;
            worker.Start();
        }
    }
}
