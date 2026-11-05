#!/bin/bash
set -eu
exec bash "$(dirname "$0")/../../data_providers/scripts/watch.sh" "$@"
