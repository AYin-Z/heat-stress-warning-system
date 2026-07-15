#!/bin/bash
# 部署手表 APK 脚本
# 用法: bash push_to_watch.sh

set -e

WATCH_DIR="/home/ayin/Current_Works/热应激预警系统/watch-app"
APK="$WATCH_DIR/app/build/outputs/apk/debug/app-debug.apk"
TARGET="/system/priv-app/heatstress/heatstress.apk"

echo "=== 1. 检查 APK ==="
if [ ! -f "$APK" ]; then
    echo "❌ APK 未找到: $APK"
    echo "请先运行: cd $WATCH_DIR && ./gradlew assembleDebug"
    exit 1
fi
echo "✅ APK: $(ls -lh $APK | awk '{print $5}')"

echo ""
echo "=== 2. ADB Root ==="
adb root
sleep 2

echo ""
echo "=== 3. Remount system ==="
adb remount

echo ""
echo "=== 4. Push APK ==="
adb shell "mkdir -p /system/priv-app/heatstress"
adb push "$APK" "$TARGET"

echo ""
echo "=== 5. Reboot ==="
adb reboot

echo ""
echo "✅ 部署完成！手表重启后自动启动"
echo ""
echo "验证: adb logcat | grep -i heatstress"
