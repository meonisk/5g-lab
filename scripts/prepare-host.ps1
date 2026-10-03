# Загружаем SCTP в ядро виртуальной машины Docker Desktop/WSL2.
# NGAP между gNB и AMF использует SCTP. Модуль CONFIG_IP_SCTP=m
# не загружается автоматически и требует повторной загрузки после перезапуска Docker.
wsl -d docker-desktop -e sh -c 'PATH=/sbin:/usr/sbin:$PATH; modprobe sctp'
$loaded = docker run --rm --privileged alpine:3.20 sh -c 'grep -c SCTP /proc/net/protocols'
if ($loaded -ge 1) { Write-Output "SCTP: loaded — модуль загружен" } else { Write-Output "SCTP: FAILED — модуль не загружен"; exit 1 }
