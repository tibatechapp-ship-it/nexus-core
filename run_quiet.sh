#!/bin/sh
cd "$(dirname "$0")"
exec python3 -W ignore novamind.py "$@"
