# Testing Patterns

**Analysis Date:** 2026-05-13

## Test Framework

**Runner:** pytest 8.x
**Config:** `pyproject.toml` `[tool.pytest.ini_options]`

```toml
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-v --tb=short --cov=odoodev --cov-report=term-missing --cov-fail-under=55"
asyncio_mode = "auto"
```

**Additional libraries:**
- `pytest-cov` — coverage with 55% minimum threshold
- `pytest-mock` — `mocker` fixture (pytest-mock style)
- `pytest-asyncio` — async test support (`asyncio_mode = "auto"`)
- `unittest.mock` — `patch`, `MagicMock` used directly in many tests

## Run Commands

```bash
pytest                                                        # all tests + coverage
pytest tests/test_version_registry.py                        # single module
pytest tests/test_cli_config.py::test_config_versions        # single test function
pytest tests/test_prerequisites.py::TestNodeCheck            # single class
pytest --no-cov                                              # skip coverage (faster)
```

## Test File Organization

**Location:** `tests/` directory (flat, not co-located with source)

**Naming:** `test_<module_or_feature>.py`

```
tests/
├── conftest.py                    # shared fixtures
├── test_version_registry.py       # VersionRegistry, load_versions, get_version
├── test_templates.py              # Jinja2 template rendering
├── test_prerequisites.py          # prerequisite checks (node, psql, wkhtmltopdf)
├── test_start_language.py         # --lang / --load-language CLI flags
├── test_database.py               # DB ops (list, restore, drop)
├── test_db_backup.py              # backup extraction
├── test_git_ops.py                # git clone/update operations
├── test_venv_manager.py           # UV venv creation and hash checks
├── test_venv_patch_version.py     # venv Python version patching
├── test_migration_config.py       # migration configuration
├── test_migrate_command.py        # migrate CLI command
├── test_odoo_process.py           # Odoo process management
├── test_process_manager.py        # process manager
├── test_process_manager_group.py  # process group management
├── test_run_command.py            # run command
├── test_log_parser.py             # log parsing
├── test_addon_selector.py         # addon selection
├── test_pull.py                   # pull/update operations
└── test_xmlrpc_client.py          # XML-RPC client
```

## Fixtures (conftest.py)

**`tmp_dir`** — `tempfile.TemporaryDirectory` yielded as string path:
```python
@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d
```

**`versions_yaml`** — writes a minimal 2-version YAML (v18, v19) to `tmp_dir`, returns `Path`:
```python
@pytest.fixture
def versions_yaml(tmp_dir):
    # writes versions.yaml with v18 + v19 entries
    return path  # Path object
```

Use `versions_yaml` fixture when testing anything that reads version config from disk. Use `tmp_dir` for file I/O tests that need an isolated workspace.

## Test Structure

**Suite organization:** class-based grouping by subject:
```python
class TestLoadVersions:
    def test_load_bundled_versions(self): ...
    def test_version_16_exists(self): ...
    def test_version_18_config(self): ...
```

**Single functions** used for simple isolated cases outside a logical group.

**Fixture injection:** via parameter name matching (standard pytest):
```python
def test_env_template_v19(self):          # no fixtures needed
def test_something(self, tmp_dir): ...     # fixture injected
```

## Mocking

**Two styles used:**

**1. `unittest.mock.patch` decorator** (preferred for external commands/subprocess):
```python
from unittest.mock import MagicMock, patch

@patch("odoodev.core.prerequisites.command_exists", return_value=True)
@patch("odoodev.core.prerequisites.detect_os", return_value="macos")
@patch("subprocess.run")
def test_node_found_valid_version(self, mock_run, _os, _cmd):
    mock_run.return_value = MagicMock(returncode=0, stdout="v20.11.1\n")
    ...
```

**2. `monkeypatch`** (pytest fixture, for env vars, attributes, CWD):
```python
def test_load_language_added(self, monkeypatch):
    monkeypatch.setenv("ODOODEV_LANG", "de")
    monkeypatch.setattr("odoodev.commands.start.some_fn", lambda: ...)
```

**What to mock:**
- `subprocess.run` / `subprocess.check_output` — never execute real system commands in tests
- File system functions when not using `tmp_dir`
- `detect_os`, `command_exists`, `find_executable` — platform detection
- Environment variables via `monkeypatch.setenv`

**What NOT to mock:**
- `load_versions()` against bundled YAML — tests rely on real bundled data
- Pure dataclass construction — test directly with real instances
- Jinja2 template rendering — `PackageLoader("odoodev", "templates")` loads real templates

## Template Tests

Templates are tested by rendering with explicit context dicts and asserting on output substrings:
```python
result = template.render(version="18", db_port=18432, ...)
assert "DB_PORT=18432" in result
assert "ODOO_VERSION=18" in result
```

Template loader: `PackageLoader("odoodev", "templates")` — reads from installed package.

## Coverage

**Minimum:** 55% (`--cov-fail-under=55`)

**Report:** terminal with missing lines (`--cov-report=term-missing`)

**View:**
```bash
pytest --cov=odoodev --cov-report=html    # generates htmlcov/
```

## CI/CD

No CI pipeline file detected (no `.github/workflows/` or `.gitlab-ci.yml`). Tests run locally via `pytest`.

## Async Tests

`asyncio_mode = "auto"` — all `async def test_*` functions are collected and run automatically without `@pytest.mark.asyncio`.

---

*Testing analysis: 2026-05-13*
