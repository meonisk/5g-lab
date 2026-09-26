# SIPp AKA image provenance

This image is a source-built, stand-independent SIPp client for a later IMS AKA
spike. It does not implement or prove a continuous two-UE call or media path.

Build from the repository root:

```powershell
docker build -f app/infrastructure/images/sipp-aka/Dockerfile -t lab-sipp-aka:3.7.7-opc .
docker run --rm lab-sipp-aka:3.7.7-opc -v
```

SIPp prints its feature string for `-v` and exits with status 1; the expected
string for this build is `SIPp v3.7.7-TLS-SCTP-PCAP-SHA256`.

The build downloads the [SIPp v3.7.7 tag archive](https://github.com/SIPp/sipp/archive/refs/tags/v3.7.7.tar.gz),
checks its SHA-256 `2717f0fbe8554b2b2eb18dcf1f4ed8063bc8a94ef5349e2adc33d3d563e7d6c1`,
and applies the laboratory's binary-safe AKA patch copied from
`../ims/patches/sipp-3.7.7-aka-binary-safe-v3.patch` (SHA-256
`64ffeea54ba074d0a87d7af680552539a846e471d19d5007bcb6bfaacf546962`).
The patch preserves zero bytes in `aka_K`, `aka_OP`, and `aka_AMF` by passing
hexadecimal parameters through SIPp's length-aware escape representation.
The second laboratory patch, `sipp-3.7.7-opc-v1.patch` (SHA-256
`150add85e98484d3deec47c1cdd43d579e68c110122160960b1af1f5c6dfd34d`),
adds `aka_OPc=0x` followed by exactly 32 hexadecimal digits. It selects direct
OPc input for the Milenage functions involved in AKA and preserves `aka_OP` as
the original OP-deriving path. A scenario containing both parameters fails at
parse time. This prevents deriving a stored OPc twice.
The synthetic C++ regression test is copied from
`../ims/tests/sipp-aka-binary-safe-test.cpp` into
`app/infrastructure/vendor/sipp-aka/` (SHA-256
`f6ecba08b9de3ee85db1d44e8afe0804230a45af88af188dd4c1531e8eb29f50`)
and executes during the build. This verifies parameter encoding, not an IMS
registration or authenticated call.
The additional `sipp-opc-vector-test.cpp` (SHA-256
`28e7b09f979a017bbddcf28aa9378f97ba1c1dbe0555b17c93bc26a8a11a1b21`)
runs against [3GPP TS 35.208 Test Set 1](https://www.etsi.org/deliver/etsi_ts/135200_135299/135208/19.00.00_60/ts_135208v190000p.pdf)
for MAC-A, MAC-S, RES, CK, IK, AK, and AK-S with both OP and OPc inputs. It
also checks that passing OPc as OP does not yield the expected RES.

The exact upstream `LICENSE.txt` is vendored at
`app/infrastructure/vendor/sipp-aka/LICENSE.txt` (SHA-256
`f8f4d9a51309e3d7179efb4141f64f1bd680e938f75043b17f6d7031fbe67edd`)
and compared byte-for-byte with the downloaded archive. Upstream describes SIPp
as GPL-2.0-or-later with separately noted licenses for specific components;
see that file for the full terms. The runtime image carries the archive, patches,
and license under `/usr/share/source` and `/usr/share/doc/sipp` so its exact
source and modification remain available with the binary.

The old `../ims/deploy/build-sipp-aka-safe.sh` currently expects patch SHA-256
`fcece93757982f2d807b8ab1c44bfa704e6f024b144b78fb497c4a2359b6e262`,
which does not match the clean `../ims` patch file copied here. The image pins
and checks the copied file's actual hash, avoiding any silent substitution.

Build flags explicitly enable SSL/TLS, PCAP, and SCTP. The Debian bookworm-slim
base is pinned by digest in the Dockerfile. Debian package indexes remain a
time-varying input; the image is source- and patch-pinned, not bit-reproducible
across all build dates.
