"""Provision OAI subscriptions without resetting existing AKA keys or SQN."""

import json
import re
import subprocess
from pathlib import Path

from initialize_local import read_values

ROOT = Path(__file__).resolve().parents[1]


def sql_value(value):
    if not isinstance(value, str):
        value = json.dumps(value, separators=(",", ":"))
    return "CONVERT(0x" + value.encode().hex() + " USING utf8mb4)"


def query(statement):
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "lab-oai-db",
            "sh",
            "-c",
            'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u oai -N -B oai_db',
        ],
        input=statement,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        # SQL diagnostics can echo credentials. Never print them.
        raise RuntimeError(
            "OAI subscriber SQL failed (diagnostics withheld to protect credentials)"
        )
    return result.stdout.strip()


def profiles(env):
    result = []
    for ue in (1, 2):
        imsi = env[f"UE{ue}_IMSI"]
        if not re.fullmatch(r"\d{15}", imsi):
            raise ValueError(f"UE{ue}_IMSI must contain 15 digits")
        names = [f"UE{ue}_5GS_{field}" for field in ("K", "OPC", "AMF")]
        if not any(env.get(name) for name in names):
            names = [f"SUBSCRIBER_{field}" for field in ("K", "OPC", "AMF")]
        keys = [env[name] for name in names]
        for key, length in zip(keys, (32, 32, 4), strict=True):
            if not re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", key):
                raise ValueError("Invalid 5GS credential format")
        result.append((imsi, keys))
    return result


def statements(env, imsi, keys):
    k, opc, amf = keys
    identity = sql_value(imsi)
    plmn = sql_value(env["MCC"] + env["MNC"])
    snssai = {"sst": int(env["UE_PDU_SST"])}
    sequence = {"sqn": "000000000020", "sqnScheme": "NON_TIME_BASED", "lastIndexes": {"ausf": 0}}
    values = [imsi, "5G_AKA", k, k, sequence, amf, "milenage", opc, imsi]
    auth = (
        "INSERT INTO AuthenticationSubscription "
        "(ueid,authenticationMethod,encPermanentKey,protectionParameterId,sequenceNumber,"
        "authenticationManagementField,algorithmId,encOpcKey,supi) VALUES ("
        + ",".join(sql_value(value) for value in values)
        + ") ON DUPLICATE KEY UPDATE ueid=ueid;"
    )
    dnn_config = {}
    for dnn, qi in ((env["INTERNET_DNN"], 9), (env["IMS_DNN"], 5)):
        dnn_config[dnn] = {
            "pduSessionTypes": {"defaultSessionType": "IPV4", "allowedSessionTypes": ["IPV4"]},
            "sscModes": {"defaultSscMode": "SSC_MODE_1", "allowedSscModes": ["SSC_MODE_1"]},
            "5gQosProfile": {
                "5qi": qi,
                "priorityLevel": 8,
                "arp": {
                    "priorityLevel": 8,
                    "preemptCap": "NOT_PREEMPT",
                    "preemptVuln": "NOT_PREEMPTABLE",
                },
            },
            "sessionAmbr": {"uplink": "100Mbps", "downlink": "100Mbps"},
        }
    nssai = sql_value({"defaultSingleNssais": [snssai], "singleNssais": [snssai]})
    session = sql_value(dnn_config)
    # OAI SMF encodes absent SD as FFFFFF when querying UDM/UDR.
    slice_json = sql_value({**snssai, "sd": "FFFFFF"})
    return [
        auth,
        "INSERT INTO AccessAndMobilitySubscriptionData (ueid,servingPlmnid,nssai) "
        f"VALUES ({identity},{plmn},{nssai}) ON DUPLICATE KEY UPDATE nssai={nssai};",
        "INSERT INTO SessionManagementSubscriptionData "
        f"(ueid,servingPlmnid,singleNssai,dnnConfigurations) VALUES ({identity},{plmn},{slice_json},{session}) "
        f"ON DUPLICATE KEY UPDATE singleNssai={slice_json},dnnConfigurations={session};",
    ]


def main():
    env = {
        **read_values(ROOT / "app/config/lab.env"),
        **read_values(ROOT / "local/secrets/ims.env"),
    }
    commands = ["START TRANSACTION;"]
    for imsi, keys in profiles(env):
        existing = query(
            "SELECT encPermanentKey,encOpcKey,authenticationManagementField "
            f"FROM AuthenticationSubscription WHERE ueid={sql_value(imsi)};"
        )
        if existing and existing.lower().split("\t") != [key.lower() for key in keys]:
            raise RuntimeError("OAI AKA credential mismatch; explicit migration required")
        commands.extend(statements(env, imsi, keys))
    query("\n".join([*commands, "COMMIT;"]))
    print("OAI: two subscriber profiles provisioned; existing keys and SQN preserved")


if __name__ == "__main__":
    main()
