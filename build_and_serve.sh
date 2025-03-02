#!/bin/bash
# This script builds Slidev presentations and serves the static files with token authentication

set -e  # Exit on any error

# Create a log file for debugging
exec > >(tee build_serve.log) 2>&1

echo "🚀 Building Slidev presentation at $(date)"

# Make sure we're in the correct directory
cd "$(dirname "$0")"

echo "📂 Current directory: $(pwd)"
echo "📄 Files in current directory:"
ls -la

# Kill any process using port 3030
if lsof -ti:3030 >/dev/null ; then
    echo "🚫 Killing process on port 3030"
    lsof -ti:3030 | xargs kill -9
fi
# Build the Slidev presentation in production mode
echo "🔨 Running Slidev build..."
npx slidev build 

# Verify build succeeded
if [ ! -d "./dist" ]; then
    echo "❌ Build failed - dist directory not created!"
    exit 1
fi

echo "✅ Build complete! Static files are in ./dist"
echo "📂 Starting token-authenticated HTTP server on port 3030..."

# Change to the dist directory
cd ./dist

# Serve with the token-authenticated server instead of basic HTTP server
python ../slidev_auth.py 3030