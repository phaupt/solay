#!/usr/bin/env bash
# Network connectivity watchdog.
#
# The Pi's kernel, systemd, and dashboard process can all be perfectly
# healthy while the WiFi stack silently gives up reconnecting after a
# deauth (observed: NetworkManager landing in `no-secrets` state and
# never retrying). In that failure mode no existing watchdog fires —
# systemd is happy, the HW watchdog is being pinged, the service is
# looping — but the Pi is invisible on the LAN and renders only stale
# data.
#
# This script pings the default gateway every $NW_INTERVAL seconds and
# reboots the Pi after $NW_MAX_FAILURES consecutive failures.

set -u

INTERVAL="${NW_INTERVAL:-60}"
MAX_FAILURES="${NW_MAX_FAILURES:-5}"

log() { logger -t network-watchdog "$*"; }

log "started (interval=${INTERVAL}s max_failures=${MAX_FAILURES})"

failures=0
while true; do
    gw="$(ip route 2>/dev/null | awk '/^default/{print $3; exit}')"

    if [ -z "$gw" ]; then
        failures=$((failures + 1))
        log "no default route (fail ${failures}/${MAX_FAILURES})"
    elif ping -c 1 -W 3 "$gw" >/dev/null 2>&1; then
        if [ "$failures" -gt 0 ]; then
            log "gateway ${gw} reachable again after ${failures} failure(s)"
        fi
        failures=0
    else
        failures=$((failures + 1))
        log "gateway ${gw} unreachable (fail ${failures}/${MAX_FAILURES})"
    fi

    if [ "$failures" -ge "$MAX_FAILURES" ]; then
        log "${failures} consecutive failures, rebooting"
        sync
        /sbin/reboot
        exit 0
    fi

    sleep "$INTERVAL"
done
