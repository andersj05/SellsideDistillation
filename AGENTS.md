# Repository working instructions

- Work on `feat/<feature-name>` branches based on `dev`; merge through PRs to `dev`, then promote `dev` to `main`.
- Make frequent small commits after coherent, tested changes. Push feature work regularly. Preserve the user's uncommitted changes.
- Run `uv run --frozen --offline python scripts/check.py` for implementation changes. Fix required checks before promoting a PR. CI covers Linux/Windows and Python 3.12–3.14.
- Keep supplied reports, generated data/runs/evaluations, exports, databases, and credentials out of Git. Use invented test data and inspect staged diffs.
- The implemented application is an offline deterministic fixture lab. Preserve the evidence interface and independent evaluator. Document incomplete research capabilities accurately.

## GitHub CLI authentication

- The Windows GitHub CLI account `andersj05` is stored in Windows Credential Manager.
- The workspace sandbox can block outbound GitHub traffic and make `gh auth status` report an invalid token incorrectly.
- Verify GitHub operations outside the sandbox with the narrowest appropriate approval. Recommend re-authentication only if that outside-sandbox check reports an actual authentication failure.
- Do not recommend `gh auth logout` or `gh auth login` based only on a sandboxed check.
