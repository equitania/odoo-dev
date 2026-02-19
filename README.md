# odoodev — Unified Odoo Development CLI

Unified CLI tool for native Odoo development environment management across versions (v16-v19).

## Installation

```bash
uv pip install -e ".[dev]"
```

## Usage

```bash
odoodev config versions          # List available versions
odoodev init 18                  # Initialize v18 environment
odoodev start 18 --dev           # Start Odoo in dev mode
odoodev repos 18                 # Clone/update repositories
odoodev db 18 list               # List databases
```

## License

AGPL-3.0-or-later
