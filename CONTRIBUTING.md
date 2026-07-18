# Contributing

Thanks for considering a contribution!

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Running tests and lint

```bash
pytest
ruff check .
```

All Graph API interactions in tests are mocked (via `responses`) — no real
Azure tenant or credentials are needed to run the test suite.

## Building the Docker image locally

```bash
docker build -t azure-secret-watch:dev .
```

## Guidelines

- Keep the tool read-only. Any change that would let it write to Microsoft
  Graph (creating/rotating/deleting credentials) is out of scope — this
  project only ever notifies humans, it doesn't act on their behalf.
- Never log or persist actual secret/certificate values.
- Add or update tests for any behavior change, especially around the
  expiry-bucket and dedupe logic in `scanner.py` / `state_store.py`.
- Keep new configuration options documented in `.env.example`.
