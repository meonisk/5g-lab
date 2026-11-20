# shellcheck shell=bash
# Подстановка PLMN и SIM в копии конфигураций OAI (libconfig). Используется
# scripts/rfsim.sh и scripts/gnb.sh; исходные файлы конфигураций не меняются.
# Нужны MCC/MNC из lab.env. Фильтры: stdin -> stdout.

# gNB: plmn_list = ({ mcc = 001; mnc = 01; mnc_length = 2; ... }). Длина MNC —
# по числу цифр в lab.env: SIM с MNC из двух цифр не видит сеть с трёхзначным.
gnb_plmn() {
    sed -E "s/(^|[{ ;])mcc *= *[0-9]+;/\1mcc = $MCC;/; s/(^|[{ ;])mnc *= *[0-9]+;/\1mnc = $MNC;/; s/mnc_length *= *[0-9]+;/mnc_length = ${#MNC};/"
}

# Адрес хоста на мосту ядра — шлюз сети, к которой подключён P-CSCF («адрес/маска»).
host_address() {
    local address
    address=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.Gateway}}/{{.IPPrefixLen}}{{end}}' lab-pcscf)
    [[ $address == */* && $address != /* ]] || return 1
    echo "$address"
}

# gNB на хосте: адрес NG и N3 — ADDRESS (в исходных конфигурациях часто стоит адрес
# контейнера gNB, которого на хосте нет).
gnb_address() {
    sed -E "s#(GNB_IPV4_ADDRESS_FOR_(NG_AMF|NGU)) *= *\"[^\"]*\"#\\1 = \"$1\"#"
}

# UE rfsim: uicc0 = { imsi = "..."; key = "..."; opc = "..."; dnn = "..."; }.
# PREFIX — UE1 или UE2: IMSI и ключи те же, что заводятся в UDR ядра.
ue_sim() {
    local prefix=$1 imsi key opc
    imsi=${prefix}_IMSI key=${prefix}_IMS_K opc=${prefix}_IMS_OPC
    sed -E "s/imsi *= *\"[^\"]*\"/imsi = \"${!imsi}\"/; s/key *= *\"[^\"]*\"/key = \"${!key}\"/; s/opc *= *\"[^\"]*\"/opc = \"${!opc}\"/; s/dnn *= *\"[^\"]*\"/dnn = \"$IMS_DNN\"/"
}
