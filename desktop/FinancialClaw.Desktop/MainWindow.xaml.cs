using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows;
using Wpf.Ui.Controls;

namespace FinancialClaw.Desktop;

public partial class MainWindow : Window
{
    private readonly string _repoRoot;
    private readonly string _companiesRoot;
    private bool _isRunning;

    public ObservableCollection<CompanyRecord> Companies { get; } = new();
    public ObservableCollection<RunSummary> RunSummaries { get; } = new();

    public MainWindow()
    {
        InitializeComponent();
        DataContext = this;

        _repoRoot = FindRepoRoot();
        _companiesRoot = Path.Combine(_repoRoot, "companies");
        WorkspaceText.Text = _companiesRoot;
        RefreshCompanies();
    }

    private void RefreshCompanies()
    {
        Companies.Clear();
        if (!Directory.Exists(_companiesRoot))
        {
            AddRunSummary(new RunSummary { Company = "-", Progress = "-", Result = "Analysis workspace was not found." });
            return;
        }

        foreach (var dir in Directory.GetDirectories(_companiesRoot).OrderBy(Path.GetFileName))
        {
            var company = Path.GetFileName(dir);
            var sourceReports = CountSourceReports(dir);
            var processedReports = CountProcessedReports(dir, company);

            Companies.Add(new CompanyRecord
            {
                Name = company,
                SourceReports = sourceReports,
                ProcessedReports = processedReports
            });
        }
    }

    private void RefreshButton_Click(object sender, RoutedEventArgs e)
    {
        if (_isRunning)
        {
            return;
        }

        RefreshCompanies();
    }

    private async void UpdateAllButton_Click(object sender, RoutedEventArgs e)
    {
        if (_isRunning)
        {
            return;
        }

        _isRunning = true;
        SetActionsEnabled(false);

        try
        {
            foreach (var company in Companies.ToList())
            {
                await RunCompanyAsync(company);
            }
        }
        finally
        {
            _isRunning = false;
            SetActionsEnabled(true);
            RefreshCompanies();
        }
    }

    private async void UpdateCompanyButton_Click(object sender, RoutedEventArgs e)
    {
        if (_isRunning || sender is not Button { Tag: CompanyRecord company })
        {
            return;
        }

        _isRunning = true;
        SetActionsEnabled(false);

        try
        {
            await RunCompanyAsync(company);
        }
        finally
        {
            _isRunning = false;
            SetActionsEnabled(true);
            RefreshCompanies();
        }
    }

    private async Task RunCompanyAsync(CompanyRecord company)
    {
        var summary = new RunSummary
        {
            Company = company.Name,
            Progress = "0 / 0",
            Result = "Preparing"
        };
        AddRunSummary(summary);

        var startInfo = new ProcessStartInfo
        {
            FileName = "python",
            WorkingDirectory = _repoRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        startInfo.Environment["PYTHONPATH"] = "src";
        startInfo.ArgumentList.Add("-m");
        startInfo.ArgumentList.Add("financial_claw.pipeline.ingest");
        startInfo.ArgumentList.Add(company.Name);
        startInfo.ArgumentList.Add("--companies-root");
        startInfo.ArgumentList.Add("companies");

        using var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, args) => HandleLogLine(summary, args.Data);
        process.ErrorDataReceived += (_, args) => HandleLogLine(summary, args.Data);

        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        await process.WaitForExitAsync();

        if (process.ExitCode == 0)
        {
            if (!summary.Result.Contains("No new reports", StringComparison.OrdinalIgnoreCase))
            {
                summary.Result = "Completed";
            }
        }
        else
        {
            summary.Result = $"Failed. Exit code {process.ExitCode}";
        }
    }

    private void HandleLogLine(RunSummary summary, string? line)
    {
        if (string.IsNullOrWhiteSpace(line))
        {
            return;
        }

        Dispatcher.Invoke(() =>
        {
            var selected = Regex.Match(line, @"selected_reports=(\d+)");
            if (selected.Success && int.TryParse(selected.Groups[1].Value, out var selectedReports))
            {
                summary.Progress = selectedReports == 0 ? "0 / 0" : $"0 / {selectedReports}";
                summary.Result = selectedReports == 0 ? "No new reports" : "Queued";
            }

            var pdfStart = Regex.Match(line, @"\[pdf-start\]\s+(\d+)/(\d+).*file=(.+)$");
            if (pdfStart.Success)
            {
                var current = Math.Max(0, int.Parse(pdfStart.Groups[1].Value) - 1);
                var total = int.Parse(pdfStart.Groups[2].Value);
                summary.Progress = $"{current} / {total}";
                summary.Result = $"Processing {pdfStart.Groups[3].Value}";
            }

            var pdfDone = Regex.Match(line, @"\[pdf-done\]\s+(\d+)/(\d+)");
            if (pdfDone.Success)
            {
                summary.Progress = $"{pdfDone.Groups[1].Value} / {pdfDone.Groups[2].Value}";
                summary.Result = "Processing";
            }

            var runDone = Regex.Match(line, @"\[company-run-done\].*succeeded=(\d+).*failed=(\d+)");
            if (runDone.Success)
            {
                summary.Result = runDone.Groups[2].Value == "0" ? "Extraction completed" : $"Failed reports: {runDone.Groups[2].Value}";
            }

            if (line.Contains("no new reports", StringComparison.OrdinalIgnoreCase))
            {
                summary.Result = "No new reports";
            }
        });
    }

