#!/bin/bash
# SVGをPNG（2倍解像度）へ書き出す。使い方: bash assets/png.sh
cd "$(dirname "$0")"
CHROME="${CHROME:-C:/Program Files/Google/Chrome/Application/chrome.exe}"
for f in chart-*.svg; do
  [ -f "$f" ] || continue
  w=$(grep -o 'width="[0-9]*"' "$f" | head -1 | grep -o '[0-9]*'); h=$(grep -o 'height="[0-9]*"' "$f" | head -1 | grep -o '[0-9]*')
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 --window-size=$w,$h \
    --default-background-color=00000000 --screenshot="$(pwd -W 2>/dev/null || pwd)/${f%.svg}.png" "file:///$(pwd -W 2>/dev/null || pwd)/$f" >/dev/null 2>&1
  echo "png ${f%.svg}.png"
done
