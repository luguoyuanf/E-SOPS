#!/bin/sh
set -eu
# ESOP uses local conversion; originals and rendered outputs still use Platform OSS.
if [ -f /etc/apt/sources.list.d/debian.sources ]; then
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources
fi
apt-get -o Acquire::Retries=5 update
apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
    ffmpeg libreoffice-writer libreoffice-calc libreoffice-impress poppler-utils fonts-noto-cjk fonts-dejavu-core
rm -rf /var/lib/apt/lists/*
