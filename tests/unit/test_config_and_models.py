from fa.config import RuntimeConfig
from fa.models import ReportFile


def test_runtime_config_uses_expected_defaults():
    config = RuntimeConfig.from_env({})

    assert config.tolerance == 0.5
    assert config.llm_table_repair is False


def test_report_file_sha256_has_expected_length():
    report = ReportFile(
        company_code="SKHYNIX",
        report_name="annual_report_2025.pdf",
        file_path="/tmp/annual_report_2025.pdf",
        sha256="a" * 64,
    )

    assert len(report.sha256) == 64