    private void OpenWorkspaceButton_Click(object sender, RoutedEventArgs e)
    {
        if (Directory.Exists(_companiesRoot))
        {
            Process.Start(new ProcessStartInfo(_companiesRoot) { UseShellExecute = true });
        }
    }

    private void AddCompanyButton_Click(object sender, RoutedEventArgs e)
    {
        if (_isRunning)
        {
            return;
        }

        var dialog = new AddCompanyWindow { Owner = this };
        if (dialog.ShowDialog() != true)
        {
            return;
        }

        var companyDir = Path.Combine(_companiesRoot, dialog.CompanyName);
        Directory.CreateDirectory(Path.Combine(companyDir, "Financial_Statements"));
        Directory.CreateDirectory(Path.Combine(companyDir, "final_excel"));
        RefreshCompanies();
    }

    private void AddRunSummary(RunSummary summary)
    {
        RunHistoryGapRow.Height = new GridLength(16);
        RunHistoryRow.Height = GridLength.Auto;
        RunHistoryPanel.Visibility = Visibility.Visible;
        RunSummaries.Insert(0, summary);
        while (RunSummaries.Count > 100)
        {
            RunSummaries.RemoveAt(RunSummaries.Count - 1);
        }
    }

    private void SetActionsEnabled(bool enabled)
    {
        RefreshButton.IsEnabled = enabled;
        UpdateAllButton.IsEnabled = enabled;
        AddCompanyButton.IsEnabled = enabled;
        OpenWorkspaceButton.IsEnabled = enabled;
        CompanyGrid.IsEnabled = enabled;
    }

    private static int CountSourceReports(string companyDir)
    {
        var fsDir = Path.Combine(companyDir, "Financial_Statements");
        return Directory.Exists(fsDir) ? Directory.GetFiles(fsDir, "*.pdf").Length : 0;
    }

    private static int CountProcessedReports(string companyDir, string company)
    {
        var configPath = Path.Combine(companyDir, $"{company}_config.json");
        if (!File.Exists(configPath))
        {
            return 0;
        }

        try
        {
            using var stream = File.OpenRead(configPath);
            using var doc = JsonDocument.Parse(stream);
            if (doc.RootElement.TryGetProperty("processed_reports", out var processed) && processed.ValueKind == JsonValueKind.Array)
            {
                return processed.GetArrayLength();
            }
        }
        catch
        {
            return 0;
        }

        return 0;
    }

    private static string FindRepoRoot()
    {
        var dir = AppContext.BaseDirectory;
        while (!string.IsNullOrWhiteSpace(dir))
        {
            if (File.Exists(Path.Combine(dir, "pyproject.toml")) && Directory.Exists(Path.Combine(dir, "src")))
            {
                return dir;
            }

            var parent = Directory.GetParent(dir);
            if (parent is null)
            {
                break;
            }

            dir = parent.FullName;
        }

        return Directory.GetCurrentDirectory();
    }
}

public sealed class CompanyRecord : INotifyPropertyChanged
{
    private int _sourceReports;
    private int _processedReports;

    public string Name { get; init; } = "";

    public int SourceReports
    {
        get => _sourceReports;
        set
        {
            _sourceReports = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(PendingReports));
        }
    }

    public int ProcessedReports
    {
        get => _processedReports;
        set
        {
            _processedReports = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(PendingReports));
        }
    }

    public int PendingReports => Math.Max(SourceReports - ProcessedReports, 0);

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}

public sealed class RunSummary : INotifyPropertyChanged
{
    private string _progress = "";
    private string _result = "";

    public string Time { get; init; } = DateTime.Now.ToString("HH:mm:ss");
    public string Company { get; init; } = "";

    public string Progress
    {
        get => _progress;
        set
        {
            _progress = value;
            OnPropertyChanged();
        }
    }

    public string Result
    {
        get => _result;
        set
        {
            _result = value;
            OnPropertyChanged();
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
