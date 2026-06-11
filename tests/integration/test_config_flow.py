"""Integration tests — config flow (user step + reauth) and the
auth-failure surfaces in ``async_setup_entry`` / the coordinator.

Runs on the real HA flow engine via pytest-homeassistant-custom-component.
``validate_input`` is patched for the flow-level tests (form routing,
error rendering, entry creation) and the real integration setup is
blocked by ``mock_setup_entry``; validate_input's own exception mapping
(AuthenticationError → InvalidAuth, everything else → CannotConnect) is
covered separately by driving the function directly with a patched
client.
"""

from __future__ import annotations

import sys
from pathlib import Path

# conftest.py adds these, but pytest's collection order can bite —
# import-time path inserts are the safe belt-and-braces.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_VENDORED_LIB = _REPO_ROOT / "custom_components" / "blaueis_midea" / "lib"
if str(_VENDORED_LIB) not in sys.path:
    sys.path.insert(0, str(_VENDORED_LIB))

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from homeassistant import config_entries  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.const import CONF_HOST, CONF_PORT  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402

from custom_components.blaueis_midea.config_flow import (  # noqa: E402
    CannotConnect,
    InvalidAuth,
    validate_input,
)
from custom_components.blaueis_midea.const import CONF_PSK, DOMAIN  # noqa: E402

pytestmark = pytest.mark.asyncio

USER_INPUT = {CONF_HOST: "127.0.0.1", CONF_PORT: 8765, CONF_PSK: "correct-horse"}

_VALIDATE = "custom_components.blaueis_midea.config_flow.validate_input"


@pytest.fixture
def mock_setup_entry():
    """Block the real async_setup_entry behind entry creation/reload.

    Without this, a flow ending in CREATE_ENTRY runs the real setup —
    glossary load, scrypt stretch, and a live websocket connect that
    only fails because pytest-socket blocks it.
    """
    with patch(
        "custom_components.blaueis_midea.async_setup_entry", return_value=True
    ) as mock:
        yield mock


def _reauth_flows(hass: HomeAssistant, entry) -> list[dict]:
    return [
        f
        for f in hass.config_entries.flow.async_progress()
        if f["context"].get("source") == config_entries.SOURCE_REAUTH
        and f["context"].get("entry_id") == entry.entry_id
    ]


# ── User step ───────────────────────────────────────────────────────────


