# AGENTS.md — blaueis-ha-midea

Home Assistant custom integration for Midea ACs via a Blaueis gateway. Consumes `blaueis-libmidea`. The library lives under `custom_components/blaueis_midea/lib/blaueis/{core,client}/` as a build artefact mirroring the libmidea source-of-truth — never edit those files directly. Sync is automated and drift-gated by a pre-commit hook (see "Vendored libmidea" below).

## Linting

```sh
ruff check && ruff format --check
```

Zero warnings expected. Config in `.ruff.toml` (ruff 0.11.x — pinned in the CI lint job and gated by the pre-commit hook); the vendored `lib/` mirror is excluded — it is linted at its source repo.

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

## Vendored libmidea — single source of truth, drift-gated

`blaueis-libmidea` is the canonical source. `custom_components/blaueis_midea/lib/blaueis/{core,client}/` is a mirrored copy maintained automatically. Three tools under `tools/` enforce the no-drift contract:

- `sync_from_libmidea.py` — copies `../blaueis-libmidea/packages/blaueis-{core,client}/src/blaueis/{core,client}/` into the vendored tree. `--check` mode reports drift without writing. Run after any libmidea change before staging the ha-midea side.
- `dev_link_libmidea.py` — replaces the vendored dirs with relative symlinks for a tight edit-test loop (changes in libmidea are immediately visible to HA tests / reload). `--unlink` restores flat-file copies and re-syncs. `--status` reports current mode.
- `pre-commit` (installed into `.git/hooks/` via `tools/install-hooks.sh`) — refuses commits while symlinked, and refuses commits if the vendored tree has drifted from libmidea HEAD. Direct edits to `lib/` cannot land.

**First-time setup after cloning**: `tools/install-hooks.sh`.

**Daily flow**: edit in libmidea → run `tools/sync_from_libmidea.py` in ha-midea → `git commit` (hook validates). Or in dev-link mode: edit libmidea, tests/HA pick it up live; `tools/dev_link_libmidea.py --unlink` before committing.

When libmidea is published (PyPI or GitHub), the long-term plan is to replace the vendored copy with a `requirements:` entry in `manifest.json` and delete `lib/` entirely — the `from blaueis.core import …` imports already in use don't change.

## Code knowledge graph (optional)

An optional [graphify](https://github.com/Graphify-Labs/graphify) index of this
repo may exist under `graphify-out/` (gitignored, never committed). Nothing here
depends on it — build, tests and CI are unaffected when it is absent.

It is **never rebuilt automatically**; no git hook triggers it, because a rebuild
is minutes of disk work and must never fire during a deploy to Home Assistant.
So it goes stale as you commit. **Check first:**

```sh
./tools/graph_refresh.sh --status   # instant; says POTENTIALLY OUT OF DATE when behind
./tools/graph_refresh.sh            # rebuild (minutes)
```

`--status` compares the commit the graph was built from against `HEAD`, so the
answer is exact rather than a cached marker that can itself go stale.

**Rebuilds are opt-in per checkout.** `./tools/graph_refresh.sh` does nothing
unless `.graphify-enabled` exists at the repo root (gitignored, never committed).
`--status` always works — it is read-only and instant.

If that file is absent, treat its absence as deliberate: this working copy may be
a deploy target, a CI runner, a bisect worktree or a throwaway clone, where
minutes of disk churn is exactly what nobody wants. **Do not create it to get
past the gate** — ask first.

The vendored `custom_components/blaueis_midea/lib/` tree is excluded via
`.graphifyignore`: it is a mirror of the upstream library, and indexing it here
would duplicate every upstream symbol. Query the library's own graph for anything
under `lib/`.

**Query it:**

```sh
graphify query "how does X work" --graph graphify-out/graph.json
graphify explain "SymbolName"    --graph graphify-out/graph.json
graphify god-nodes               --graph graphify-out/graph.json
```

**Blind spots — never read absence from the graph as absence in the source.**
It is a navigation aid, not an authority:

- **YAML contributes zero nodes.** graphify ships no YAML extractor despite its
  docs listing one, so `.yaml`/`.yml` files are invisible.
- **JavaScript functions bound as object-literal properties get no node.**
  `function foo() {}`, `const f = function () {}`, `exports.f = …`, `this.f = …`
  and `Foo.prototype.f = …` are all indexed; `{ foo: function () {} }` is not.
  Code written in the object-literal module style is therefore heavily
  under-represented — not all function expressions, specifically that binding.

If a symbol is not in the graph, confirm against the source before concluding
anything. Treat a hit as a pointer worth following, not as proof.
