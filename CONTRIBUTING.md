# Contributing to meteoswiss-mcp

🇩🇪 [Deutsche Version](CONTRIBUTING.de.md)

Thank you for your interest in contributing! This server is part of the [Swiss Public Data MCP Portfolio](https://github.com/malkreide/swiss-public-data-mcp).

---

## Reporting Issues

Use [GitHub Issues](https://github.com/malkreide/meteoswiss-mcp/issues) to report bugs or request features.

Please include:
- Python version and OS
- Full error message or description of unexpected behaviour
- Steps to reproduce

---

## Pull Requests

1. Fork the repository
2. Set up the dev environment and the local gates:
   `pip install -e ".[dev]" && pre-commit install`
   The hooks run the same checks as CI, using the `ruff` version pinned in
   `pyproject.toml` — that pin is the single source of truth, and the first
   hook fails if the `ruff` on your `PATH` is a different one.
3. Create a feature branch: `git checkout -b feat/your-feature`
4. Make your changes and add tests
5. Ensure all tests pass: `PYTHONPATH=src pytest tests/ -m "not live"`
6. Commit using [Conventional Commits](https://www.conventionalcommits.org/): `feat: add new tool`
7. Push and open a Pull Request against `main`

---

## Code Style

- Python 3.11+
- [Ruff](https://github.com/astral-sh/ruff) for linting and formatting
- Type hints required for all public functions
- Tests required for new tools (`tests/test_server.py`)
- Follow the existing `MCPServer` / Pydantic v2 patterns in `server.py`

---

## Data Sources

This server uses open Swiss weather and climate APIs — all without authentication:

| Source | Documentation |
|--------|--------------|
| BGDI STAC API (MeteoSwiss OGD) | [data.geo.admin.ch](https://data.geo.admin.ch/api/stac/v1) |
| Open-Meteo (MeteoSwiss ICON) | [open-meteo.com](https://open-meteo.com/) |
| opendata.swiss | [opendata.swiss](https://opendata.swiss/) |

When adding new data sources, follow the **No-Auth-First** principle: Phase 1 uses only open, authentication-free endpoints. Authenticated APIs are introduced in later phases with graceful degradation.

---

## The live suite: when it runs, and who sees a red result

**Cadence:** daily 05:17 UTC, plus on demand via *Actions → Live Tests → Run
workflow*. See [`.github/workflows/live-tests.yml`](.github/workflows/live-tests.yml).

**Who sees it:** **Nobody, automatically.** A failure produces *no* issue and no notification
here — only a red run in the Actions tab and an explanation in the job summary.
Anyone who does not open that tab learns nothing.

This is the weakest point of this gate, documented rather than glossed over:
other servers in the portfolio open an issue on red. The run is retried once
before reporting red, so a single network hiccup does not raise a false alarm.

**A red live run does not necessarily mean *our* bug.** It means the contract
with the source has changed, or the source is down. Both belong seen; only the
first belongs fixed. Please read the run before disabling the job — that is how
this check dies, and it is the only one in the repository that can contradict a
wrong assumption about die MeteoSchweiz-Quellen. Every other test asserts against a fixture, and
the fixture was written from the same assumption as the code.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
