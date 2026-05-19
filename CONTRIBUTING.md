# Contributing to synmich

Thanks for your interest! Contributions of any size are welcome.

## Setup

```bash
git clone https://github.com/schnyder/synmich.git
cd synmich
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Project structure

```
synmich/
├── synmich/
│   ├── cli.py              # Argparse + command dispatch
│   ├── config.py           # YAML config loader
│   ├── core/
│   │   ├── synology.py     # Synology Photos API client
│   │   ├── immich.py       # Immich API client
│   │   ├── migrator.py     # Main migration orchestrator
│   │   └── checkpoint.py   # Resume state persistence
│   └── ui/
│       ├── theme.py        # Banner, colors, helpers
│       ├── wizard.py       # `synmich init` interactive setup
│       └── dashboard.py    # Textual TUI for `migrate`
```

## Running locally

```bash
synmich --version
synmich --help
synmich init
synmich migrate --albums-only --workers 2
```

## Style

- Code formatted with `ruff format`.
- 100-char line limit.
- Type hints encouraged but not mandatory.

## Tests

```bash
pytest
```

## Pull Requests

1. Fork and create a feature branch from `main`.
2. Keep PRs focused — one feature/fix per PR.
3. Update README/CHANGELOG if user-facing.
4. Be kind in code reviews.

## Bug reports

Include:
- DSM version, Immich version, Python version
- `~/.config/synmich/config.yaml` (with passwords/keys redacted)
- Tail of `~/.config/synmich/migration.log`
- Steps to reproduce

## Feature requests

Open an issue describing the use case. We prioritize features that benefit the wider community over niche personal setups.
