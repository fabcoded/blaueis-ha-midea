# Feature gating in the integration

> How the library's offer gate surfaces in Home Assistant: which entities/presets
> appear depends on the current device state (capability, mode, interlocks, power).
> The gating **model** lives in the vendored library —
> `blaueis-libmidea/docs/feature_gating.md`. This doc covers only the HA-side wiring.

---

## 1. The two offering sites

The gate evaluator (`blaueis.core.gate_eval.evaluate_offered`) is consulted at exactly
two places — both decide *whether to offer*, never how to write:

- **`_ux_mixin.field_ux_available(coordinator, field_name)`** — backs the `available`
  property of every per-field entity (switch / sensor / number / select / button). An
  entity fades when the gate says the field isn't offered (and also when the device is
  disconnected or stale — those liveness checks run first).
- **`climate._preset_visible(field_name)`** — decides which presets appear in the climate
  entity's preset list (e.g. a heat-only preset is hidden in cool).

A field with no `gate:` block reduces to the prior behaviour (`is_field_visible`), so
adding the evaluator was parity-preserving until a field opts in.

## 2. What each site plumbs into the evaluator

```python
evaluate_offered(
    gdef,
    mode=device.read("operating_mode"),
    power_on=True,                                  # see §3
    active_constraints=device.active_constraints(field_name),
    field_states=interlock_states(device, gdef),   # only the gate's interlock deps
    caps=device.caps_bitmap(),
)
```

- **`active_constraints`** — the field's cap-derived constraints (`valid_set`, …) for the
  capability-mode axis. Read via `device.active_constraints(name)`.
- **`field_states`** — `interlock_states(device, gdef)` builds a `{dep: value}` map for
  *only* the fields this gate's `interlocks` reference (usually zero), so the per-check
  cost stays bounded. Values come from `device.read`, which returns the **retained**
  decoded value even for hidden/excluded dependencies (see the library's
  decode-retention section).
- **`caps`** — the B5 flag bitmap for `ux.hardware_flag`.
- **`cap_values`** *(pending — eco-variant increment)* — `device.cap_values()` will be
  passed once the `mode_forks` axis lands, after a live engagement test.

## 3. Why `power_on=True`

Both sites pass `power_on=True` on purpose: power-state fading is already handled
upstream — `_ux_mixin` gates on `coordinator.device_fresh`, and the climate preset list
returns none-only when the device is off. Passing `True` keeps the evaluator's power axis
inert here, so this layer is parity with the prior mode gate plus the now-live capability
and interlock axes.

## 4. The wire path is NOT gated here

The command builder (`blaueis.core.command`) keeps its own small `is_field_visible` mode
mask to zero stale bits on outgoing frames. It does **not** consult the gate evaluator —
the offer gate is advisory (UI availability) and must never change wire behaviour. Keep
these two concerns separate.

## 5. Vendored boundary

`gate_eval`, `gate_anchors`, the gate schema, and capability ingestion all live in the
vendored library under `custom_components/blaueis_midea/lib/blaueis/`. Edit them in the
`blaueis-libmidea` source and re-vendor with `tools/sync_from_libmidea.py`; direct edits
to the vendored tree are overwritten. Only the two offering sites and the
`interlock_states` helper are integration-side code.

---

See `blaueis-libmidea/docs/feature_gating.md` for the gating model, the `gate:` block
schema, the evaluator semantics, and the bit-position anchors.
