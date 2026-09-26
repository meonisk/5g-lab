# syntax=docker/dockerfile:1
ARG DEBIAN_IMAGE=debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171
FROM ${DEBIAN_IMAGE} AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates cmake curl libncurses-dev libpcap-dev \
    libsctp-dev libssl-dev patch pkg-config && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY app/infrastructure/vendor/sipp-aka/sipp-3.7.7-aka-binary-safe-v3.patch patch.diff
COPY app/infrastructure/vendor/sipp-aka/sipp-3.7.7-opc-v1.patch opc.patch
COPY app/infrastructure/vendor/sipp-aka/LICENSE.txt LICENSE.txt
COPY app/infrastructure/vendor/sipp-aka/sipp-aka-binary-safe-test.cpp test.cpp
COPY app/infrastructure/vendor/sipp-aka/sipp-opc-vector-test.cpp opc-test.cpp

RUN printf '%s  %s\n' \
      64ffeea54ba074d0a87d7af680552539a846e471d19d5007bcb6bfaacf546962 patch.diff \
      150add85e98484d3deec47c1cdd43d579e68c110122160960b1af1f5c6dfd34d opc.patch \
      f8f4d9a51309e3d7179efb4141f64f1bd680e938f75043b17f6d7031fbe67edd LICENSE.txt \
      f6ecba08b9de3ee85db1d44e8afe0804230a45af88af188dd4c1531e8eb29f50 test.cpp \
      28e7b09f979a017bbddcf28aa9378f97ba1c1dbe0555b17c93bc26a8a11a1b21 opc-test.cpp \
    | sha256sum -c -

RUN curl -fL --retry 3 https://github.com/SIPp/sipp/archive/refs/tags/v3.7.7.tar.gz \
      -o source.tar.gz && \
    echo '2717f0fbe8554b2b2eb18dcf1f4ed8063bc8a94ef5349e2adc33d3d563e7d6c1  source.tar.gz' \
      | sha256sum -c - && \
    mkdir source && tar -xzf source.tar.gz -C source --strip-components=1 && \
    cmp LICENSE.txt source/LICENSE.txt && \
    cd source && patch --batch -p1 < ../patch.diff && \
    patch --batch -p1 < ../opc.patch

# Catch the AKA binary/NUL handling regression independently of network scenarios.
RUN c++ -std=c++11 -Wall -Wextra -Werror -Isource/include test.cpp -o aka-selftest && \
    ./aka-selftest

RUN cc -Isource/include -c source/src/milenage.c -o milenage.o && \
    cc -Isource/include -c source/src/rijndael.c -o rijndael.o && \
    c++ -std=c++11 -Wall -Wextra -Werror -Isource/include \
      opc-test.cpp milenage.o rijndael.o -o opc-selftest && ./opc-selftest

RUN cmake -S source -B out -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_CXX_FLAGS=-Wno-error=format-truncation \
      -DUSE_SSL=ON -DUSE_PCAP=ON -DUSE_SCTP=ON && \
    printf '#define SIPP_VERSION VERSION\n#define VERSION "v3.7.7"\n' > out/version.h && \
    cmake --build out --target sipp --parallel 2

FROM ${DEBIAN_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends \
    libncurses6 libncursesw6 libpcap0.8 libsctp1 libssl3 && rm -rf /var/lib/apt/lists/*
COPY --from=build /build/out/sipp /usr/local/bin/sipp
COPY --from=build /build/source.tar.gz /usr/share/source/sipp-3.7.7.tar.gz
COPY --from=build /build/patch.diff /usr/share/source/sipp-3.7.7-aka-binary-safe-v3.patch
COPY --from=build /build/opc.patch /usr/share/source/sipp-3.7.7-opc-v1.patch
COPY --from=build /build/LICENSE.txt /usr/share/doc/sipp/LICENSE.txt
ENTRYPOINT ["sipp"]
