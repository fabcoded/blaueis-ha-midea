# Contributing to blaueis-ha-midea

Contributions are welcome. This project is MIT-licensed — by submitting a change you agree that your contribution is licensed under the same terms.

## Before you start

- For anything non-trivial, **open an issue first** describing the change and your plan. Small fixes and typo corrections can go straight to PR.
- Read [`AGENTS.md`](AGENTS.md) — it describes the integration's conventions, test expectations, and reload-vs-restart rules.
- The Python library this integration consumes is vendored under `custom_components/blaueis_midea/lib/`. Protocol or glossary changes belong upstream in [blaueis-libmidea](https://github.com/fabcoded/blaueis-libmidea), not here — submit those there and then bump the vendored snapshot.

## Citation rule — the one that matters

This integration builds on community research (see [README.md#acknowledgments](README.md#acknowledgments)). When editing, **never**:

- Reference file paths, function names, or line numbers from external implementations in code, comments, or documentation.
- Copy content from external source code — comments, variable names, logic blocks.

Structured-provenance fields (`alt_names:` / `sources:` in the vendored `glossary.yaml`) are the one exception. See the glossary's file-header comments and the workspace-level `AGENTS.md` for the rule.

## Development setup

Clone into `<HA config>/custom_components/blaueis_midea/` (symlink recommended for development) and restart HA.

Install the git hooks once after cloning — they run the same lint and formatting gates as CI:

```sh
pip install pre-commit   # if you don't already have it
./tools/install-hooks.sh
```

Two of the hooks guard the vendored `lib/` mirror and are only meaningful inside the development workspace. Without a sibling `blaueis-libmidea` checkout they skip with a warning rather than blocking your commit.

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
