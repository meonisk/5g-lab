# syntax=docker/dockerfile:1
ARG KAMAILIO_IMAGE=ghcr.io/herlesupreeth/docker_kamailio@sha256:efc9df818c239d28cd61a822d62ce0201b6ca3047f6fa653233bfa84498510de
FROM ${KAMAILIO_IMAGE} AS build

WORKDIR /usr/local/src/kamailio
COPY app/infrastructure/vendor/kamailio-ims/lookup-null-contact-v1.patch /tmp/lookup-null-contact-v1.patch

# Refuse to patch another upstream revision or an altered source file.
RUN test "$(git rev-parse HEAD)" = 9874599e41fa69cc3807676a7995a135a350a9ba && \
    test -z "$(git status --porcelain -- src/modules/ims_registrar_scscf/lookup.c)" && \
    printf '%s  %s\n' \
      da90fc367bb52ca9236c162d33f183dacd62bb2fadd92b9a6c513ae3611ab659 \
      src/modules/ims_registrar_scscf/lookup.c | sha256sum -c - && \
    printf '%s  %s\n' \
      eb5d16b82d9b675426e8f4fd30edbea06249e489af7a9ac41312af2a6b9fb39a \
      /tmp/lookup-null-contact-v1.patch | sha256sum -c - && \
    git apply /tmp/lookup-null-contact-v1.patch && \
    make -C src/modules/ims_registrar_scscf clean && \
    make -C src/modules/ims_registrar_scscf ims_registrar_scscf.so

FROM ${KAMAILIO_IMAGE}
COPY --from=build /usr/local/src/kamailio/src/modules/ims_registrar_scscf/ims_registrar_scscf.so \
  /usr/local/lib64/kamailio/modules/ims_registrar_scscf.so
COPY --from=build /usr/local/src/kamailio/src/modules/ims_registrar_scscf/lookup.c \
  /usr/local/src/kamailio/src/modules/ims_registrar_scscf/lookup.c
COPY app/infrastructure/vendor/kamailio-ims/COPYING /usr/share/doc/kamailio/COPYING
COPY app/infrastructure/vendor/kamailio-ims/lookup-null-contact-v1.patch \
  /usr/share/doc/kamailio/lookup-null-contact-v1.patch
