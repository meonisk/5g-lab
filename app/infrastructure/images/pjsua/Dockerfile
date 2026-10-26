# syntax=docker/dockerfile:1
# Minimal pjsua CLI (pjproject 2.14.1, audio only) for the test SIP clients
# lab-sipue1/2. They attach to the core bridge and register to the P-CSCF
# directly; ping and ip stay for manual network diagnostics.
FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171 AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl libasound2-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL https://github.com/pjsip/pjproject/archive/refs/tags/2.14.1.tar.gz \
    | tar xz
WORKDIR /src/pjproject-2.14.1
RUN ./configure --disable-video >/dev/null \
    && make dep >/dev/null && make -j"$(nproc)" >/dev/null \
    && make -C pjsip-apps/build pjsua >/dev/null \
    && strip pjsip-apps/bin/pjsua-*-linux-gnu* \
    && mv pjsip-apps/bin/pjsua-*-linux-gnu* pjsip-apps/bin/pjsua

FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash espeak-ng iproute2 iputils-ping libasound2 libssl3 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/pjproject-2.14.1/pjsip-apps/bin/pjsua /usr/local/bin/pjsua
ENTRYPOINT ["pjsua"]
