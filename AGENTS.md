# Development rules

- Read `CONTRIBUTING.md` and `docs/project-layout.md` before structural changes.
- Keep owned source/config files at most 300 physical lines, including comments.
  Split by responsibility; do not compress statements to satisfy the limit.
- Keep operator configuration in `lab.env`, credentials in ignored `secrets/ims.env`.
- Preserve entry-point compatibility and the PCMU/8000 SIP/RTP media contract.
- Keep third-party sources and licenses under `vendor/`; report them separately.
- Run `python tools/quality/check.py` before completing code changes.
- For media/routing changes, rebuild affected images and run applicable live gates.
- Integration gates share one stand and must run serially.
- Never commit private recordings, generated WAVs, secrets, or evidence runs.
- Do not publish or push unless the user asks.
