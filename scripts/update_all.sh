#!/bin/bash
# COMPATIBILITY SHIM: maintenance is owned by data-providers.
set -eu
cd "$(dirname "$0")/.."
exec .venv/bin/python -m data_providers.cli maintain --execute "$@"
