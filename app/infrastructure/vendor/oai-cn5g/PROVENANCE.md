# OAI CN5G schema

Source: https://github.com/openairinterface/oai-cn5g-fed/tree/3beb7e3582ada946f230bf4271673733eb1c4818

Release: v2.2.1. `schema.sql` comes from `docker-compose/database/oai_db2.sql`.
All INSERT statements (upstream demo subscribers and keys) were removed.
DDL is otherwise unchanged. Repository license is retained in `LICENSE`.

Runtime configuration follows `docker-compose/conf/basic_nrf_config.yaml` at this revision.
UPF simple-switch behavior checked against oai-cn5g-upf v2.2.1,
commit 451c27daa4b38bd03a5cb5b92412743364ff8ae0:
`src/upf_app/simpleswitch/pfcp_switch.cpp`, `setup_pdn_interfaces`.
It creates one tun0 for all IPv4 DNNs; built-in SNAT applies to all pools,
so this lab disables it and adds internet-only MASQUERADE.
