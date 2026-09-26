"""Bind private SIP challenges to same-user MAA vectors using keyed fingerprints."""

import base64
import secrets

from aka_trace import _digest_parameter, messages
from cx_metadata import challenge_fingerprint, identity_pseudonym, summarize_pcap


def assess(directory, settings, bad_response=False, expected_challenges=1):
    counts = (
        {ue: expected_challenges for ue in (1, 2)}
        if isinstance(expected_challenges, int)
        else expected_challenges
    )
    if (
        not isinstance(counts, dict)
        or set(counts) != {1, 2}
        or any(type(counts[ue]) is not int or counts[ue] < 1 for ue in (1, 2))
    ):
        raise ValueError("Expected challenge count must be positive")
    key = secrets.token_bytes(32)
    # Raw identities, vectors and this key stay inside the ignored evidence directory.
    with (directory / "pseudonym.key").open("xb") as stream:
        stream.write(key)
    identities = {ue: settings[f"UE{ue}_IMSI"] + "@" + settings["IMS_DOMAIN"] for ue in (1, 2)}
    expected = {
        identity: {"UAR", "MAR"} if bad_response and ue == 1 else {"UAR", "MAR", "SAR"}
        for ue, identity in identities.items()
    }
    result = summarize_pcap(
        directory / "cx.pcap",
        key,
        port=int(settings["PYHSS_BIND_PORT"]),
        expected_commands=expected,
    )
    bindings = []
    for ue, identity in identities.items():
        count = counts[ue]
        binding = {"ue": ue, "status": "FAIL"}
        try:
            trace = (directory / f"ue{ue}-messages.log").read_text(encoding="utf-8")
            challenges = [item for item in messages(trace) if item.status == 401]
            if len(challenges) != count:
                raise ValueError("SIP AKA challenge count mismatch")
            fingerprints = []
            for challenge in challenges:
                encoded = _digest_parameter(challenge.header("www-authenticate"), "nonce")
                fingerprints.append(
                    challenge_fingerprint(base64.b64decode(encoded, validate=True), key)
                )
            if len(set(fingerprints)) != count:
                raise ValueError("SIP AKA challenge was reused")
            user = identity_pseudonym(identity, key)
            same_user = [
                item
                for item in result["transactions"]
                if item.get("user") == user and item.get("command") == "MAR"
            ]
            if len(same_user) != count:
                raise ValueError("Same-user MAA count mismatch")
            matches = [
                [
                    item
                    for item in same_user
                    if fingerprint in item.get("challenge_fingerprints", [])
                ]
                for fingerprint in fingerprints
            ]
            if any(len(items) != 1 for items in matches):
                raise ValueError("SIP challenge lacks unique same-user MAA")
            sessions = [items[0].get("session") for items in matches]
            if any(not session for session in sessions) or len(set(sessions)) != count:
                raise ValueError("MAA sessions were reused")
            if count == 1:
                binding.update(status="PASS", challenge=fingerprints[0], session=sessions[0])
            else:
                binding.update(status="PASS", challenges=fingerprints, sessions=sessions)
        except (ValueError, TypeError, KeyError, OSError):
            pass
        bindings.append(binding)
    result["sip_maa_bindings"] = bindings
    if any(item["status"] != "PASS" for item in bindings):
        result["status"] = "FAIL"
        result["binding_error"] = "SIP challenge lacks exactly one same-user MAA vector"
    return result
