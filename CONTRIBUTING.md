# Contributing to blaueis-ha-midea

Contributions are welcome. This project is CC0 — by submitting a change you agree that your contribution is dedicated to the public domain under the same terms.

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

For test-suite and lint work:

```sh
ruff check && ruff format --check
python3 -m pytest
```

Tests must stay green (123 currently).

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

By contributing, you dedicate your contribution to the public domain under [CC0 1.0 Universal](LICENSE). If you have attribution or licensing concerns, please open an issue — we will respond promptly.
