from pathlib import Path

from tradingagents.report_history import load_prior_report_context


def _write_report(root: Path, directory: str, analysis_date: str, decision: str) -> None:
    report = root / directory
    (report / "2_research").mkdir(parents=True)
    (report / "3_trading").mkdir()
    (report / "5_portfolio").mkdir()
    (report / "0_evidence.md").write_text(
        f"# Evidence Manifest\n\n- Analysis date: {analysis_date}\n", encoding="utf-8"
    )
    (report / "complete_report.md").write_text("# Complete report", encoding="utf-8")
    (report / "2_research" / "manager.md").write_text(f"Manager {decision}", encoding="utf-8")
    (report / "3_trading" / "trader.md").write_text(f"Trader {decision}", encoding="utf-8")
    (report / "5_portfolio" / "decision.md").write_text(f"PM {decision}", encoding="utf-8")


def test_prior_report_context_reads_only_earlier_same_symbol_reports(tmp_path):
    _write_report(tmp_path, "005930_old", "2026-08-02", "BUY")
    _write_report(tmp_path, "005930_same_day", "2026-09-02", "SELL")
    _write_report(tmp_path, "005930_future", "2026-09-03", "SELL")
    _write_report(tmp_path, "000660_other", "2026-08-01", "SELL")

    context, reports = load_prior_report_context(tmp_path, "005930", "2026-09-02")

    assert [report.analysis_date for report in reports] == ["2026-08-02"]
    assert "Manager BUY" in context
    assert "SELL" not in context
    assert "current verified evidence overrides it" in context


def test_prior_report_context_returns_explicit_absence_note(tmp_path):
    context, reports = load_prior_report_context(tmp_path, "005930", "2026-09-02")

    assert reports == []
    assert "No completed report" in context
