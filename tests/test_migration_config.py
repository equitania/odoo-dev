"""Tests for migration configuration module."""

import os
from pathlib import Path

import pytest

from odoodev.core.migration_config import (
    MigrationConfig,
    MigrationGroup,
    activate_migration,
    clear_migration_cache,
    create_migration_group,
    deactivate_migration,
    get_active_group,
    load_migration_config,
    remove_migration_group,
    save_migration_config,
)


@pytest.fixture(autouse=True)
def clean_cache():
    """Clear migration config cache before and after each test."""
    clear_migration_cache()
    yield
    clear_migration_cache()


@pytest.fixture
def migration_dir(tmp_dir, monkeypatch):
    """Set up a temporary migration config directory."""
    config_dir = Path(tmp_dir) / ".config" / "odoodev"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "odoodev.core.migration_config.get_migration_config_path",
        lambda: config_dir / "migration.yaml",
    )
    return config_dir


class TestMigrationGroup:
    """Tests for MigrationGroup dataclass."""

    def test_frozen(self):
        group = MigrationGroup(
            name="16-to-18",
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base="~/odoo-share/migration/16-to-18",
            created_at="2026-03-30T10:00:00",
        )
        with pytest.raises(AttributeError):
            group.name = "changed"

    def test_fields(self):
        group = MigrationGroup(
            name="16-to-18",
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base="~/odoo-share/migration/16-to-18",
            created_at="2026-03-30T10:00:00",
        )
        assert group.name == "16-to-18"
        assert group.from_version == "16"
        assert group.to_version == "18"
        assert group.pg_version == "16.11-alpine"
        assert group.shared_db_port == 16432


class TestLoadSaveMigrationConfig:
    """Tests for loading and saving migration config."""

    def test_load_nonexistent_returns_empty(self, migration_dir):
        config = load_migration_config()
        assert config.active is None
        assert config.groups == {}

    def test_save_and_load_roundtrip(self, migration_dir):
        group = MigrationGroup(
            name="16-to-18",
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base="~/odoo-share/migration/16-to-18",
            created_at="2026-03-30T10:00:00",
        )
        config = MigrationConfig(active="16-to-18", groups={"16-to-18": group})
        save_migration_config(config)

        clear_migration_cache()
        loaded = load_migration_config()
        assert loaded.active == "16-to-18"
        assert "16-to-18" in loaded.groups
        assert loaded.groups["16-to-18"].from_version == "16"
        assert loaded.groups["16-to-18"].to_version == "18"
        assert loaded.groups["16-to-18"].shared_db_port == 16432

    def test_load_empty_file(self, migration_dir):
        config_path = migration_dir / "migration.yaml"
        config_path.write_text("")
        config = load_migration_config()
        assert config.active is None
        assert config.groups == {}

    def test_load_invalid_yaml(self, migration_dir):
        config_path = migration_dir / "migration.yaml"
        config_path.write_text("not_a_dict")
        config = load_migration_config()
        assert config.active is None

    def test_save_creates_header_comment(self, migration_dir):
        config = MigrationConfig(active=None, groups={})
        path = save_migration_config(config)
        content = path.read_text()
        assert "Managed by: odoodev migrate" in content


class TestGetActiveGroup:
    """Tests for get_active_group()."""

    def test_no_config_returns_none(self, migration_dir):
        assert get_active_group() is None

    def test_no_active_returns_none(self, migration_dir):
        config = MigrationConfig(active=None, groups={})
        save_migration_config(config)
        clear_migration_cache()
        assert get_active_group() is None

    def test_active_returns_group(self, migration_dir):
        group = MigrationGroup(
            name="16-to-18",
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base="~/odoo-share/migration/16-to-18",
            created_at="2026-03-30T10:00:00",
        )
        config = MigrationConfig(active="16-to-18", groups={"16-to-18": group})
        save_migration_config(config)
        clear_migration_cache()

        result = get_active_group()
        assert result is not None
        assert result.name == "16-to-18"
        assert result.from_version == "16"

    def test_active_points_to_nonexistent_group(self, migration_dir):
        config = MigrationConfig(active="nonexistent", groups={})
        save_migration_config(config)
        clear_migration_cache()
        assert get_active_group() is None


class TestCreateMigrationGroup:
    """Tests for create_migration_group()."""

    def test_create_with_defaults(self, migration_dir, tmp_dir):
        group = create_migration_group(
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base=f"{tmp_dir}/odoo-share/migration/16-to-18",
        )
        assert group.name == "16-to-18"
        assert group.from_version == "16"
        assert group.to_version == "18"
        assert group.created_at  # not empty

        # Verify persisted
        clear_migration_cache()
        config = load_migration_config()
        assert "16-to-18" in config.groups

    def test_create_with_custom_name(self, migration_dir, tmp_dir):
        group = create_migration_group(
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base=f"{tmp_dir}/odoo-share/migration/custom",
            name="my-migration",
        )
        assert group.name == "my-migration"

    def test_create_duplicate_raises(self, migration_dir, tmp_dir):
        create_migration_group(
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base=f"{tmp_dir}/odoo-share/migration/16-to-18",
        )
        with pytest.raises(ValueError, match="already exists"):
            create_migration_group(
                from_version="16",
                to_version="18",
                pg_version="16.11-alpine",
                shared_db_port=16432,
                shared_filestore_base=f"{tmp_dir}/odoo-share/migration/16-to-18",
            )

    def test_create_creates_filestore_dir(self, migration_dir, tmp_dir):
        base = f"{tmp_dir}/odoo-share/migration/16-to-18"
        create_migration_group(
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base=base,
        )
        assert os.path.isdir(os.path.join(base, "filestore"))


