#!/bin/bash

# Configuration
TOKEN_FILE="influx_token.txt"
ORG_NAME="Horseless Labs"
BUCKET_NAME="wimbac"
GOOGLE_CREDS_FILE="telemetry-to-bi-fb84db1b17ff.json"
FOLDER_ID_FILE="drive_folder_id.txt"

# Check if required files exist
if [ ! -f "$TOKEN_FILE" ]; then
    echo "Error: $TOKEN_FILE not found."
    return 1 2>/dev/null || exit 1
fi

if [ ! -f "$GOOGLE_CREDS_FILE" ]; then
    echo "Error: $GOOGLE_CREDS_FILE not found."
    return 1 2>/dev/null || exit 1
fi

if [ ! -f "$FOLDER_ID_FILE" ]; then
    echo "Error: $FOLDER_ID_FILE not found."
    return 1 2>/dev/null || exit 1
fi

# Google OAuth configuration
GOOGLE_OAUTH_CLIENT_SECRET_FILE="client_secret.json"
GOOGLE_OAUTH_TOKEN_FILE="token.json"

if [ ! -f "$GOOGLE_OAUTH_CLIENT_SECRET_FILE" ]; then
    echo "Error: $GOOGLE_OAUTH_CLIENT_SECRET_FILE not found."
    return 1 2>/dev/null || exit 1
fi

# Export variables
export INFLUX_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
export INFLUX_ORG="$ORG_NAME"
export INFLUX_BUCKET="$BUCKET_NAME"
export GOOGLE_APPLICATION_CREDENTIALS="$PWD/$GOOGLE_CREDS_FILE"
export GOOGLE_DRIVE_FOLDER_ID="$(tr -d '\r\n' < "$FOLDER_ID_FILE")"

export GOOGLE_AUTH_MODE="oauth"
export GOOGLE_OAUTH_CLIENT_SECRET="$PWD/client_secret.json"
export GOOGLE_OAUTH_TOKEN="$PWD/token.json"

echo "Environment variables loaded:"
echo "  ORG: $INFLUX_ORG"
echo "  BUCKET: $INFLUX_BUCKET"
echo "  TOKEN: [LOADED FROM $TOKEN_FILE]"
echo "  GOOGLE CREDS: $GOOGLE_APPLICATION_CREDENTIALS"
echo "  GOOGLE DRIVE FOLDER ID: $GOOGLE_DRIVE_FOLDER_ID"

echo "  GOOGLE AUTH MODE: $GOOGLE_AUTH_MODE"
echo "  GOOGLE OAUTH CLIENT SECRET: $GOOGLE_OAUTH_CLIENT_SECRET"
echo "  GOOGLE OAUTH TOKEN: $GOOGLE_OAUTH_TOKEN"