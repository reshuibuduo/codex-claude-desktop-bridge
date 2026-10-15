#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP="$ROOT/dist/Codex Claude Bridge.app"
SDK="${SDKROOT:-$(/usr/bin/xcrun --sdk macosx --show-sdk-path)}"
ARCH="$(/usr/bin/uname -m)"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/runtime/bridge"
/usr/bin/xcrun swiftc "$ROOT/menu/MenuApp.swift" -o "$APP/Contents/MacOS/CodexClaudeBridge" -framework AppKit -sdk "$SDK" -target "$ARCH-apple-macosx13.0"
cp "$ROOT/bridge_core.py" "$APP/Contents/Resources/runtime/bridge_core.py"
cp "$ROOT/bridge/desktop_ipc.py" "$ROOT/bridge/desktop_mcp.py" "$ROOT/bridge/desktop_setup.py" "$ROOT/bridge/live_service.py" "$APP/Contents/Resources/runtime/bridge/"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>CodexClaudeBridge</string>
<key>CFBundleIdentifier</key><string>io.github.reshuibuduo.codex-claude-bridge</string>
<key>CFBundleName</key><string>Codex Claude Bridge</string>
<key>CFBundleDisplayName</key><string>Codex Claude Bridge</string>
<key>CFBundleVersion</key><string>2</string>
<key>CFBundleShortVersionString</key><string>0.2.0</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
/usr/bin/find "$APP/Contents/Resources/runtime" -type d -name __pycache__ -exec /bin/rm -rf {} +
/usr/bin/codesign --force --sign - "$APP"
"$APP/Contents/MacOS/CodexClaudeBridge" --self-test
/usr/bin/codesign --verify --deep --strict "$APP"
echo "MENU_BUILD_OK $ARCH signed=ad-hoc"
