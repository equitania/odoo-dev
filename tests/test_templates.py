"""Tests for Jinja2 template rendering."""

from jinja2 import Environment, PackageLoader

from odoodev.core.version_registry import get_version


def _get_template_env():
    return Environment(
        loader=PackageLoader("odoodev", "templates"),
        keep_trailing_newline=True,
    )


class TestEnvTemplate:
    def test_renders_env_template(self):
        jinja_env = _get_template_env()
        template = jinja_env.get_template("env.template.j2")
        result = template.render(
            version="18",
            env_name="dev18_native",
            platform="macos",
            dev_user="testuser",
            docker_platform="linux/arm64",
            db_port=18432,
            odoo_port=18069,
            gevent_port=18072,
            mailpit_port=18025,
            smtp_port=1025,
            postgres_version="16.11-alpine",
        )
        assert "ENV_NAME=dev18_native" in result
        assert "ODOO_VERSION=18" in result
        assert "DB_PORT=18432" in result
        assert "ODOO_PORT=18069" in result
        assert "POSTGRES_VERSION=16.11-alpine" in result
        assert "DEV_USER=testuser" in result

    def test_env_template_v19(self):
        jinja_env = _get_template_env()
        template = jinja_env.get_template("env.template.j2")
        v19 = get_version("19")
        result = template.render(
            version="19",
            env_name=v19.env_name,
            platform="linux",
            dev_user="dev",
            docker_platform="linux/amd64",
            db_port=v19.ports.db,
            odoo_port=v19.ports.odoo,
            gevent_port=v19.ports.gevent,
            mailpit_port=v19.ports.mailpit,
            smtp_port=v19.ports.smtp,
            postgres_version=v19.postgres,
        )
        assert "ODOO_VERSION=19" in result
        assert "DB_PORT=19432" in result
        assert "POSTGRES_VERSION=17.4-alpine" in result


class TestDockerComposeTemplate:
    def test_renders_compose(self):
        jinja_env = _get_template_env()
        template = jinja_env.get_template("docker-compose.yml.j2")
        result = template.render(
            version="18",
            user="testuser",
            docker_platform="linux/arm64",
            postgres_version="16.11-alpine",
            db_port=18432,
            mailpit_port=18025,
            smtp_port=1025,
        )
        assert "dev-db-18-native" in result
        assert "postgres:" in result
        assert "18432" in result
        assert "pg_isready" in result
        assert "postgresql.conf:/etc/postgresql/postgresql.conf" in result
        assert "config_file=/etc/postgresql/postgresql.conf" in result

    def test_compose_version_substitution(self):
        jinja_env = _get_template_env()
        template = jinja_env.get_template("docker-compose.yml.j2")
        result = template.render(
            version="19",
            user="dev",
            docker_platform="linux/amd64",
            postgres_version="17.4-alpine",
            db_port=19432,
            mailpit_port=19025,
            smtp_port=1925,
        )
        assert "dev-db-19-native" in result
        assert "19432" in result
        assert "postgresql.conf:/etc/postgresql/postgresql.conf" in result
        assert "config_file=/etc/postgresql/postgresql.conf" in result


class TestOdooConfigTemplate:
    def test_renders_odoo_config(self):
        jinja_env = _get_template_env()
        template = jinja_env.get_template("odoo_template.conf.j2")
        result = template.render(
            data_dir="/home/user/odoo-share/",
            db_host="localhost",
            db_port=18432,
            gevent_port=18072,
            http_port=18069,
        )
        assert "[options]" in result
        assert "db_host = localhost" in result
        assert "db_port = 18432" in result
        assert "http_port = 18069" in result
        assert "gevent_port = 18072" in result
