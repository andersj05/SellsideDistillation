# Reporting security issues

Report a suspected vulnerability privately through [GitHub private vulnerability reporting](https://github.com/andersj05/SellsideDistillation/security/advisories/new). Include the affected commit, realistic input/control available to an attacker, expected behavior, actual behavior, and a minimal synthetic reproduction.

Keep credentials, private research reports, and sensitive exploit data out of public issues and pull requests. Ordinary correctness bugs can use the public bug template with invented inputs.

The current application is a local, single-user, deterministic fixture CLI. It has no hosted service or live model route. Its evidence interface limits the bundled adapter's tool access; it does not isolate arbitrary Python from the host. Run manifests detect changes relative to a saved inventory and do not authenticate its owner. See the [README](../README.md) and [audit record](../docs/audit-2026-09-15.md) for implemented controls and limits.

This document describes reporting and current implementation context. It adds no finding exclusions, accepted risks, or scanner suppression rules. Any future live or shared deployment requires a fresh security review of its actual boundaries.
