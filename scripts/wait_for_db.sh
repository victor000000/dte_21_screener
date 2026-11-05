#!/bin/bash
# COMPATIBILITY SHIM: provider-owned operations and runtime.
set -eu
exec bash "$(dirname "$0")/../../data_providers/scripts/wait_for_db.sh" "$@"
