# ADR-0001: Security remains mandatory, legal procedure may be violated

**Status:** Accepted (architecture, 2026-11-24)

Simulation modes may allow procedurally improper actions to take effect and be reviewed later. This is not permission for actor impersonation, secret evidence leaks, arbitrary tool calls or cross-agent memory access. A security check always takes precedence over mode selection.

Why: deterministic simulation must allow *mistakes in court* without allowing *arbitrary compromise of the simulator*. Record the rejected attempt and the violation assessment separately.
