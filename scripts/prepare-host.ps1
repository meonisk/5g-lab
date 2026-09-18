# Load the SCTP kernel module inside the Docker Desktop WSL2 VM.
# NGAP between gNB and AMF runs over SCTP; the module is present in the WSL2
# kernel (CONFIG_IP_SCTP=m) but is NOT loaded by default and does NOT survive
# a Docker Desktop restart. Run this before "docker compose up".
wsl -d docker-desktop -e sh -c 'PATH=/sbin:/usr/sbin:$PATH; modprobe sctp'
$loaded = docker run --rm --privileged alpine:3.20 sh -c 'grep -c SCTP /proc/net/protocols'
if ($loaded -ge 1) { Write-Output "SCTP: loaded" } else { Write-Output "SCTP: FAILED"; exit 1 }