async def test_user_flow_success(hass: HomeAssistant, mock_setup_entry) -> None:
    """Happy path: form → validate ok → entry created with the input."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    with patch(_VALIDATE, return_value={"title": "Blaueis AC (127.0.0.1)"}):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Blaueis AC (127.0.0.1)"
    assert result["data"] == USER_INPUT
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        (CannotConnect, "cannot_connect"),
        (InvalidAuth, "invalid_auth"),
        (RuntimeError, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    mock_setup_entry,
    side_effect: type[Exception],
    expected_error: str,
) -> None:
    """Validation failures re-show the form with the mapped error key."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(_VALIDATE, side_effect=side_effect):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}

    # The flow recovers: a later valid submit still creates the entry.
    with patch(_VALIDATE, return_value={"title": "Blaueis AC (127.0.0.1)"}):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_duplicate_aborts(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """A second entry for the same host:port aborts as already_configured."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: mock_config_entry.data[CONF_HOST],
            CONF_PORT: mock_config_entry.data[CONF_PORT],
            CONF_PSK: "whatever",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ── validate_input exception mapping ────────────────────────────────────


def _tcp_ok():
    """Patch for asyncio.open_connection — successful TCP precheck."""
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return AsyncMock(return_value=(MagicMock(), writer))


def _client_failing_with(exc: Exception) -> MagicMock:
    client = MagicMock()
    client.connect = AsyncMock(side_effect=exc)
    client.close = AsyncMock()
    return client


async def test_validate_input_maps_auth_error_to_invalid_auth(
    hass: HomeAssistant,
) -> None:
    """Key-confirmation failure (wrong PSK) raises InvalidAuth, not
    CannotConnect — and the client is closed (no leaked slot)."""
    from blaueis.core.crypto import AuthenticationError

    client = _client_failing_with(AuthenticationError("PSK mismatch"))
    with (
        patch("asyncio.open_connection", _tcp_ok()),
        patch("blaueis.client.ws_client.HvacClient", return_value=client),
        patch("blaueis.core.crypto.psk_to_bytes", return_value=b"k" * 32),
    ):
        with pytest.raises(InvalidAuth):
            await validate_input(hass, dict(USER_INPUT))
    client.close.assert_awaited()


async def test_validate_input_slot_pool_full_is_cannot_connect(
    hass: HomeAssistant,
) -> None:
    """A plain HandshakeError (capacity refusal, malformed reply) is a
    transient connection problem — never invalid_auth."""
    from blaueis.core.crypto import HandshakeError

    client = _client_failing_with(
        HandshakeError("Gateway refused connection: slot_pool_full")
    )
    with (
        patch("asyncio.open_connection", _tcp_ok()),
        patch("blaueis.client.ws_client.HvacClient", return_value=client),
        patch("blaueis.core.crypto.psk_to_bytes", return_value=b"k" * 32),
    ):
        with pytest.raises(CannotConnect):
            await validate_input(hass, dict(USER_INPUT))
    client.close.assert_awaited()


async def test_validate_input_maps_ws_failure_to_cannot_connect(
    hass: HomeAssistant,
) -> None:
    """Non-handshake connect failures stay CannotConnect."""
    client = _client_failing_with(OSError("connection refused"))
    with (
        patch("asyncio.open_connection", _tcp_ok()),
        patch("blaueis.client.ws_client.HvacClient", return_value=client),
        patch("blaueis.core.crypto.psk_to_bytes", return_value=b"k" * 32),
    ):
        with pytest.raises(CannotConnect):
            await validate_input(hass, dict(USER_INPUT))


# ── Reauth ──────────────────────────────────────────────────────────────


async def test_reauth_flow_success(
    hass: HomeAssistant, mock_config_entry, mock_setup_entry
) -> None:
    """Reauth asks only for the PSK, updates the entry, keeps host/port."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(_VALIDATE, return_value={"title": "ignored"}) as mock_validate:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PSK: "new-key"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    # Revalidated against the STORED host/port with the NEW key…
    validated = mock_validate.call_args[0][1]
    assert validated[CONF_HOST] == mock_config_entry.data[CONF_HOST]
    assert validated[CONF_PSK] == "new-key"
    # …and only the PSK changed on the entry.
    assert mock_config_entry.data[CONF_PSK] == "new-key"
    assert mock_config_entry.data[CONF_HOST] == "127.0.0.1"


async def test_reauth_flow_wrong_psk_shows_error(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """A still-wrong key re-shows the form; the entry stays untouched."""
    mock_config_entry.add_to_hass(hass)
    old_psk = mock_config_entry.data[CONF_PSK]

    result = await mock_config_entry.start_reauth_flow(hass)
    with patch(_VALIDATE, side_effect=InvalidAuth):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PSK: "still-wrong"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data[CONF_PSK] == old_psk


# ── Auth failures outside the flow ──────────────────────────────────────


async def test_setup_entry_auth_failed_starts_reauth(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """An AuthenticationError during setup puts the entry in SETUP_ERROR
    (no retry backoff — retrying a wrong key is pointless) and HA
    auto-creates a reauth flow. Also pins the class-identity contract:
    the AuthenticationError the vendored lib raises must be the same
    object __init__.py catches."""
    from blaueis.core.crypto import AuthenticationError

    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.blaueis_midea.coordinator.BlaueisMideaCoordinator"
        ".async_start",
        AsyncMock(side_effect=AuthenticationError("PSK mismatch")),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert len(_reauth_flows(hass, mock_config_entry)) == 1


async def test_runtime_auth_failure_starts_reauth(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """The runtime chain coordinator._on_auth_failed → __init__ hook →
    entry.async_start_reauth opens exactly one reauth flow (the gateway
    rotated its key while HA was connected)."""
    mock_config_entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.blaueis_midea.coordinator.BlaueisMideaCoordinator"
            ".async_start",
            AsyncMock(),
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data
        # Simulate the vendored reconnect loop hitting a confirmed
        # mismatch (it calls this coordinator method via
        # Device.on_auth_failed).
        coordinator._on_auth_failed("PSK mismatch")
        await hass.async_block_till_done()

        # Fires once even if the device callback repeats — HA dedupes.
        coordinator._on_auth_failed("PSK mismatch")
        await hass.async_block_till_done()

    assert len(_reauth_flows(hass, mock_config_entry)) == 1
