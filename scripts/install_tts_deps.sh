#!/usr/bin/env bash
# Install offline TTS and media deps (Debian/Ubuntu): espeak-ng, ffmpeg, fonts
# Usage: sudo ./scripts/install_tts_deps.sh
set -eu
echo "Installing espeak-ng, ffmpeg, and fonts..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  espeak-ng libespeak-ng1 ffmpeg fonts-dejavu-core
echo "Versions:"
espeak-ng --version | head -n 1 || true
ffmpeg -version | head -n 1 || true
echo "Done."
