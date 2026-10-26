# Development rules

All commands and paths are relative to the repository root. Linux only.

- Read `CONTRIBUTING.md` and `docs/project-layout.md` before structural changes.
- Keep owned source/config files at most 300 logical lines. Blank lines and
  comments do not count; a visually wrapped Python statement counts once.
- Use blank lines to separate processing stages. Comment intent, protocol
  constraints, failure policy, and non-obvious concurrency decisions.
- Keep all operator configuration, addresses, and lab SIM keys in `app/config/lab.env`.
- Preserve the PCMU/8000 SIP/RTP media contract.
- Keep third-party sources and licenses under `app/infrastructure/vendor/`; report them separately.
- Run `python scripts/check.py` before completing code changes.
- For media/routing changes, rebuild affected images and run applicable live gates.
- Integration gates share one stand and must run serially.
- Never commit private recordings, generated WAVs, or evidence runs.
- Do not publish or push unless the user asks.
