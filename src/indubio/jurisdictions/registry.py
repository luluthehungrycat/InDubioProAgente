"""Explicit lookup of known rulesets; unknown IDs fail instead of silently falling back."""

from collections.abc import Callable

from indubio.jurisdictions.base import JurisdictionRuleset
from indubio.jurisdictions.demo import DEMO_RULESET_ID, DemoRuleset
from indubio.jurisdictions.demo.floor import DEMO_FLOOR_RULESET_ID, DemoFloorRuleset

_KNOWN: dict[str, Callable[[], JurisdictionRuleset]] = {DEMO_RULESET_ID: DemoRuleset}
# Opt-in floor-control packs (``indubio.core.floor``); a separate namespace so a floor
# pack can never be selected as a jurisdiction and vice versa.
_KNOWN_FLOOR: dict[str, Callable[[], JurisdictionRuleset]] = {
    DEMO_FLOOR_RULESET_ID: DemoFloorRuleset,
}


def get_ruleset(ruleset_id: str) -> JurisdictionRuleset:
    try:
        factory = _KNOWN[ruleset_id]
    except KeyError:
        raise ValueError(f"Unknown ruleset: {ruleset_id!r}") from None
    return factory()


def get_floor_ruleset(ruleset_id: str) -> JurisdictionRuleset:
    try:
        factory = _KNOWN_FLOOR[ruleset_id]
    except KeyError:
        raise ValueError(f"Unknown floor ruleset: {ruleset_id!r}") from None
    return factory()
