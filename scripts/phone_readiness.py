"""Read-only server preflight; never certifies a physical phone from Docker tests."""

import json
import subprocess


def run(container, *arguments):
    try:
        result = subprocess.run(
            ["docker", "exec", container, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def inspect():
    codecs = run("lab-rtpengine", "rtpengine", "--codecs")
    supported = dict(line.strip().split(":", 1) for line in codecs.splitlines() if ":" in line)
    # Read only this feature directive, not the generated config with DB credentials.
    ipsec = run("lab-pcscf", "grep", "-x", "#!define WITH_IPSEC", "/etc/kamailio_pcscf/pcscf.cfg")
    checks = [
        {"check": "rtpengine_reachable", "status": "PASS" if codecs else "FAIL"},
        {
            "check": "pcscf_ipsec_configured",
            "status": "PASS" if ipsec else "FAIL",
            "scope": "Configuration only; no UE Security-Verify or XFRM SA proof",
        },
    ]
    for codec in ("PCMU", "AMR", "AMR-WB"):
        value = supported.get(codec, "unavailable").strip()
        checks.append(
            {
                "check": f"codec_{codec}_bidirectional",
                "status": "PASS" if value == "fully supported" else "FAIL",
                "detail": value,
            }
        )
    for name in (
        "native_phone_and_sim_profile",
        "radio_and_5gs_registration",
        "automatic_pcscf_discovery",
        "ims_aka_ipsec_registration",
        "amr_ai_sdp_and_bidirectional_audio",
        "prack_update_preconditions_qos",
        "incoming_outgoing_calls",
        "ai_translation_native_dialer",
        "reattach_recovery",
    ):
        checks.append({"check": name, "status": "UNVERIFIED"})
    return {
        "status": "NOT_READY",
        "checks": checks,
        "scope": "Server preflight; physical acceptance is separately required",
    }


def main():
    print(json.dumps(inspect(), indent=2))
    return 1  # Hardware acceptance cannot be inferred from server capabilities.


if __name__ == "__main__":
    raise SystemExit(main())
