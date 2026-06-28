#!/bin/bash

# Configuration
TOKEN_FILE="influx_token.txt"
ORG_NAME="Horseless Labs"
BUCKET_NAME="wimbac"
GOOGLE_CREDS_FILE="telemetry-to-bi-fb84db1b17ff.json"

# Check if required files exist
if [ ! -f "$TOKEN_FILE" ]; then
    echo "Error: $TOKEN_FILE not found."
    exit 1
fi

if [ ! -f "$GOOGLE_CREDS_FILE" ]; then
    echo "Error: $GOOGLE_CREDS_FILE not found."
    exit 1
fi

# Export variables
export INFLUX_TOKEN="$(<"$TOKEN_FILE")"
export INFLUX_ORG="$ORG_NAME"
export INFLUX_BUCKET="$BUCKET_NAME"
export GOOGLE_APPLICATION_CREDENTIALS="$PWD/$GOOGLE_CREDS_FILE"

echo "Environment variables loaded:"
echo "  ORG: $INFLUX_ORG"
echo "  BUCKET: $INFLUX_BUCKET"
echo "  TOKEN: [LOADED FROM $TOKEN_FILE]"
echo "  GOOGLE CREDS: $GOOGLE_APPLICATION_CREDENTIALS"