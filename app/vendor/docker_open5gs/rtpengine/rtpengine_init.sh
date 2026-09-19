#!/bin/bash

# BSD 2-Clause License

# Copyright (c) 2020-2025, Supreeth Herle
# All rights reserved.

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:

# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.

# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

set -Eeuo pipefail
set -x
RUNTIME=${1:-rtpengine}

if [[ "${TABLE:--1}" != "-1" ]]; then
	if lsmod | grep xt_RTPENGINE || modprobe xt_RTPENGINE; then
		echo "rtpengine kernel module already loaded."
	else
		modprobe xt_RTPENGINE
	fi
fi

# Populate options of the rtpengine cli command
[ -z "${INTERFACE:-}" ] && INTERFACE="$(awk 'END{print $1}' /etc/hosts)"
[ -z "${TABLE:-}" ] && TABLE="-1"
[ -z "${LISTEN_NG:-}" ] && LISTEN_NG="$(awk 'END{print $1}' /etc/hosts):2223"
[ -z "${PORT_MIN:-}" ] && PORT_MIN="30000"
[ -z "${PORT_MAX:-}" ] && PORT_MAX="40000"
[ -z "${TOS:-}" ] && TOS="184"
[ -z "${PIDFILE:-}" ] && PIDFILE="/run/ngcp-rtpengine-daemon.pid"

[ -z "${LISTEN_CLI:-}" ] && LISTEN_CLI="$(awk 'END{print $1}' /etc/hosts):9901"

OPTIONS=""
OPTIONS="$OPTIONS --interface=$INTERFACE --listen-ng=$LISTEN_NG --listen-cli=$LISTEN_CLI --pidfile=$PIDFILE --port-min=$PORT_MIN --port-max=$PORT_MAX "
OPTIONS="$OPTIONS --table=$TABLE  --tos=$TOS --foreground"

if test "${NO_FALLBACK:-no}" = "yes" ; then
	OPTIONS="$OPTIONS --no-fallback"
fi

# Sync docker time
#ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Add static route to route traffic back to UE as there is not NATing
ip route replace "${IMS_UE_CIDR}" via "${UPF_IP}"
# Route needed for VoWiFi client where internet APN is used
ip route replace "${INTERNET_UE_CIDR}" via "${UPF_IP}"

set -x

exec $RUNTIME $OPTIONS
