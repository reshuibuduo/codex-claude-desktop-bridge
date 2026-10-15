#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP="$ROOT/dist/Codex Claude Bridge.app"
SDK="${SDKROOT:-$(/usr/bin/xcrun --sdk macosx --show-sdk-path)}"
ARCH="$(/usr/bin/uname -m)"
PYTHON="${PYTHON_FOR_BUILD:-python3}"
VERSION=$(cat "$ROOT/VERSION")
case "$ARCH" in arm64|x86_64) ;; *) echo "Unsupported build architecture: $ARCH" >&2; exit 1;; esac
# Only replace generated output; user state lives outside the bundle.
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/runtime/bridge"
/usr/bin/xcrun swiftc "$ROOT/menu/MenuApp.swift" -o "$APP/Contents/MacOS/CodexClaudeBridge" -framework AppKit -sdk "$SDK" -target "$ARCH-apple-macosx13.0"
cp "$ROOT/bridge_core.py" "$APP/Contents/Resources/runtime/bridge_core.py"
cp "$ROOT/bridge/desktop_ipc.py" "$ROOT/bridge/desktop_mcp.py" "$ROOT/bridge/desktop_setup.py" "$ROOT/bridge/live_service.py" "$ROOT/bridge/bundle_smoke.py" "$APP/Contents/Resources/runtime/bridge/"
"$PYTHON" "$ROOT/scripts/prepare_runtime.py" --arch "$ARCH" --destination "$APP/Contents/Resources/python"
cp "$ROOT/LICENSE" "$APP/Contents/Resources/LICENSE"
cp -R "$ROOT/licenses" "$APP/Contents/Resources/licenses"
cp "$ROOT/menu/python-runtime.lock.json" "$APP/Contents/Resources/python-runtime.lock.json"
cp "$ROOT/docs/INSTALL.txt" "$APP/Contents/Resources/INSTALL.txt"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>CodexClaudeBridge</string>
<key>CFBundleIdentifier</key><string>io.github.reshuibuduo.codex-claude-bridge</string>
<key>CFBundleName</key><string>Codex Claude Bridge</string>
<key>CFBundleDisplayName</key><string>Codex Claude Bridge</string>
<key>CFBundleVersion</key><string>$VERSION</string>
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
"$PYTHON" "$ROOT/scripts/sign_bundle.py" "$APP"
"$APP/Contents/MacOS/CodexClaudeBridge" --self-test
"$APP/Contents/MacOS/CodexClaudeBridge" --bundle-self-test
/usr/bin/codesign --verify --deep --strict "$APP"
echo "MENU_BUILD_OK $ARCH version=$VERSION python=embedded signed=ad-hoc notarized=false"
