# AI-automation runbook — programmatic HA access

> How an AI agent (or any script) connects to a Home Assistant instance
> running this integration, applies and verifies glossary overrides,
> and walks the diagnostic chain when something looks wrong. Generic —
> no instance-specific values appear in this doc; substitute your own
> from local config.

---

## 1. Variables

This runbook uses four placeholders end-to-end. Substitute from your
own local config; never paste real values into commits, issue reports,
or any artefact that leaves your machine.

| Placeholder | What it is | Where you get it |
|---|---|---|
| `${HA_URL}` | HA base URL, e.g. `http://10.0.0.10:8123` | Your HA install. Workspace conventions for local dev are in `../AGENTS.md` ("Workspace-local dev environment"). |
| `${HA_TOKEN}` | Long-lived API token | HA → your user profile → Security → "Long-Lived Access Tokens" → Create. Workspace dev convention stores this at the path documented in `../AGENTS.md`. **Never log, commit, or transmit this value.** |
| `${ENTRY_ID}` | Config-entry id for the Blaueis Midea integration on a specific install | One-shot lookup — see §3.1. |
| `${DEVICE_ID}` | HA device id for the AC the integration owns | One-shot lookup — see §3.2. |

For brevity below, all REST examples assume:

```sh
export HA_URL="…"
export HA_TOKEN="…"
H='-H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json"'
```

The `$H` shorthand keeps the auth header out of every example.

---

## 2. Two protocols: REST and WebSocket

HA exposes two API surfaces. They overlap, but each has things only it
can do:

| Surface | Use it for |
|---|---|
| **REST** | One-shot reads, single service calls, downloading diagnostics. Stateless. Easy to script. |
| **WebSocket** | Anything that drives config-flow / options-flow (including the Glossary-Overrides textarea), real-time entity state subscriptions, integration reload signals. Stateful — open one connection per agent session, multiplex. |

Most of the override-verification flow uses WebSocket because the
options flow is WebSocket-only.

---

## 3. REST cookbook

### 3.1 Find the integration's config entry

```sh
curl -s $H "${HA_URL}/api/config/config_entries" | \
  jq '.[] | select(.domain == "blaueis_midea") | {entry_id, title, state}'
```

Pick the entry whose `state` is `"loaded"`. Stash its `entry_id` as
`${ENTRY_ID}` for the rest of the session.

### 3.2 Find the AC's device id

```sh
curl -s $H "${HA_URL}/api/config/config_entries/entry/${ENTRY_ID}" | \
  jq '.entry_id'  # entry exists check
# Devices are exposed via the WebSocket device registry — see §4.2.
# REST has no first-class device list endpoint.
```

If you only need to query *entities* (most of the integration's
surface), the prefix-based pattern in §3.3 is enough — you don't need
`${DEVICE_ID}` for that.

### 3.3 List entities under the integration

```sh
curl -s $H "${HA_URL}/api/states" | \
  jq '[.[] | select(.entity_id | startswith("sensor.${ENTRY_PREFIX}_") or
                                  startswith("switch.${ENTRY_PREFIX}_") or
                                  startswith("climate.${ENTRY_PREFIX}_"))]'
```

Replace `${ENTRY_PREFIX}` with the slug HA gave the integration (visible
on any one of its entities). The integration uses one prefix per device.

### 3.4 Read a single entity

```sh
curl -s $H "${HA_URL}/api/states/sensor.${ENTRY_PREFIX}_indoor_temperature" | \
  jq '.state, .attributes'
```

`unknown` for `state` means the integration hasn't decoded a value yet
(or never will — see §6.2 debug recipe).

### 3.5 Reload the config entry

After a glossary-override change, the entry needs to reload for the
override to apply. Submitting a new override via the options flow
(§4.3) triggers reload automatically; if you patched options some
other way, reload explicitly:

```sh
curl -s -X POST $H "${HA_URL}/api/config/config_entries/entry/${ENTRY_ID}/reload"
```

Wait for state to return to `loaded` (§3.1) before assuming the new
override is in effect.

### 3.6 Pull integration logs

