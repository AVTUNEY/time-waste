#!/bin/bash
# Build script for Hugo blog with JSON-LD fix

set -e

# Parse arguments
HUGO_ARGS=""
if [[ "$*" == *"--minify"* ]] || [[ "$*" == *"-m"* ]]; then
  HUGO_ARGS="--minify"
fi

echo "Building Hugo site..."
hugo $HUGO_ARGS

echo "Fixing JSON-LD structured data..."
python3 fix-jsonld.py

echo "✅ Build complete! Site is ready in ./public/"
