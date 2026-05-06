from fa.config import RuntimeConfig
from fa.models import ReportFile


def test_runtime_config_uses_expected_defaults():
    config = RuntimeConfig.from_env({})

    assert config.validation_tolerance_millions == 0.5
    assert config.enable_llm_table_repair is False
    assert config.enable_llm_lineitem_match is False


def test_report_file_sha256_has_expected_length():
    report = ReportFile(
        company="SKHYNIX",
        pdf_path="/tmp/annual_report_2025.pdf",
        file_name="annual_report_2025.pdf",
        sha256="a" * 64,
        mtime=1715000000.0,
    )

    assert len(report.sha256) == 64
