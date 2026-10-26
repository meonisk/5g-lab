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