class TestActivateDeactivate:
    """Tests for activate and deactivate."""

    def test_activate(self, migration_dir, tmp_dir):
        create_migration_group(
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base=f"{tmp_dir}/odoo-share/migration/16-to-18",
        )
        clear_migration_cache()
        group = activate_migration("16-to-18")
        assert group.name == "16-to-18"

        clear_migration_cache()
        config = load_migration_config()
        assert config.active == "16-to-18"

    def test_activate_nonexistent_raises(self, migration_dir):
        with pytest.raises(KeyError, match="not found"):
            activate_migration("nonexistent")

    def test_deactivate(self, migration_dir, tmp_dir):
        create_migration_group(
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base=f"{tmp_dir}/odoo-share/migration/16-to-18",
        )
        activate_migration("16-to-18")
        clear_migration_cache()
        deactivate_migration()

        clear_migration_cache()
        config = load_migration_config()
        assert config.active is None

    def test_deactivate_when_none_active(self, migration_dir):
        deactivate_migration()  # Should not raise
        config = load_migration_config()
        assert config.active is None


class TestRemoveMigrationGroup:
    """Tests for remove_migration_group()."""

    def test_remove(self, migration_dir, tmp_dir):
        create_migration_group(
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base=f"{tmp_dir}/odoo-share/migration/16-to-18",
        )
        clear_migration_cache()
        remove_migration_group("16-to-18")

        clear_migration_cache()
        config = load_migration_config()
        assert "16-to-18" not in config.groups

    def test_remove_nonexistent_raises(self, migration_dir):
        with pytest.raises(KeyError, match="not found"):
            remove_migration_group("nonexistent")

    def test_remove_active_without_force_raises(self, migration_dir, tmp_dir):
        create_migration_group(
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base=f"{tmp_dir}/odoo-share/migration/16-to-18",
        )
        activate_migration("16-to-18")
        clear_migration_cache()

        with pytest.raises(ValueError, match="currently active"):
            remove_migration_group("16-to-18")

    def test_remove_active_with_force(self, migration_dir, tmp_dir):
        create_migration_group(
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base=f"{tmp_dir}/odoo-share/migration/16-to-18",
        )
        activate_migration("16-to-18")
        clear_migration_cache()

        remove_migration_group("16-to-18", force=True)
        clear_migration_cache()
        config = load_migration_config()
        assert config.active is None
        assert "16-to-18" not in config.groups


class TestVersionRegistryIntegration:
    """Tests for migration override in version_registry."""

    def test_migration_overrides_target_port(self, migration_dir, versions_yaml, tmp_dir):
        """When migration is active, target version's DB port should be overridden."""
        from odoodev.core.migration_config import save_migration_config

        group = MigrationGroup(
            name="18-to-19",
            from_version="18",
            to_version="19",
            pg_version="16.11-alpine",
            shared_db_port=18432,
            shared_filestore_base=f"{tmp_dir}/odoo-share/migration/18-to-19",
            created_at="2026-03-30T10:00:00",
        )
        config = MigrationConfig(active="18-to-19", groups={"18-to-19": group})
        save_migration_config(config)
        clear_migration_cache()

        from odoodev.core.version_registry import load_versions

        versions = load_versions(override_path=versions_yaml)
        # v19 should now have v18's DB port
        assert versions["19"].ports.db == 18432
        # v19's postgres should be overridden to the shared pg_version
        assert versions["19"].postgres == "16.11-alpine"
        # v18 should be unchanged
        assert versions["18"].ports.db == 18432

    def test_no_migration_no_override(self, migration_dir, versions_yaml):
        """Without active migration, versions are unchanged."""
        from odoodev.core.version_registry import load_versions

        versions = load_versions(override_path=versions_yaml)
        assert versions["18"].ports.db == 18432
        assert versions["19"].ports.db == 19432


class TestFilestoreIntegration:
    """Tests for migration-aware filestore paths."""

    def test_filestore_shared_when_active(self, migration_dir, tmp_dir):
        from odoodev.core.database import get_filestore_path
        from odoodev.core.migration_config import save_migration_config

        shared_base = f"{tmp_dir}/odoo-share/migration/16-to-18"
        group = MigrationGroup(
            name="16-to-18",
            from_version="16",
            to_version="18",
            pg_version="16.11-alpine",
            shared_db_port=16432,
            shared_filestore_base=shared_base,
            created_at="2026-03-30T10:00:00",
        )
        config = MigrationConfig(active="16-to-18", groups={"16-to-18": group})
        save_migration_config(config)
        clear_migration_cache()

        # Both source and target should use shared path
        path_16 = get_filestore_path("16", "mydb")
        path_18 = get_filestore_path("18", "mydb")
        assert path_16 == path_18
        assert "migration/16-to-18" in path_16

        # Other versions should not be affected
        path_19 = get_filestore_path("19", "mydb")
        assert "migration" not in path_19

    def test_filestore_normal_when_inactive(self, migration_dir, tmp_dir):
        from odoodev.core.database import get_filestore_path

        path_16 = get_filestore_path("16", "mydb")
        path_18 = get_filestore_path("18", "mydb")
        assert path_16 != path_18
        assert "v16" in path_16
        assert "v18" in path_18
