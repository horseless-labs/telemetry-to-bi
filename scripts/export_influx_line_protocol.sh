#!/usr/bin/env bash

set -euo pipefail

# Export line protocol from a local InfluxDB 2.x engine copy.
#
# Expected source layout:
#
#   wimbac-influx-copy/
#   └── influxdb/
#       └── engine/
#           ├── data/
#           └── wal/
#
# This script uses:
#
#   influxd inspect export-lp
#
# to export TSM data from bucket IDs into line protocol files.
#
# Usage:
#
#   ./scripts/export_influx_line_protocol.sh
#
# Optional:
#
#   ENGINE_PATH=./wimbac-influx-copy/influxdb/engine \
#   OUTPUT_DIR=./schema_exports \
#   SAMPLE_LINES=50000 \
#   ./scripts/export_influx_line_protocol.sh

ENGINE_PATH="${ENGINE_PATH:-./wimbac-influx-copy/influxdb/engine}"
OUTPUT_DIR="${OUTPUT_DIR:-./schema_exports}"
SAMPLE_LINES="${SAMPLE_LINES:-50000}"

# Bucket IDs found under:
#
#   ./influxdb/engine/data/<bucket_id>/autogen
#
# In this backup:
#
#   3c56875bf638a356
#   9869293bf881d9b3
#
BUCKET_IDS=(
  "3c56875bf638a356"
  "9869293bf881d9b3"
)

mkdir -p "$OUTPUT_DIR"

echo "Using engine path: $ENGINE_PATH"
echo "Writing exports to: $OUTPUT_DIR"
echo

if [[ ! -d "$ENGINE_PATH/data" ]]; then
  echo "ERROR: Could not find data directory at: $ENGINE_PATH/data" >&2
  echo "Check ENGINE_PATH." >&2
  exit 1
fi

if [[ ! -d "$ENGINE_PATH/wal" ]]; then
  echo "WARNING: Could not find WAL directory at: $ENGINE_PATH/wal" >&2
  echo "Continuing anyway, but export may be incomplete."
  echo
fi

command -v influxd >/dev/null 2>&1 || {
  echo "ERROR: influxd command not found." >&2
  echo "Install InfluxDB or make sure influxd is on your PATH." >&2
  exit 1
}

for bucket_id in "${BUCKET_IDS[@]}"; do
  sample_file="$OUTPUT_DIR/bucket_${bucket_id}_sample.lp"
  full_file="$OUTPUT_DIR/bucket_${bucket_id}.lp"

  echo "============================================================"
  echo "Bucket ID: $bucket_id"
  echo "============================================================"

  echo "Previewing first 20 lines:"
  influxd inspect export-lp \
    --bucket-id "$bucket_id" \
    --engine-path "$ENGINE_PATH" \
    --output-path - \
    | head -20 || true

  echo
  echo "Writing sample export: $sample_file"
  influxd inspect export-lp \
    --bucket-id "$bucket_id" \
    --engine-path "$ENGINE_PATH" \
    --output-path - \
    | head -n "$SAMPLE_LINES" \
    > "$sample_file"

  sample_size="$(wc -l < "$sample_file")"
  echo "Sample lines written: $sample_size"

  # Uncomment this block if you want full line protocol exports.
  # Be careful: these files can be large.
  #
  # echo "Writing full export: $full_file"
  # influxd inspect export-lp \
  #   --bucket-id "$bucket_id" \
  #   --engine-path "$ENGINE_PATH" \
  #   --output-path "$full_file"

  echo
done

echo "Done."
echo
echo "Next:"
echo "  python3 scripts/infer_influx_schema.py schema_exports/*.lp"