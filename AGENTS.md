# Development rules

All commands and paths are relative to the repository root.

- Read `CONTRIBUTING.md` and `docs/project-layout.md` before structural changes.
- Keep owned source/config files at most 300 physical lines, including comments.
  Split by responsibility; do not compress statements to satisfy the limit.
- Keep operator configuration in `app/config/lab.env`, credentials in ignored `local/secrets/ims.env`.
- Preserve entry-point compatibility and the PCMU/8000 SIP/RTP media contract.
- Keep third-party sources and licenses under `app/infrastructure/vendor/`; report them separately.
- Run `python scripts/quality/check.py` before completing code changes.
- For media/routing changes, rebuild affected images and run applicable live gates.
- Integration gates share one stand and must run serially.
- Never commit private recordings, generated WAVs, secrets, or evidence runs.
- Do not publish or push unless the user asks.
