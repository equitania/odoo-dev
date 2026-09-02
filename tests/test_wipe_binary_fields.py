"""v0.66.0: --wipe covers Binary-field attachments, recompute survives bad records.

Background (real restore log, Odoo 18): after ``--sanitize`` the filestore still
held 1655 invoice PDFs (250 MB) and 1847 EBICS bank files — Odoo 17+ stores the
legal invoice PDF as the Binary field ``account.move.invoice_pdf_report_file``,
which the ``res_field IS NOT NULL`` guard of v0.62.0 spared wholesale. And the
recompute died on ONE partner with a pre-existing invalid Peppol endpoint, so
not a single ``complete_name`` was committed after anonymization.
"""

from __future__ import annotations

import re

from odoodev.core.database import (
    ANONYMIZE_TABLES,
    WIPE_BINARY_DELETE_MODELS,
    WIPE_BINARY_DELETE_SQL,
    WIPE_PARTNER_IMAGE_DELETE_SQL,
    WipeResult,
    _build_recompute_script,
    wipe_database,
)


class TestAnonymizePeppol:
    def test_partner_specs_null_peppol_endpoint(self):
        """peppol_endpoint derives from VAT / company registry — anonymize it too."""
        for spec in (s for s in ANONYMIZE_TABLES if s.table == "res_partner"):
            field = next((f for f in spec.fields if f.column == "peppol_endpoint"), None)
            assert field is not None, spec.where
            assert field.generator(None, 1) is None


class TestRecomputeScriptResilience:
    def test_script_is_valid_python(self):
        script = _build_recompute_script({"res.partner": ("name",)})
        compile(script, "<recompute>", "exec")

    def test_script_isolates_failing_records_instead_of_aborting(self):
        script = _build_recompute_script({"res.partner": ("name",)})
        # A constraint failure rolls back, bisects and reports the culprit ...
        assert "env.cr.rollback()" in script
        assert "odoodev-recompute: skipped" in script
        # ... and every successful chunk is committed on its own, so one bad
        # record can no longer discard the recompute of all the others.
        assert script.count("env.cr.commit()") >= 1
        assert "env.flush_all()" in script

    def test_script_reports_skipped_count_in_done_marker(self):
        script = _build_recompute_script({"res.partner": ("name",)})
        assert "odoodev-recompute: done" in script
        assert "skipped" in script


