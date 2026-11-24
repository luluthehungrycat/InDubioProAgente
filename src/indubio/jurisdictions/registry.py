"""Explicit lookup of known rulesets; unknown IDs fail instead of silently falling back."""

from collections.abc import Callable

from indubio.jurisdictions.base import JurisdictionRuleset
from indubio.jurisdictions.demo import DEMO_RULESET_ID, DemoRuleset

_KNOWN: dict[str, Callable[[], JurisdictionRuleset]] = {DEMO_RULESET_ID: DemoRuleset}


def get_ruleset(ruleset_id: str) -> JurisdictionRuleset:
    try:
        factory = _KNOWN[ruleset_id]
    except KeyError:
        raise ValueError(f"Unknown ruleset: {ruleset_id!r}") from None
    return factory()
