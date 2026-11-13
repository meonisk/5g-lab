# Vendored from herlesupreeth/docker_open5gs (master, fetched 2026-09-18).
# https://github.com/herlesupreeth/docker_open5gs - BSD 2-Clause, see LICENSE.
# Local adaptations (deployment overview: ../../../../docs/guide-3-sip.md):
# - I-CSCF SIP port 4060 -> 4069 (local IMS connectivity profile; see ../../../../docs/guide-3-sip.md)
# - PyHSS template: enable_insecure_auc: False (laboratory key-material policy; no sibling repository required)
# - Repository cleanup: omitted unused mysql/Dockerfile, mysql/mysql_init.sh,
#   and pyhss/Dockerfile. Compose uses MYSQL_IMAGE and PYHSS_IMAGE; neither
#   service builds these recipes. PyHSS runtime templates and init remain.
# - Retained CSCF route/SEMS/TLS files and XSDs: upstream init scripts copy them,
#   even when the corresponding optional functionality is disabled in this lab.
# - RTPengine image: install Debian libavcodec-extra59 for AMR/AMR-WB encoders;
#   fail the image build if either bidirectional codec is unavailable.
# - P-CSCF: add PCMU transcoding to configured AI service offers only; identifiers
#   are validated and rendered by pcscf_init.sh. Normal destinations are unchanged.
# - S-CSCF failure_route isc_orig_failure/isc_term_failure: NOTICE logs with the
#   reply code (L_DBG is hidden at debug=2) and resetdsturi() before continuing to
#   the callee, so DefaultHandling SESSION_CONTINUED never re-targets a dead AS.
#   route[orig] arms t_on_failure("isc_orig_failure") before t_newtran() (set after
#   the ISC relay it never reached the transaction) and marks $avp(isc_orig_as),
#   so failures of the callee itself are not re-run through the iFC chain.
#   isc_orig_failure tries the next AS once ($avp(isc_orig_retry)): ims_isc reads
#   the chain mark from the original request's lumps in every failure route, so a
#   second failure would pick the same AS again until tm runs out of branches.
#   After that the request continues to the callee; no failure route is re-armed.
#   Before that t_relay the route re-assigns $ru = $ru: the R-URI was consumed by
#   the AS branches, and t_relay failed with "no branches for forwarding".
#   The continued request still carries the failed AS Route and ISC mark (ims_isc
#   lumps of the original request), returns via I-CSCF and would re-enter the iFC
#   chain. isc_orig_failure adds X-Lab-ISC-Continued; route[orig] then drops it,
#   the Route headers and dst_uri, and goes straight to FINAL_ORIG.