class TestWipeBinaryFields:
    def _capture(self, monkeypatch, ok=True, columns=None):
        psql_queries: list[str] = []
        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: (columns or {"id"}) if columns is None or table in columns else set(),
        )
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda query, **k: (psql_queries.append(query), (ok, "DELETE 3\n"))[1],
        )
        monkeypatch.setattr("odoodev.core.database._run_psql_tuples", lambda query, **k: (True, []))
        return psql_queries

    def test_transactional_binary_models_are_listed(self):
        for model in ("account.move", "ebics.file", "hr.employee", "hr.version", "account.bank.statement"):
            assert model in WIPE_BINARY_DELETE_MODELS
        # Master data / branding must NOT be in the list.
        for model in ("product.template", "product.product", "res.company", "ir.ui.view"):
            assert model not in WIPE_BINARY_DELETE_MODELS

    def test_binary_delete_sql_targets_res_field_rows_of_listed_models(self):
        assert "res_field IS NOT NULL" in WIPE_BINARY_DELETE_SQL
        assert "'account.move'" in WIPE_BINARY_DELETE_SQL
        assert "'ebics.file'" in WIPE_BINARY_DELETE_SQL

    def test_partner_image_delete_keeps_user_and_company_partners(self):
        assert "res_model = 'res.partner'" in WIPE_PARTNER_IMAGE_DELETE_SQL
        assert "res_field LIKE 'image_%'" in WIPE_PARTNER_IMAGE_DELETE_SQL
        assert "FROM res_users" in WIPE_PARTNER_IMAGE_DELETE_SQL
        assert "FROM res_company" in WIPE_PARTNER_IMAGE_DELETE_SQL

    def test_wipe_runs_binary_and_partner_image_deletes(self, monkeypatch):
        psql_queries = self._capture(monkeypatch)
        assert wipe_database("mydb")
        assert WIPE_BINARY_DELETE_SQL in psql_queries
        assert WIPE_PARTNER_IMAGE_DELETE_SQL in psql_queries

    def test_orphan_sweep_deletes_binary_rows_whose_record_is_gone(self, monkeypatch):
        """documents.document thumbnails survived their cascaded document rows."""
        psql_queries = self._capture(monkeypatch)
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_tuples",
            lambda query, **k: (True, [["documents.document"], ["product.template"]]),
        )
        wipe_database("mydb")
        sweeps = [q for q in psql_queries if "NOT EXISTS (SELECT 1 FROM documents_document" in q]
        assert len(sweeps) == 1
        assert "res_model = 'documents.document'" in sweeps[0]
        assert "res_field IS NOT NULL" in sweeps[0]
        # product.template rows still exist — the sweep only removes dangling ones,
        # so the statement for it is the same NOT EXISTS shape (never a blanket delete).
        prod = next(q for q in psql_queries if "res_model = 'product.template'" in q)
        assert "NOT EXISTS (SELECT 1 FROM product_template" in prod

    def test_orphan_sweep_skips_models_without_a_table(self, monkeypatch):
        """Abstract/transient models have no table — no statement may reference one."""
        psql_queries = self._capture(monkeypatch, columns={"ir_attachment", "mail_message", "id"})
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_tuples",
            lambda query, **k: (True, [["mail.thread"]]),
        )
        wipe_database("mydb")
        assert not any("mail_thread" in q for q in psql_queries)

    def test_orphan_sweep_rejects_unsafe_model_names(self, monkeypatch):
        psql_queries = self._capture(monkeypatch)
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_tuples",
            lambda query, **k: (True, [["res.partner; DROP TABLE x"]]),
        )
        assert wipe_database("mydb")
        assert not any("DROP TABLE" in q for q in psql_queries)


class TestWipeResult:
    def test_result_is_truthy_on_success_and_carries_counts(self, monkeypatch):
        psql_queries: list[str] = []
        monkeypatch.setattr("odoodev.core.database._existing_columns", lambda table, *a, **k: {"id"})

        def fake_psql(query, **k):
            psql_queries.append(query)
            if query.startswith("DELETE FROM ir_attachment"):
                return True, "DELETE 1655\n"
            return True, "DELETE 0\n"

        monkeypatch.setattr("odoodev.core.database._run_psql", fake_psql)
        monkeypatch.setattr("odoodev.core.database._run_psql_tuples", lambda query, **k: (True, []))
        monkeypatch.setattr("odoodev.core.database.gc_filestore", lambda db, path, **k: (True, 1650))

        result = wipe_database("mydb", filestore_path="/tmp/mydb")
        assert isinstance(result, WipeResult)
        assert bool(result) is True
        assert result.success is True
        assert result.attachments_deleted >= 1655
        assert result.files_removed == 1650

    def test_result_is_falsy_on_failure(self, monkeypatch):
        monkeypatch.setattr("odoodev.core.database._existing_columns", lambda table, *a, **k: {"id"})
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda query, **k: (False, "boom"))
        monkeypatch.setattr("odoodev.core.database._run_psql_tuples", lambda query, **k: (True, []))
        result = wipe_database("mydb")
        assert bool(result) is False
        assert result.success is False

    def test_delete_counts_parse_psql_tags(self):
        from odoodev.core.database import _rows_affected

        assert _rows_affected("DELETE 1655\n") == 1655
        assert _rows_affected("UPDATE 12") == 12
        assert _rows_affected("") == 0
        assert re.match(r"^\d+$", str(_rows_affected("garbage")))
