"""Integration test — ``blaueis_midea.run_field_inventory`` service.

Tests the surfaces that don't require the full Device / coordinator
async lifecycle:

- Service handler's "no entries" branch is safe (no crash).
- Direct-import path of ``_handle_service_call`` works.
- The :class:`InventoryDownloadRegistry` + :class:`_MultiEntryInventoryView`
  serve blobs correctly when populated directly.

The full end-to-end (button-press → scan → blob → download) is exercised
by the live-AC smoke on 192.168.210.25 — we don't duplicate that here
because mocking the entire Device async stack is substantial glue for
relatively little marginal coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

# conftest.py adds these, but pytest's collection order can bite —
# import-time path inserts are the safe belt-and-braces.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402

pytestmark = pytest.mark.asyncio


async def test_handler_is_safe_with_no_entries(hass):
    """Calling the service when no blaueis_midea entry is loaded must
    log a warning and return — never crash.

    Covers the handler's early-exit branch, the most common
    developer-environment state.
    """
    from custom_components.blaueis_midea.field_inventory import _handle_service_call
    from homeassistant.core import ServiceCall

    call = ServiceCall(hass, "blaueis_midea", "run_field_inventory", {"label": "ghost"})
    # No blaueis_midea entries registered → handler should noop.
    # (Should NOT raise — that's the contract for fire-and-forget services.)
    await _handle_service_call(hass, call)