The error log endpoint returns the whole `home-assistant.log` since
HA started — grep for `blaueis_midea` to filter.

```sh
curl -s $H "${HA_URL}/api/error_log" | grep blaueis_midea | tail -50
```

For finer control, configure a per-component log level via the
`logger` component (one-shot, until next restart):

```sh
curl -s -X POST $H "${HA_URL}/api/services/logger/set_level" \
  -d '{"blaueis_midea": "debug"}'
```

### 3.7 Download diagnostics

The richest single artefact for debugging. Includes entry config,
gateway session info, the structured `glossary_override` block (§5),
the local + gateway debug rings, and a list of available decoded
fields.

```sh
curl -s $H -o diagnostics.json \
  "${HA_URL}/api/config/diagnostics/config_entry/${ENTRY_ID}"
jq '.glossary_override' diagnostics.json
```

The diagnostics JSON is auto-redacted for `psk` / `token` / `password`
keys before HA returns it, but always inspect before sharing — the
`combined_records` array contains raw frame dumps that can include
device serial numbers.

---

## 4. WebSocket cookbook

REST can't drive HA's config-flow. The options flow that owns the
Glossary-Overrides textarea is a multi-step state machine reached
only via WebSocket commands.

### 4.1 Open a WebSocket and authenticate

```python
import asyncio, json, websockets

async def open_ha_ws(url: str, token: str):
    ws = await websockets.connect(url.replace("http", "ws") + "/api/websocket")
    hello = json.loads(await ws.recv())  # {"type": "auth_required", ...}
    await ws.send(json.dumps({"type": "auth", "access_token": token}))
    auth_ok = json.loads(await ws.recv())
    assert auth_ok["type"] == "auth_ok", auth_ok
    return ws

async def call(ws, msg: dict, msg_id: int) -> dict:
    msg["id"] = msg_id
    await ws.send(json.dumps(msg))
    while True:
        reply = json.loads(await ws.recv())
        if reply.get("id") == msg_id and reply.get("type") == "result":
            return reply
```

Every command pair you send carries a unique monotonic `id`. The
helper above picks results out of the stream by id.

### 4.2 Read the device registry

```python
result = await call(ws, {"type": "config/device_registry/list"}, 1)
my_devices = [
    d for d in result["result"]
    if any(c[0] == "blaueis_midea" for c in d["identifiers"])
]
device_id = my_devices[0]["id"]      # = ${DEVICE_ID}
```

### 4.3 Drive the options flow (Glossary-Overrides textarea)

The options flow is a three-step dance:

```python
async def submit_override(ws, entry_id: str, yaml_text: str, msg_id_start: int = 100):
    # Step 1: open the options flow for this entry. Returns the
    # initial form schema.
    init = await call(ws, {
        "type": "config_entries/options/flow",
        "handler": entry_id,
    }, msg_id_start)
    flow_id = init["result"]["flow_id"]

    # Step 2: post the form's user_input. Pass every field the form
    # asks for (the readonly display fields are dropped server-side).
    # The override goes in `glossary_overrides_yaml`.
    submit = await call(ws, {
        "type": "config_entries/options/configure",
        "flow_id": flow_id,
        "user_input": {
            "follow_me_function_configured": False,
            "follow_me_function_enabled": False,
            "follow_me_function_sensor": "",
            "follow_me_function_guard_temp_min": -15.0,
            "follow_me_function_guard_temp_max": 40.0,
            "follow_me_function_safety_timeout": 300,
            "glossary_overrides_yaml": yaml_text,
            "run_inventory_scan_now": False,
        },
    }, msg_id_start + 1)

    # Step 3: outcome. Two shapes:
    #   {"type": "create_entry", "data": {…}}   → success, options saved
    #   {"type": "form", "errors": {…}, "description_placeholders":
    #     {"override_error": "…"}}               → validation failed
    return submit["result"]
```

**Field omissions matter** — voluptuous treats omitted Optional fields
with non-empty defaults as "submit the default", which can resurrect
stale state. Always pass every field you read from `init["result"]
["data_schema"]`.

