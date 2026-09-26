# Kamailio IMS registrar source patch

Source: `src/modules/ims_registrar_scscf/lookup.c` from Kamailio commit
`9874599e41fa69cc3807676a7995a135a350a9ba`, carried in
`ghcr.io/herlesupreeth/docker_kamailio@sha256:efc9df818c239d28cd61a822d62ce0201b6ca3047f6fa653233bfa84498510de`.
The source file was clean against that commit and had SHA-256
`da90fc367bb52ca9236c162d33f183dacd62bb2fadd92b9a6c513ae3611ab659`.

`lookup-null-contact-v1.patch` changes one condition in `lookup()`: once the
linked-contact scan exhausts its list, `impucontact` is null even if `ptr`
still points to the last, invalid contact. The original `if(ptr == 0)` then
falls through and attempts to route to it. The patch checks both conditions.
Patch SHA-256:
`eb5d16b82d9b675426e8f4fd30edbea06249e489af7a9ac41312af2a6b9fb39a`.

`COPYING` is copied byte-for-byte from `/usr/local/src/kamailio/COPYING` in
the pinned image; SHA-256
`baabeacd717907c24379807d4813f1e71a976d1cd5e46c8a71ea8a509fc38a4f`.
Kamailio describes GPL terms and module obligations in that file. This
directory contains the upstream license and our separate source patch; the
full source tree remains in the pinned image.

Local deployment evidence is kept outside version control at
`local/private/scscf-expiry-deploy-20260921T223437Z/receipt.json`.
The successful build/deploy receipt identifies patched image
`sha256:8965c8545320b6a662478971c0726b6a6b5b71103acc1f8e060f4da368d70437`
and installed `ims_registrar_scscf.so` SHA-256
`96ed5f1d4e1ea0cdd6f84f3bd56623f288ef42c28b777d5e1df7df2b821ef41c`.
The live passive-expiry gate at
`local/private/aka-inactive-expire-20260921T223528557343Z/result.json`
reports `PASS`, cleanup `PASS`, and physical Contact removal after 264.708
seconds. This verifies the expired-Contact route guard in that deployed image;
separate continuous AKA call regressions then passed with cleanup in both
directions: `aka-call-20260921T224222548781Z` (UE1 caller) and
`aka-call-20260921T224428323334Z` (UE2 caller).
