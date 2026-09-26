# S-CSCF registrar contact guard

The pinned S-CSCF image's `lookup()` scans linked IMPU contacts. If every
contact is invalid or expired, the scan ends with `impucontact == 0` while
`ptr` can still point to the last rejected contact. The existing guard checks
only `ptr == 0`, so the function may rewrite the Request-URI toward that
rejected contact. The one-line patch checks both values before routing.

Build from the repository root:

```powershell
.\scripts\compose.ps1 build scscf
```

The Dockerfile pins the base image by digest, requires embedded Kamailio commit
`9874599e41fa69cc3807676a7995a135a350a9ba`, and checks the unmodified
`lookup.c` SHA-256 and patch SHA-256 before applying it. It rebuilds only
`ims_registrar_scscf` and copies that module and its patched `lookup.c` into the same pinned runtime
image. The base image's other modules and configuration are unchanged.

The vendored [patch and provenance](../app/infrastructure/vendor/kamailio-ims/PROVENANCE.md)
and [upstream license](../app/infrastructure/vendor/kamailio-ims/COPYING)
accompany the image. A local build and deployment passed; the private receipt
is `local/private/scscf-expiry-deploy-20260921T223437Z/receipt.json`.
It records patched image ID
`sha256:8965c8545320b6a662478971c0726b6a6b5b71103acc1f8e060f4da368d70437`
and installed module SHA-256
`96ed5f1d4e1ea0cdd6f84f3bd56623f288ef42c28b777d5e1df7df2b821ef41c`.

The live passive-expiry gate passed with cleanup in
`local/private/aka-inactive-expire-20260921T223528557343Z/result.json`.
It rejected the inactive callee without routing to its expired Contact, and
observed physical registrar removal after 264.708 seconds. Subsequent
continuous AKA call regressions passed with cleanup in both directions:
`aka-call-20260921T224222548781Z` (UE1 caller) and
`aka-call-20260921T224428323334Z` (UE2 caller).
