#!/bin/bash

# Configuration
TOKEN_FILE="influx_token.txt"
ORG_NAME="Horseless Labs"
BUCKET_NAME="wimbac"

# Check if the token file exists
if [ ! -f "$TOKEN_FILE" ]; then
    echo "Error: $TOKEN_FILE not found."
    return 1
fi

# Export the variables
export INFLUX_TOKEN=$(cat "$TOKEN_FILE")
export INFLUX_ORG="$ORG_NAME"
export INFLUX_BUCKET="$BUCKET_NAME"

echo "InfluxDB environment variables loaded:"
echo "  ORG: $INFLUX_ORG"
echo "  BUCKET: $INFLUX_BUCKET"
echo "  TOKEN: [LOADED FROM $TOKEN_FILE]"