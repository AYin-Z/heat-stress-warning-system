#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APK="${1:-$SCRIPT_DIR/app/build/outputs/apk/release/app-release.apk}"

if [[ ! -f "$APK" ]]; then
    echo "APK not found: $APK" >&2
    exit 1
fi

adb get-state >/dev/null

EXISTING_UID="$(adb shell dumpsys package com.heatstress.watch 2>/dev/null \
    | sed -n 's/.*userId=\([0-9]*\).*/\1/p' | head -n 1 | tr -d '\r')"

if [[ -n "$EXISTING_UID" && "$EXISTING_UID" != "1000" ]]; then
    echo "An old non-system-UID build is installed (uid=$EXISTING_UID)." >&2
    echo "Back up its data, uninstall it once, then rerun this script." >&2
    exit 2
fi

adb install -r "$APK"
adb shell am start -n com.heatstress.watch/.MainActivity
sleep 3

RUNNING_PID="$(adb shell pidof com.heatstress.watch | tr -d '\r')"
if [[ -z "$RUNNING_PID" ]]; then
    echo "The app did not start after installation." >&2
    exit 3
fi

echo "Installed: $APK"
echo "Initialized A80 power policy (pid=$RUNNING_PID)."
echo "Verify with: adb logcat -s HeatStress MqttManager NtpSync"
