# Security Policy

## Supported Versions

Only the latest released version of `odoodev-equitania` receives security fixes.

## Reporting a Vulnerability

Please report security vulnerabilities **privately** — do **not** open a public issue.

- **Email:** security@equitania.de
- **PGP (optional):** request our public key via email

Include in your report:
- Affected version (`odoodev --version`)
- Steps to reproduce or proof-of-concept
- Potential impact

We acknowledge reports within **5 business days** and aim to provide a fix or
mitigation within **90 days**, coordinated with you on disclosure timing.

## Scope

This policy covers the `odoodev` CLI tool itself — its command handlers, core
modules, templates, and TUI code.

**Out of scope:**
- Odoo server vulnerabilities (report to Odoo S.A.)
- Docker or Apple Container runtime vulnerabilities
- PostgreSQL vulnerabilities
- Issues in third-party dependencies (report upstream)

## Security-relevant context

`odoodev` manages local development environments and handles:
- Database credentials (`.env`, `.pgpass` files — written with `0o600` permissions)
- SSH keys for git clone operations (temporary configs, `0o600`)
- PostgreSQL dump/restore operations (path-traversal guards on archive extraction)
- Database anonymization (SQL identifier validation via `_check_identifier`)

Default dev credentials (`ownerp` / `CHANGE_AT_FIRST`) are placeholders intended
for local development only. The tool warns at runtime and blocks `odoodev start`
until the placeholder is changed or explicitly acknowledged via
`--allow-placeholder-password`.
