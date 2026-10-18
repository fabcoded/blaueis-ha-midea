# Contributing to blaueis-ha-midea

Contributions are welcome. This project is MIT-licensed — by submitting a change you agree that your contribution is licensed under the same terms.

## Before you start

- For anything non-trivial, **open an issue first** describing the change and your plan. Small fixes and typo corrections can go straight to PR.
- Read [`AGENTS.md`](AGENTS.md) — it describes the integration's conventions, test expectations, and reload-vs-restart rules.
- The Python library this integration consumes is installed from PyPI (`blaueis-core`, `blaueis-client`, exact pins in `manifest.json`). Protocol or glossary changes belong upstream in [blaueis-libmidea](https://github.com/fabcoded/blaueis-libmidea), not here — submit those there; the integration adopts them by bumping the pins once the library is released.

## Citation rule — the one that matters

This integration builds on community research (see [README.md#acknowledgments](README.md#acknowledgments)). When editing, **never**:

- Reference file paths, function names, or line numbers from external implementations in code, comments, or documentation.
- Copy content from external source code — comments, variable names, logic blocks.

Structured-provenance fields (`alt_names:` / `sources:` in the library's `glossary.yaml`) are the one exception. See the glossary's file-header comments and the workspace-level `AGENTS.md` for the rule.

## Development setup

Clone into `<HA config>/custom_components/blaueis_midea/` (symlink recommended for development) and restart HA.

Install the git hooks once after cloning — they run the same lint and formatting gates as CI:

```sh
pip install pre-commit   # if you don't already have it
./tools/install-hooks.sh
```

Install the test dependencies with `pip install -r requirements-dev.txt`. It carries the same library pins as `manifest.json`; to try an unreleased library change, install a local `blaueis-libmidea` checkout over them in your own environment (`pip install -e <libmidea>/packages/blaueis-core -e <libmidea>/packages/blaueis-client`) and do not commit it.

For test-suite and lint work:

```sh
ruff check && ruff format --check
python3 -m pytest
```

Tests must stay green (418 passing + 2 `xfail` currently). The suite has
two halves, and CI runs both on every PR:

```sh
python3 -m pytest tests/unit -m "not integration"   # mocked HA, fast
python3 -m pytest tests/integration -m integration  # real HA event loop
```

The integration half needs `pytest-homeassistant-custom-component`
(plus `jsonschema websockets pyyaml cryptography`, mirroring
`manifest.json`) and drives the config flow and options flow on Home
Assistant's own flow engine. The `integration` marker is applied to
every test in `tests/integration/` by that directory's `conftest.py` —
don't add it per module.

## How issues are triaged

New issues start with `needs-triage`. After a first look they move to one of:

- `needs-info` — waiting on the reporter (usually versions or a diagnostics bundle);
- `ready-for-agent` — fully specified, small enough to be implemented from the issue text alone, by a person or a coding agent;
- `ready-for-human` — needs judgement, hardware access or a decision;
- `wontfix` — out of scope, with the reason in the closing comment.

Issues labelled `wayfinder:*` belong to a planning map (an issue labelled `wayfinder:map` and its sub-issues); they track release work rather than user reports.

## Home Assistant–specific reminders

- Python file changes require `ha core restart` — a config-entry reload does not reload `.py` files.
- Never modify user dashboards, Lovelace configs, or other HA user state without explicit per-operation permission.
- `OptionsFlow` has five well-known framework traps — see [`docs/ha_config_flow_gotchas.md`](docs/ha_config_flow_gotchas.md) before editing config flow.

## What good PRs look like

- **Minimal.** One logical change per PR.
- **Tested.** Integration tests exist under `tests/` — add to them when you change behaviour.
- **Declarative where possible.** HA entity metadata (category, device_class, units, visibility) goes in `glossary.yaml` / overrides YAML, not hand-rolled in Python.
- **Cap-gated by default.** Never expose a field permissively — either a B5 capability confirms it or the user explicitly overrides.

## License and attribution

By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE). If you have attribution or licensing concerns, please open an issue — we will respond promptly.
