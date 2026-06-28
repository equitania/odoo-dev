"""Tests for the odoodev bench command and its pure helpers."""

from __future__ import annotations

from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.commands.bench import _fmt, _parse_pgbench_tps, _recommend, _winner


class TestParsePgbenchTps:
    def test_parses_tps(self):
        out = "tps = 1234.56 (without initial connection time)\n"
        assert _parse_pgbench_tps(out) == 1234.56

    def test_takes_first_match(self):
        out = "tps = 100.0 (including connections establishing)\ntps = 105.0 (without...)\n"
        assert _parse_pgbench_tps(out) == 100.0

    def test_no_match_returns_none(self):
        assert _parse_pgbench_tps("no numbers here") is None


class TestWinner:
    def test_lower_is_better_cold_start(self):
        results = {"docker": {"cold_start_s": 5.0}, "apple": {"cold_start_s": 2.0}}
        assert _winner(results, "cold_start_s") == "apple"

    def test_higher_is_better_tps(self):
        results = {"docker": {"tps": 900.0}, "apple": {"tps": 1200.0}}
        assert _winner(results, "tps") == "apple"

    def test_single_runtime_no_winner(self):
        results = {"docker": {"tps": 900.0}}
        assert _winner(results, "tps") is None

    def test_missing_metric_no_winner(self):
        results = {"docker": {"tps": None}, "apple": {"tps": 1200.0}}
        assert _winner(results, "tps") is None


class TestRecommend:
    def test_prefers_tps(self):
        results = {
            "docker": {"tps": 1500.0, "cold_start_s": 1.0},
            "apple": {"tps": 1200.0, "cold_start_s": 0.5},
        }
        # Docker wins TPS even though Apple wins cold start.
        assert _recommend(results) == "docker"

    def test_falls_back_to_cold_start(self):
        results = {
            "docker": {"tps": None, "cold_start_s": 4.0},
            "apple": {"tps": None, "cold_start_s": 1.0},
        }
        assert _recommend(results) == "apple"

    def test_error_runtime_excluded(self):
        results = {"docker": {"error": "start failed"}, "apple": {"tps": 1200.0, "cold_start_s": 1.0}}
        assert _recommend(results) is None


class TestFmt:
    def test_none_is_dash(self):
        assert "-" in _fmt(None)

    def test_float_formatted(self):
        assert _fmt(12.345, "s") == "12.35s"


def _canned(metrics):
    def _fake(*args, **kwargs):
        # backend is the first positional argument.
        backend = args[0]
        return metrics[backend.cli]

    return _fake


class TestBenchCommand:
    def test_runs_both_and_recommends(self, monkeypatch):
        monkeypatch.setattr("odoodev.commands.bench._find_pg_binary", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr("odoodev.commands.bench.check_docker", lambda: True)
        monkeypatch.setattr("odoodev.commands.bench.check_apple_container", lambda: True)
        metrics = {
            "docker": {"cold_start_s": 4.0, "tps": 900.0, "tps_method": "pgbench", "io_s": 3.0, "stats": None},
            "container": {"cold_start_s": 1.0, "tps": 1300.0, "tps_method": "pgbench", "io_s": 2.0, "stats": None},
        }
        monkeypatch.setattr("odoodev.commands.bench._benchmark_runtime", _canned(metrics))
        result = CliRunner().invoke(cli, ["bench", "18"])
        assert result.exit_code == 0
        assert "Benchmark" in result.output
        assert "Apple Container" in result.output

    def test_skips_unavailable_runtime(self, monkeypatch):
        monkeypatch.setattr("odoodev.commands.bench._find_pg_binary", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr("odoodev.commands.bench.check_docker", lambda: True)
        monkeypatch.setattr("odoodev.commands.bench.check_apple_container", lambda: False)
        metrics = {
            "docker": {"cold_start_s": 4.0, "tps": 900.0, "tps_method": "pgbench", "io_s": 3.0, "stats": None},
        }
        monkeypatch.setattr("odoodev.commands.bench._benchmark_runtime", _canned(metrics))
        result = CliRunner().invoke(cli, ["bench", "18"])
        assert result.exit_code == 0
        assert "Skipping Apple Container" in result.output

    def test_aborts_without_psql(self, monkeypatch):
        monkeypatch.setattr("odoodev.commands.bench._find_pg_binary", lambda name: None)
        result = CliRunner().invoke(cli, ["bench", "18"])
        assert result.exit_code == 1
        assert "psql not found" in result.output

    def test_aborts_when_no_runtime_available(self, monkeypatch):
        monkeypatch.setattr("odoodev.commands.bench._find_pg_binary", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr("odoodev.commands.bench.check_docker", lambda: False)
        monkeypatch.setattr("odoodev.commands.bench.check_apple_container", lambda: False)
        result = CliRunner().invoke(cli, ["bench", "18"])
        assert result.exit_code == 1
        assert "No requested runtime" in result.output
