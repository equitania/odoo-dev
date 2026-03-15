"""Tests for odoodev.tui.log_parser."""

from odoodev.tui.log_parser import LEVEL_ORDER, level_ge, parse_line


class TestParseLineStandard:
    """Test parsing standard Odoo log lines."""

    def test_info_line(self):
        line = "2025-03-15 10:23:45,123 4567 INFO v18_exam odoo.modules.loading: Loading module eq_sale"
        entry = parse_line(line)
        assert entry.timestamp == "2025-03-15 10:23:45,123"
        assert entry.pid == "4567"
        assert entry.level == "INFO"
        assert entry.database == "v18_exam"
        assert entry.logger == "odoo.modules.loading"
        assert entry.message == "Loading module eq_sale"
        assert entry.raw == line

    def test_warning_line(self):
        line = "2025-03-15 10:23:46,456 4567 WARNING v18_exam odoo.models: Deprecated field usage"
        entry = parse_line(line)
        assert entry.level == "WARNING"
        assert entry.logger == "odoo.models"
        assert entry.message == "Deprecated field usage"

    def test_error_line(self):
        line = "2025-03-15 10:23:47,789 4567 ERROR v18_exam odoo.http: Request error"
        entry = parse_line(line)
        assert entry.level == "ERROR"
        assert entry.logger == "odoo.http"

    def test_debug_line(self):
        line = "2025-03-15 10:23:48,000 4567 DEBUG v18_exam odoo.sql_db: query took 0.003s"
        entry = parse_line(line)
        assert entry.level == "DEBUG"

    def test_critical_line(self):
        line = "2025-03-15 10:23:49,111 4567 CRITICAL v18_exam odoo.service: Server crash"
        entry = parse_line(line)
        assert entry.level == "CRITICAL"

    def test_message_with_colons(self):
        line = "2025-03-15 10:23:45,123 4567 INFO v18_exam odoo.addons.base: key: value: nested"
        entry = parse_line(line)
        assert entry.logger == "odoo.addons.base"
        assert entry.message == "key: value: nested"

    def test_empty_message(self):
        line = "2025-03-15 10:23:45,123 4567 INFO v18_exam odoo.modules: "
        entry = parse_line(line)
        assert entry.level == "INFO"
        assert entry.message == ""

    def test_database_with_numbers(self):
        line = "2025-03-15 10:23:45,123 4567 INFO v18_test_2025 odoo.modules.loading: init"
        entry = parse_line(line)
        assert entry.database == "v18_test_2025"


class TestParseLineRaw:
    """Test parsing non-standard lines (tracebacks, startup, blank)."""

    def test_traceback_line(self):
        line = '  File "/opt/odoo/server/odoo/http.py", line 123, in dispatch'
        entry = parse_line(line)
        assert entry.level == "RAW"
        assert entry.message == line
        assert entry.raw == line

    def test_blank_line(self):
        entry = parse_line("")
        assert entry.level == "RAW"
        assert entry.raw == ""

    def test_startup_banner(self):
        line = "Odoo server is ready. Listening on http://0.0.0.0:8069"
        entry = parse_line(line)
        assert entry.level == "RAW"

    def test_python_traceback_header(self):
        line = "Traceback (most recent call last):"
        entry = parse_line(line)
        assert entry.level == "RAW"

    def test_line_with_newline(self):
        line = "2025-03-15 10:23:45,123 4567 INFO db odoo.x: msg\n"
        entry = parse_line(line)
        assert entry.level == "INFO"
        assert entry.raw == line.rstrip("\n")

    def test_line_with_crlf(self):
        line = "2025-03-15 10:23:45,123 4567 INFO db odoo.x: msg\r\n"
        entry = parse_line(line)
        assert entry.level == "INFO"
        assert entry.raw == line.rstrip("\r\n")

    def test_unicode_content(self):
        line = "2025-03-15 10:23:45,123 4567 INFO db odoo.x: Rechnungsstellung fur Kunden"
        entry = parse_line(line)
        assert entry.level == "INFO"
        assert "Rechnungsstellung" in entry.message

    def test_german_umlauts(self):
        line = "2025-03-15 10:23:45,123 4567 WARNING db odoo.x: Anderung der Bestellubersicht"
        entry = parse_line(line)
        assert entry.level == "WARNING"


class TestLevelGe:
    """Test level_ge() filtering function."""

    def test_info_ge_info(self):
        assert level_ge("INFO", "INFO") is True

    def test_warning_ge_info(self):
        assert level_ge("WARNING", "INFO") is True

    def test_error_ge_info(self):
        assert level_ge("ERROR", "INFO") is True

    def test_debug_not_ge_info(self):
        assert level_ge("DEBUG", "INFO") is False

    def test_info_not_ge_warning(self):
        assert level_ge("INFO", "WARNING") is False

    def test_raw_always_passes(self):
        assert level_ge("RAW", "ERROR") is True
        assert level_ge("RAW", "CRITICAL") is True

    def test_debug_ge_debug(self):
        assert level_ge("DEBUG", "DEBUG") is True

    def test_critical_ge_all(self):
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            assert level_ge("CRITICAL", level) is True


class TestLevelOrder:
    """Test LEVEL_ORDER constants."""

    def test_ordering(self):
        assert LEVEL_ORDER["DEBUG"] < LEVEL_ORDER["INFO"]
        assert LEVEL_ORDER["INFO"] < LEVEL_ORDER["WARNING"]
        assert LEVEL_ORDER["WARNING"] < LEVEL_ORDER["ERROR"]
        assert LEVEL_ORDER["ERROR"] < LEVEL_ORDER["CRITICAL"]

    def test_raw_highest(self):
        assert LEVEL_ORDER["RAW"] > LEVEL_ORDER["CRITICAL"]


class TestOdooLogEntryFrozen:
    """Test that OdooLogEntry is immutable."""

    def test_immutable(self):
        entry = parse_line("2025-03-15 10:23:45,123 4567 INFO db odoo.x: msg")
        try:
            entry.level = "ERROR"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass
