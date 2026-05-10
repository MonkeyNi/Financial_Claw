using System.IO;
using System.Windows;

namespace FinancialClaw.Desktop;

public partial class AddCompanyWindow : Window
{
    public string CompanyName { get; private set; } = "";

    public AddCompanyWindow()
    {
        InitializeComponent();
        CompanyNameTextBox.Focus();
    }

    private void CreateButton_Click(object sender, RoutedEventArgs e)
    {
        var name = CompanyNameTextBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            ShowError("Enter a company name.");
            return;
        }

        if (name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
        {
            ShowError("Company name contains invalid file name characters.");
            return;
        }

        CompanyName = name;
        DialogResult = true;
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
    }

    private void ShowError(string message)
    {
        ErrorText.Text = message;
        ErrorText.Visibility = Visibility.Visible;
    }
}
