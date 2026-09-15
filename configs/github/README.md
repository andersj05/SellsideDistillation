# GitHub settings

These payloads configure `andersj05/SellsideDistillation`. Run with repository administrator permissions after the named checks exist:

```powershell
gh api --method PUT repos/andersj05/SellsideDistillation/branches/main/protection --input configs/github/branch-protection.json
gh api --method PUT repos/andersj05/SellsideDistillation/branches/dev/protection --input configs/github/branch-protection.json
gh api --method PUT repos/andersj05/SellsideDistillation/actions/permissions --input configs/github/actions-permissions.json
gh api --method PUT repos/andersj05/SellsideDistillation/actions/permissions/selected-actions --input configs/github/allowed-actions.json
```

The check app ID `15368` was verified against this repository's successful GitHub Actions checks. The separate PR-only branch-policy check prevents a successful push build from satisfying the routing requirement.

Keep the default workflow token read-only, disallow Actions approval of PRs, enable vulnerability alerts, secret scanning/push protection, and private vulnerability reporting. Dependabot version updates target `dev`; security alerts are remediated through feature PRs. Release promotion uses merge commits and retains branches.

GitHub settings are external state: editing these JSON files alone does not apply them. Re-read the live settings after changes. See the [branch protection API](https://docs.github.com/en/rest/branches/branch-protection) for the payload contract.
