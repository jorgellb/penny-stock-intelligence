#!/usr/bin/env bash
set -e
curl -sf http://localhost:8000/health | head -c 500
echo
