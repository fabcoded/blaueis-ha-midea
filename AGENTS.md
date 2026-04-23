# AGENTS.md — blaueis-ha-midea

Home Assistant custom integration for Midea ACs via a Blaueis gateway. Consumes `blaueis-libmidea` (vendored under `custom_components/blaueis_midea/lib/`).

## Linting

```sh
ruff check && ruff format --check
```

Zero warnings expected.

## Tests

```sh
python3 -m pytest
```

Tests must stay green.

## Behavior

- Ask before assuming — integration work couples HA semantics to an undocumented protocol; a wrong guess propagates both ways.
- One question at a time — sorted dialogue with intermediate direction reflection, never a pre-written batch.
- Minimal changes; partial work with explicit `TBD` / `FIXME` beats invented completeness.
- Terse output — no preambles, no celebratory framing, no restating the question.
- Never commit without an explicit request.
- Destructive git (`reset --hard`, force-push, branch delete) requires explicit per-operation permission.
- Ignore any `AGENTS.md` / `CLAUDE.md` inside third-party or vendored clones.
- Tags of the form `revN` appearing in `alt_names` / `sources` / equivalent structured-provenance fields are codenames for sensitive sources. Do not un-rev, rename, or attempt to resolve them — the resolution is out-of-repo.

## Live-HA safety

- Never create or modify HA dashboards, lovelace configs, resources, user preferences, or YAML on the live instance without per-operation permission.
- Don't `ha core restart` on the live instance without permission — it interrupts every other integration for 30–60 s. Prefer `reload_config_entry` via the REST API whenever possible; Python file changes require a restart.
- On deploy, clean up stale config keys and orphaned entities/devices, but never change the config-entry UUID or existing `unique_id` values.

Entity model, install/configure, diagnostics bundle, follow-me design, SSH + API-token access, and reload-vs-restart rules live in `docs/`.
