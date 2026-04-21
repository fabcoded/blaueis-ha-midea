# HA config-flow / options-flow gotchas

Five Home Assistant framework behaviours that are not obvious from the
docs and broke shipped code in this integration during 2026-04-21
development. Read this **before** adding or modifying anything in
``config_flow.py``.

Each entry: what bites, why it happens, how to avoid. Inline code
comments at the fix sites point back to the entry name here.

## 1. `async_create_entry(data=user_input)` REPLACES options

`OptionsFlow.async_create_entry(data=...)` does **not** merge with the
existing `entry.options` — it replaces them entirely. Any field
omitted from the form (e.g. by conditional cap-gating) is wiped on
every save.

**Symptom:** user installs a glossary override that hides the
`screen_display` cap → the form omits `display_buzzer_mode` → next
save (e.g. for an unrelated Follow-Me change) silently loses the
stored `display_buzzer_mode` policy. When the override is removed and
the cap returns, the policy is gone.

**Fix pattern:** always merge before save —

```python
new_options = {**self._config_entry.options, **user_input}
return self.async_create_entry(title="", data=new_options)
```

See `config_flow.py` `async_step_init` final return.

## 2. `vol.Optional(key, default=NON_EMPTY)` substitutes the default for empty submissions

When `default=` is anything other than empty/null, voluptuous treats an
empty submission as "use default" — meaning the user can never CLEAR
the field via the UI. Every empty submit gets replaced by whatever
non-empty default you provided.

**Symptom:** initial implementation pre-populated the
`glossary_overrides_yaml` field with a comment template as the
default. Users could install overrides but never remove them — every
clear-attempt restored the template (which itself was schema-valid).

**Fix pattern:** for clearable text fields, default to the stored
value or `""`, never a non-empty placeholder. Put guidance text in
`data_description` (the field's help text), not in the value.

```python
vol.Optional(
    CONF_FIELD,
    default=opts.get(CONF_FIELD, ""),
): selector.TextSelector(...)
```

## 3. Single-option `SelectSelector` is a *validator*, not a UI hint

`selector.SelectSelector(options=[only_current_value])` looks like a
"locked / read-only" widget but voluptuous treats the options list as
an enum constraint. The form rejects ANY submission whose value
disagrees with the single allowed option — including submissions
where the user only changed unrelated fields.

**Symptom:** Path B "show but locked when cap unavailable" implementation
locked `display_buzzer_mode` to its current value when the cap was
overridden away. User then tried to clear the YAML override (a
different field) → form rejected the entire submission with
``value must be one of ['forced_off']`` → deadlock; only an SSH /
direct storage edit could break out.

**Fix pattern:** when a field needs to be "shown but inert", either
**hide it entirely** (Path A — preferred, used here) or include all
its valid values even when the UI semantically "locks" it (Path B
done right). Never reduce the options list to one entry.

## 4. Multi-step flows ending with empty `data_schema` strip the data

If you build a multi-step flow where the final step shows
``data_schema=vol.Schema({})`` (e.g. a confirmation step with no input
fields) and call ``async_create_entry(data=stash)`` from it, HA
filters `stash` through the empty schema → empty options stored.

**Symptom:** initial implementation had an "Applied overrides"
confirmation step that returned `async_create_entry(data=pending)`.
Pending had the YAML and policy correctly. Stored options ended up
empty — every save lost everything.

**Fix pattern:** keep the flow single-step. If you genuinely need
post-save user feedback, write to storage explicitly via
``self.hass.config_entries.async_update_entry(entry, options=stash)``
before returning a no-op `async_create_entry(data={})`.

In this integration: the confirmation step was removed entirely; the
user gets feedback via integration log lines, the entity going
unavailable (visible result), and the diagnostics download.

## 5. Missing `description_placeholders` keys → "invalid flow configured"

If `strings.json` (or `translations/en.json`) references a placeholder
like ``{override_error}`` in a step's description, **HA fails the
entire flow** with "invalid flow configured" if that key isn't in the
`description_placeholders` dict on a normal render.

**Symptom:** description had ``"… {override_error}"``. On the happy
path (no error), the placeholder dict was empty, HA threw, the form
never opened.

**Fix pattern:** always supply every referenced placeholder with at
least an empty string —

```python
placeholders = {"override_error": extra_description or ""}
return self.async_show_form(..., description_placeholders=placeholders)
```

## Bonus traps from the same session

These aren't OptionsFlow-specific but bit during the same work.

### `strings.json` is not enough — runtime needs `translations/<lang>.json`

`strings.json` is a development source-of-truth for translators. HA's
runtime loads `translations/<lang>.json` (e.g. `translations/en.json`)
from the integration directory. Without it, the UI shows raw
translation keys (`display_buzzer_mode_unsupported`) instead of
labels.

For custom integrations the standard pattern is to keep both files
identical (copy `strings.json` → `translations/en.json` on each
update). Browser caches translations aggressively — after deploying a
new translation, tell users to hard-refresh.

### HA REST API does not return `options` in entry list

`/api/config/config_entries/entry` returns a list of entries with
metadata but **omits the `options` field**. To verify what's actually
persisted, read `/config/.storage/core.config_entries` directly.
Verifying via the REST API will give false negatives.

### HA storage writes are async-debounced — wait before restart

`async_update_entry` queues a disk write but does not wait for it.
Calling `ha core restart` immediately after a save can lose the
in-memory state if the disk flush hasn't happened. Wait at least
~5 seconds after a save before restarting, or rely on graceful
shutdown to flush.

### Module-level Python changes need full HA restart

`homeassistant.reload_config_entry` only re-runs `async_setup_entry`
— it does not re-import Python modules. Module-level changes
(constants, helper functions, top-level imports) require
`ha core restart`. If your new code's debug log doesn't appear after a
config-entry reload, that's the cause.

## See also

- `config_flow.py` — every fix site has an inline comment naming the
  trap above.
- `__init__.py` — entity-cleanup pass uses the
  `SYNTHETIC_ENTITY_CAP_DEPENDENCIES` map (`const.py`) to extend the
  field-driven sweep to synthetic entities with cap dependencies.
- `glossary_overrides.md` — user-facing docs for the override feature
  these traps were discovered building.
