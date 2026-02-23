#!/bin/bash
set -e
echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Building webapp ==="
cd webapp && npm install && npm run build && ls -la dist/ && cd ..

echo "=== Building PWA ==="
cd pwa && npm install && npm run build:ci && ls -la dist/ && cd ..

echo "=== Build complete ==="
