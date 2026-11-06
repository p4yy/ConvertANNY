"""Characterize privacy filtering and the visible crash-report contents."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import runtime


class Settings:
    def value(self, key, default=None):
        return {"language": "en"}.get(key, default)


def check_report_sections_and_private_path_redaction():
    with tempfile.TemporaryDirectory(prefix="PRIVATEUSER-") as directory:
        root = Path(directory)
        log = root / "convertanny.log"
        log.write_text("old\n" + "\n".join(f"line-{n}" for n in range(30)), encoding="utf-8")
        saved_settings, saved_log_path = runtime.settings, runtime.winsys.log_path
        runtime.settings = lambda: Settings()
        runtime.winsys.log_path = lambda: log
        try:
            with patch("pathlib.Path.home", return_value=root), patch("getpass.getuser", return_value="PRIVATEUSER"):
                report = runtime.crash_report_text("ValueError", "  failed at PRIVATEUSER  ")
        finally:
            runtime.settings, runtime.winsys.log_path = saved_settings, saved_log_path
        assert "ConvertANNY" in report and "Language: en" in report
        assert "What happened: ValueError" in report and "failed at <user>" in report
        assert "Last log lines:" in report and "line-29" in report and "line-5" in report
        assert "line-3\n" not in report and "PRIVATEUSER" not in report and str(root) not in report


if __name__ == "__main__":
    check_report_sections_and_private_path_redaction()
    print("Crash report sections and path/user redaction passed")