The integration's parse-status field (`override_parse_status_display`)
is a read-only display: server-side it's popped from `user_input` and
recomputed from the *stored* YAML on every form render. You don't need
to populate it on submit.

### 4.4 Subscribe to entity state changes

For real-time verification after an override, subscribe before
reloading and watch state events flow:

```python
sub = {"type": "subscribe_events", "event_type": "state_changed"}
await ws.send(json.dumps({**sub, "id": 200}))
# Read events until your verification condition matches; cancel via
# {"type": "unsubscribe_events", "subscription": 200}
```

Filter on `event["data"]["entity_id"]` matching the integration's
prefix.

---

## 5. Override verification recipe

Canonical workflow when an agent submits a glossary override and
needs to confirm it took effect.

```text
1. Submit YAML via WebSocket options flow (§4.3)
2. Inspect submit result:
   ├─ create_entry → validation passed; entry will reload
   └─ form with errors → validation failed; read description_placeholders.override_error
3. (success path) Wait for entry state to return to "loaded" (§3.1)
4. Pull diagnostics (§3.7)
5. Inspect diagnostics.glossary_override:
   ├─ yaml          — what's stored (verify it matches what you submitted)
   ├─ affected_paths — leaf paths the merge changed
   └─ messages       — structured per-field gating outcomes:
                       severity / code / field / reasons / message
6. Verify entity registry matches expectation:
   - For excluded_accepted / excluded_caveat fields: entity should now exist
     under the integration's prefix (§3.3)
   - For excluded_rejected fields: entity should NOT exist (override stripped)
7. (Optional) Read each surfaced entity's state (§3.4) — caveat fields
   may be `unknown` until the next poll cycle populates them
```

Read the `messages` array's `code` field to dispatch:

| `code` | Meaning | Expected outcome |
|---|---|---|
| `protected_key` | Top-level `meta` block stripped | Override still applied |
| `excluded_accepted` | Override on a `unnecessary_automation`-only field | Field surfaces normally |
| `excluded_caveat` | Override on a field with a caveat reason (`never_observed`, `never_tested_write`, `decode_unverified`, `unknown_technical_background`) | Field surfaces; user accepts the caveat. **Verify behaviour with care** — the field's decoder or write path is unverified |
| `excluded_rejected` | Override on a field with `protocol_inert` / `unknown_semantic` / `unsafe_write` | Field is **not** surfaced; the patch was stripped. The diagnostic message names which reason blocked it |

For the closed reason vocabulary and what evidence promotes a field
out of each reason, see
`../blaueis-libmidea/docs/exclusion_reasons.md`.

---

## 6. Debugging recipes

### 6.1 "My override doesn't seem to take effect"

```text
1. ${HA_URL}/api/config/config_entries → state must be "loaded"
   (if it's "setup_in_progress" or "setup_error", the integration
    hasn't finished applying — check logs §3.6)
2. Inspect the override-parse-status field (Configure dialog,
   below the YAML textarea):
   ├─ "parse failed (check log)" → YAML invalid or schema-rejected;
   │   integration is ignoring the override at runtime. Re-fetch
   │   logs and look for "Glossary override rejected:" or
   │   "Stored glossary override failed re-validation".
   ├─ "parse with warning (check log)" → applied but with caveats;
   │   look for "Glossary override [excluded_caveat]" log lines.
   ├─ "parse ok" → applied cleanly. The change you expected may
   │   not be in your YAML — re-read what's stored.
   └─ "" (empty) → no override stored. Did your submit succeed?
3. Pull diagnostics (§3.7) → glossary_override.affected_paths must
   list the leaf paths you intended to change. If the list is empty
   or wrong, your YAML probably edited something other than what you
   thought. Compare the YAML to the base glossary at
   ../blaueis-libmidea/packages/blaueis-core/src/blaueis/core/data/glossary.yaml
4. Reload the entry explicitly (§3.5). Most options changes
   auto-reload, but a hand-edited config_entries.json does not.
```

### 6.2 "An entity reads `unknown` when I expect a value"

