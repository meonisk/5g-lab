#!/usr/bin/env bash
# Настройка ядра OAI партнёра под наш IMS — описано в docs/1-install.md, шаг 1.
#   scripts/core-setup.sh check    # только показать текущее состояние, ничего не менять
#   scripts/core-setup.sh apply    # привести ядро к нужному виду (повтор безопасен)
#   scripts/core-setup.sh revert   # вернуть файлы ядра из резервных копий *.bak-ims
# Меняются только файлы в OAI_CORE_DIR (по умолчанию ~/oai-cn5g): conf/config.yaml и
# docker-compose.yaml. Перед первой правкой создаются копии *.bak-ims. Применение
# пересоздаёт oai-smf и oai-upf: PDU-сессии всех UE обрываются на несколько секунд.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
set -a
# shellcheck source=../app/config/lab.env
source "$root/app/config/lab.env"
set +a

core=${OAI_CORE_DIR:-$HOME/oai-cn5g}
config=$core/conf/config.yaml
compose_file=$core/docker-compose.yaml
compose=(docker compose --project-directory "$core" -f "$compose_file")
demo=${OAI_DEMO_IMS_SERVICE:-ims}
nat_rule=(-s "$INTERNET_UE_CIDR" ! -d "$LAB_NETWORK_CIDR" -o eth0 -j MASQUERADE)

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ -f $config && -f $compose_file ]] || die "нет $config или $compose_file (OAI_CORE_DIR)"

# Отступ сервисов в compose ядра: ключи сервиса — на 4 пробела глубже.
service_indent=$(sed -n 's/^\( *\)oai-upf:.*/\1/p' "$compose_file" | head -1)
key_indent="$service_indent    "

value() { sed -n "s/^ *$1: *\"\{0,1\}\([^\" #]*\).*/\1/p" "$config" | head -1; }

status() {
    echo "--- $config"
    printf '  enable_snat:    %s (нужно: no)\n' "$(value enable_snat)"
    printf '  pcscf_ipv4:     %s (нужно: %s)\n' "$(value pcscf_ipv4)" "$PCSCF_IP"
    printf '  ue_dns primary: %s (нужно: %s)\n' "$(value primary_ipv4)" "$DNS_IP"
    echo "--- $compose_file"
    if grep -q 'MASQUERADE' "$compose_file"; then
        echo "  oai-upf post_start: NAT только в интернет — есть"
    else
        echo "  oai-upf post_start: НЕТ"
    fi
    if grep -q 'oai-demo-ims' "$compose_file"; then
        echo "  демо-IMS '$demo': выключен (profile oai-demo-ims)"
    else
        echo "  демо-IMS '$demo': включён"
    fi
    echo "--- работающие контейнеры"
    docker exec oai-upf iptables -t nat -S POSTROUTING 2>/dev/null | grep -E 'SNAT|MASQUERADE' | sed 's/^/  /' || true
    docker ps --format '  {{.Names}} {{.Status}}' --filter "name=^${demo}$"
}

apply() {
    # Копии делаются один раз: они хранят исходное состояние ядра партнёра.
    [[ -e $config.bak-ims ]] || cp -p "$config" "$config.bak-ims"
    [[ -e $compose_file.bak-ims ]] || cp -p "$compose_file" "$compose_file.bak-ims"

    # UPF не натит трафик UE в сеть ядра: адрес телефона записан внутри SIP/SDP.
    sed -i -E 's/^( *enable_snat: *)yes/\1no/' "$config"
    # SMF выдаёт телефону наш P-CSCF и наш DNS (чужие имена он пересылает дальше).
    sed -i -E "s/^( *pcscf_ipv4: *)\"[^\"]*\"/\\1\"$PCSCF_IP\"/" "$config"
    sed -i -E "/^ *ue_dns:/,/^ *[a-z_]+:$/ s/^( *primary_ipv4: *)\"[^\"]*\"/\\1\"$DNS_IP\"/" "$config"

    # NAT в интернет ставит сам контейнер UPF при каждом старте (Compose post_start).
    if ! grep -q 'MASQUERADE' "$compose_file"; then
        local command
        command=$(printf '"%s", ' iptables -t nat -A POSTROUTING "${nat_rule[@]}")
        awk -v svc="^${service_indent}oai-upf:" -v key="$key_indent" -v cmd="[${command%, }]" '
            $0 ~ svc {inside=1; print; print key "post_start:"; print key "    - command: " cmd; next}
            {print}' "$compose_file" >"$compose_file.new"
        mv "$compose_file.new" "$compose_file"
    fi

    # Демо-IMS OAI уходит в отдельный профиль: обычный up его больше не поднимает.
    if ! grep -q 'oai-demo-ims' "$compose_file" && grep -q "^${service_indent}${demo}:" "$compose_file"; then
        awk -v svc="^${service_indent}${demo}:" -v key="$key_indent" '
            $0 ~ svc {print; print key "profiles: [\"oai-demo-ims\"]"; next} {print}' \
            "$compose_file" >"$compose_file.new"
        mv "$compose_file.new" "$compose_file"
    fi

    "${compose[@]}" config --quiet || die "compose ядра не проходит проверку; откат: $0 revert"
    "${compose[@]}" up -d --force-recreate oai-smf oai-upf
    docker rm -f "$demo" >/dev/null 2>&1 || true
    sleep 5
    status
}

revert() {
    [[ -e $config.bak-ims && -e $compose_file.bak-ims ]] || die "нет копий *.bak-ims"
    cp -p "$config.bak-ims" "$config"
    cp -p "$compose_file.bak-ims" "$compose_file"
    "${compose[@]}" up -d --force-recreate oai-smf oai-upf
    "${compose[@]}" up -d "$demo" 2>/dev/null || true
    status
}

case ${1:-check} in
check) status ;;
apply) apply ;;
revert) revert ;;
*) die "использование: scripts/core-setup.sh check | apply | revert" ;;
esac
