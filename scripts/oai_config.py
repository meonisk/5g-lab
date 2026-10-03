"""Создание приватного OAI YAML в синтаксисе JSON из общих настроек стенда."""

import json
from pathlib import Path

NFS = ("nrf", "udr", "udm", "ausf", "amf", "smf", "upf")


def configuration(env):
    slice_info = {"sst": int(env["UE_PDU_SST"])}
    dnns = [env["INTERNET_DNN"], env["IMS_DNN"]]
    nfs = {
        nf: {
            "host": nf,
            "sbi": {
                "port": int(env["OAI_HTTP_PORT"]),
                "api_version": "v1",
                "interface_name": "eth0",
            },
        }
        for nf in NFS
    }
    nfs["amf"]["n2"] = {"interface_name": "eth0", "port": 38412}
    nfs["smf"]["n4"] = {"interface_name": "eth0", "port": 8805}
    for interface, port in (("n3", 2152), ("n4", 8805), ("n9", 2152)):
        nfs["upf"][interface] = {"interface_name": "eth0", "port": port}
    nfs["upf"]["n6"] = {"interface_name": "eth0"}
    plmn = {"mcc": env["MCC"], "mnc": env["MNC"]}
    return {
        # Журналы OAI уровня info содержат векторы аутентификации и ключи абонентов.
        "log_level": {"general": "warning"},
        "register_nf": {"general": True},
        "http_version": 1,
        "http_request_timeout": int(env["OAI_HTTP_TIMEOUT_MS"]),
        "nfs": nfs,
        "database": {
            "host": "oai-db",
            "user": "oai",
            "type": "mysql",
            "password": env["OAI_DB_PASSWORD"],
            "database_name": "oai_db",
            "generate_random": False,
            "connection_timeout": 30,
        },
        "amf": {
            "amf_name": "lab-oai-amf",
            "support_features_options": {
                "enable_simple_scenario": False,
                "enable_nssf": False,
                "enable_smf_selection": True,
            },
            "relative_capacity": 30,
            "statistics_timer_interval": 20,
            "emergency_support": False,
            "served_guami_list": [
                {**plmn, "amf_region_id": "01", "amf_set_id": "001", "amf_pointer": "01"}
            ],
            "plmn_support_list": [{**plmn, "tac": int(env["OAI_TAC"]), "nssai": [slice_info]}],
            "supported_integrity_algorithms": ["NIA2", "NIA1"],
            "supported_encryption_algorithms": ["NEA2", "NEA1", "NEA0"],
        },
        "smf": {
            "ue_mtu": 1500,
            "support_features": {
                "use_local_subscription_info": False,
                "use_local_pcc_rules": True,
            },
            "upfs": [{"host": "upf", "config": {"enable_usage_reporting": False}}],
            "ue_dns": {"primary_ipv4": env["DNS_IP"], "secondary_ipv4": env["DNS_IP"]},
            "ims": {"pcscf_ipv4": env["PCSCF_IP"]},
            "smf_info": {
                "sNssaiSmfInfoList": [
                    {"sNssai": slice_info, "dnnSmfInfoList": [{"dnn": d} for d in dnns]}
                ]
            },
        },
        "upf": {
            "support_features": {"enable_bpf_datapath": False, "enable_snat": False},
            "remote_n6_gw": "localhost",
            "smfs": [{"host": "smf"}],
            "upf_info": {
                "sNssaiUpfInfoList": [
                    {"sNssai": slice_info, "dnnUpfInfoList": [{"dnn": d} for d in dnns]}
                ]
            },
        },
        "dnns": [
            {"dnn": dnns[0], "pdu_session_type": "IPV4", "ipv4_subnet": env["INTERNET_UE_CIDR"]},
            {"dnn": dnns[1], "pdu_session_type": "IPV4", "ipv4_subnet": env["IMS_UE_CIDR"]},
        ],
    }


def render(root: Path, env):
    target = root / "local/oai"
    target.mkdir(parents=True, exist_ok=True)
    config = configuration(env)
    for nf in NFS:
        # Ключи SQL нужны только UDR. Остальные функции находят сервисы через SBI.
        value = dict(config)
        if nf != "udr":
            value.pop("database")
        (target / f"{nf}.yaml").write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