```text
1. Verify the entity exists in the registry (§3.3). Missing ⇒ either
   it's never registered (cap not advertised, or excluded reason
   stripped it) or the integration is mid-setup.
2. Pull diagnostics (§3.7) → available_fields must contain the
   underlying field name. If absent, the device's B5 capability
   probe didn't advertise it.
3. Diagnostics.combined_records includes the recent frame traffic.
   Filter for the frame protocol_key the field is decoded from
   (e.g. rsp_0xc0, rsp_0xa1) and check whether the field's bytes
   carry expected values. `unknown` plus all-zero frames usually
   means the device doesn't populate that field.
4. If the decode looks wrong on the wire: the field's glossary
   entry may carry a decode_unverified or never_observed reason —
   surface this issue against the protocol researchers, not against
   the integration.
```

### 6.3 "Capability probe disagrees with my unit"

```text
1. diagnostics.gateway_info should show the cap-probe results.
2. Compare against the field's capability block in
   ../blaueis-libmidea/packages/blaueis-core/src/blaueis/core/data/glossary.yaml.
3. If a cap is advertised but the corresponding feature doesn't
   work: that's a unit-specific firmware quirk. Hard-override the
   field via Glossary Overrides (§4.3) — but expect a caveat or
   rejection per §5.
4. If a cap is NOT advertised but the feature does work on your
   unit: capture frames showing the feature in use and contribute
   them upstream — this is exactly the evidence that promotes a
   field out of `never_observed`.
```

### 6.4 Quick sanity script

For a one-shot "is everything fine right now":

```sh
curl -s $H "${HA_URL}/api/config/config_entries" | \
  jq --arg domain blaueis_midea \
     '.[] | select(.domain == $domain) |
            {entry_id, state, error_reason: (.reason // "")}'
```

Any entry with `state != "loaded"` or a non-empty `error_reason`
needs investigation. Pull its log lines (§3.6) and diagnostics (§3.7).

---

## 7. Privacy & safety conventions

Agents working with HA touch user-identifiable state. Apply these
rules before any artefact leaves the local machine:

1. **Never log, commit, or transmit `${HA_TOKEN}`.** It grants full
   API access. Treat it like a password — read from local config,
   pass via env var, never include in git diffs, issue reports,
   shared logs, or AI conversation transcripts that persist beyond
   the working session.

2. **Never include `${HA_URL}` in shared artefacts.** A LAN address
   plus an integration name plus a token grants entry. Generalise
   to `${HA_URL}` in any output that crosses the local boundary.

3. **Redact device IDs, entity IDs, and serial numbers before
   sharing diagnostics.** The integration auto-redacts `psk` /
   `token` / `password` keys, but `combined_records` contains raw
   frame dumps that may include serials. Use `jq` to strip:

   ```sh
   jq 'del(.combined_records, .gateway_session)' diagnostics.json
   ```

   …before attaching to a public issue. The ring records are
   useful for *your* debugging but rarely needed for upstream
   reports.

4. **Cross-reference the workspace AGENTS.md.** The
   `../AGENTS.md` file at the workspace root carries the public /
   private boundary rules that apply to any commit on a public
   repo. Pre-commit leak scanning is mandatory for changes in this
   repo (see "Pre-commit hygiene" section there).

5. **Live-gateway operations are gated.** The `../AGENTS.md`
   "Live-gateway safety" section in `blaueis-libmidea/AGENTS.md`
   reserves explicit per-operation approval for the gateway
   update flow and direct edits under `/opt/blaueis-gw/`. Don't
   trigger those from this runbook without confirming intent
   with the human first.

---

## 8. Scope of this runbook

In scope: REST + WebSocket recipes for the existing integration's
documented surface, plus the override-verification flow that the
exclusion-reasons feature added.

Out of scope: live-gateway WebSocket protocol, frame decoding,
glossary editing — these live in `../blaueis-libmidea/docs/`
(`ws_protocol.md`, `architecture.md`, `disabled_fields.md`,
`exclusion_reasons.md`).

When the integration grows new options-flow steps or adds new
config-entry-level diagnostic blocks, this runbook should grow with
them — keep it current. The `Pre-commit hygiene` rule in
`../AGENTS.md` mandates doc updates alongside code changes.
