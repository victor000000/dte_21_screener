#!/bin/bash
# COMPATIBILITY SHIM: provider-owned operations and runtime.
set -eu
exec bash "$(dirname "$0")/../../data_providers/scripts/monitor_downloads.sh" "$@"
