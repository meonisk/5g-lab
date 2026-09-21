# Preparing and publishing the Git repository

The publication unit is this `lab-docker` repository. Sibling `ims`,
`asterisk_legacy` and `5g-arseny` repositories are not required by its startup.
No hosting provider or remote URL is assumed.

## Before a push

From the repository root:

```bash
python scripts/quality/check.py
python scripts/quality/check_git.py --history
git status --short
git diff --check
git remote -v
```

Stage intended changes before running the Git check: it checks the index that
will be committed. The optional history pass checks all reachable local refs.
Local credential comparisons run when `local/secrets/ims.env` exists; a fresh
clone still checks prohibited paths, executable modes and selected signatures.
Neither check is a comprehensive secret scanner or a runtime acceptance test.

Commit the reviewed changes. Publish the intended branch explicitly rather than
using `--mirror` or `--all`. Configure the destination only after the repository
URL and visibility are chosen; credentials belong in a credential manager,
not in a remote URL, source file or documentation.

## Distribution contents

Include tracked source, public configuration, synthetic text fixtures, scripts,
documentation and upstream notices. Do not upload the enclosing workspace or
an Explorer ZIP: ignored files can still be included by filesystem archivers.
Exclude `local/`, `.git/` directory copies, recordings, transcripts, packet
captures, credentials, model caches and Git backup bundles.

For a source-only archive, after committing:

```bash
git archive --format=zip --prefix=lab-docker/ --output=../lab-docker-source.zip HEAD
```

This exports the committed tree, with executable modes stored by Git. It omits
uncommitted changes and local state. Development checks use Git metadata, so
use a clone for development/validation rather than the source-only ZIP.
The older workspace ZIP is not a publication artifact.

## Local history sanitization

Publication preparation removed laboratory credential literals from source and
reachable history. Original Git history is retained only in an ignored local
backup bundle; replacement expressions and migration maps are private tooling.
Do not publish those backups, copy the old `.git`, or merge old unsanitized refs.
Historical documents and private manifests may retain their original commit IDs
and hashes; those are provenance, not current validation claims.

The active stand's local credentials are preserved. History sanitization does
not revoke credentials or alter existing subscriber databases. If an older
archive was shared, rotate the affected lab credentials and reprovision before
reusing that stand outside its isolated environment.

## Publication scope

Read [status.md](status.md) before describing this as a release. Source readiness
does not close the live-startup, latency, physical-stand or research gates.
Third-party notices remain in place. A project-wide license for original code
has not been selected; publishing source must not imply a grant of rights that
the owner has not chosen. See [THIRD_PARTY.md](../THIRD_PARTY.md).
