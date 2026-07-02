"""
Google Sheets publishing utilities for Telemetry to BI.

This module creates a Google Sheets workbook and writes telemetry analytics
DataFrames into separate tabs.

Supported auth modes:

1. OAuth user auth
   Required env:
       GOOGLE_AUTH_MODE=oauth
       GOOGLE_OAUTH_CLIENT_SECRET=/path/to/client_secret.json

   Optional env:
       GOOGLE_OAUTH_TOKEN=token.json
       GOOGLE_DRIVE_FOLDER_ID=<folder id>

2. Service account auth
   Required env:
       GOOGLE_AUTH_MODE=service_account
       GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

   Optional env:
       GOOGLE_DRIVE_FOLDER_ID=<folder id>

Notes:
    - OAuth is best when you want the workbook created in your personal Drive.
    - Service account auth is best for server-side automation, but the service
      account must have access to the target Drive folder.
"""

from __future__ import annotations

import os
from typing import Any

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe


SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def require_env(name: str) -> str:
    """
    Return a required environment variable or raise a clear error.
    """
    value = os.environ.get(name)

    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")

    return value


def get_gspread_client() -> gspread.Client:
    """
    Create an authenticated gspread client.

    Uses GOOGLE_AUTH_MODE to decide between OAuth and service account auth.

    Supported values:
        - oauth
        - service_account
    """
    auth_mode = os.environ.get("GOOGLE_AUTH_MODE", "oauth").strip().lower()

    if auth_mode == "oauth":
        client_secret = require_env("GOOGLE_OAUTH_CLIENT_SECRET")
        token_file = os.environ.get("GOOGLE_OAUTH_TOKEN", "token.json").strip()

        return gspread.oauth(
            scopes=SHEETS_SCOPES,
            credentials_filename=client_secret,
            authorized_user_filename=token_file,
        )

    if auth_mode == "service_account":
        credentials_path = require_env("GOOGLE_APPLICATION_CREDENTIALS")

        credentials = Credentials.from_service_account_file(
            credentials_path,
            scopes=SHEETS_SCOPES,
        )

        return gspread.authorize(credentials)

    raise RuntimeError(
        f"Unknown GOOGLE_AUTH_MODE={auth_mode!r}. "
        "Use 'oauth' or 'service_account'."
    )


def sanitize_for_sheets(df: pd.DataFrame | None) -> pd.DataFrame:
    """
    Convert a DataFrame into a Google-Sheets-friendly DataFrame.

    Handles:
        - None
        - empty DataFrames
        - datetime columns
        - date objects
        - NaN / NaT / pd.NA
    """
    if df is None or df.empty:
        return pd.DataFrame()

    cleaned = df.copy()

    for col in cleaned.columns:
        if pd.api.types.is_datetime64_any_dtype(cleaned[col]):
            cleaned[col] = cleaned[col].astype(str)

    cleaned = cleaned.astype(object)
    cleaned = cleaned.where(pd.notna(cleaned), "")

    return cleaned


def make_metadata_dataframe(metadata: dict[str, Any]) -> pd.DataFrame:
    """
    Convert metadata dict into a two-column DataFrame.
    """
    return pd.DataFrame(
        [{"metric": key, "value": str(value)} for key, value in metadata.items()]
    )


def create_spreadsheet(
    client: gspread.Client,
    workbook_title: str,
) -> gspread.Spreadsheet:
    """
    Create a spreadsheet.

    If GOOGLE_DRIVE_FOLDER_ID is set, create the workbook inside that folder.
    Otherwise, create it in the authenticated user's default Drive location.
    """
    drive_folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

    if drive_folder_id:
        return client.create(
            workbook_title,
            folder_id=drive_folder_id,
        )

    return client.create(workbook_title)


def get_or_create_worksheet(
    spreadsheet: gspread.Spreadsheet,
    sheet_name: str,
    df: pd.DataFrame,
) -> gspread.Worksheet:
    """
    Return an existing worksheet or create it if missing.
    """
    sheet_name_clean = sheet_name[:100]

    try:
        worksheet = spreadsheet.worksheet(sheet_name_clean)
        worksheet.clear()
        return worksheet

    except gspread.WorksheetNotFound:
        rows = max(len(df) + 10, 100)
        cols = max(len(df.columns) + 5, 20)

        return spreadsheet.add_worksheet(
            title=sheet_name_clean,
            rows=rows,
            cols=cols,
        )


def format_worksheet(worksheet: gspread.Worksheet) -> None:
    """
    Apply basic formatting to a worksheet.

    Formatting is intentionally light:
        - freeze header row
        - bold header row
        - light gray header background
        - basic filter
    """
    worksheet.freeze(rows=1)

    worksheet.format(
        "1:1",
        {
            "textFormat": {"bold": True},
            "backgroundColor": {
                "red": 0.90,
                "green": 0.90,
                "blue": 0.90,
            },
        },
    )

    try:
        worksheet.set_basic_filter()
    except Exception:
        # Formatting failure should not break publishing.
        pass


def write_tab(
    spreadsheet: gspread.Spreadsheet,
    sheet_name: str,
    df: pd.DataFrame | None,
) -> None:
    """
    Write a DataFrame to a single Google Sheets tab.
    """
    cleaned_df = sanitize_for_sheets(df)

    worksheet = get_or_create_worksheet(
        spreadsheet=spreadsheet,
        sheet_name=sheet_name,
        df=cleaned_df,
    )

    if cleaned_df.empty:
        worksheet.update("A1", [["No data returned for this summary."]])
        return

    set_with_dataframe(
        worksheet,
        cleaned_df,
        include_index=False,
        include_column_header=True,
        resize=True,
    )

    format_worksheet(worksheet)


def reorder_tabs(
    spreadsheet: gspread.Spreadsheet,
    ordered_tab_names: list[str],
) -> None:
    """
    Reorder worksheets to match the desired workbook layout.

    This is nice-to-have only. If it fails, the workbook is still usable.
    """
    try:
        worksheets = []

        for name in ordered_tab_names:
            worksheets.append(spreadsheet.worksheet(name[:100]))

        spreadsheet.reorder_worksheets(worksheets)

    except Exception:
        pass


def share_spreadsheet(
    spreadsheet: gspread.Spreadsheet,
    share_with: str | None,
) -> None:
    """
    Optionally share the spreadsheet with a Google account email.

    If share_with is None or blank, do nothing.
    """
    if not share_with:
        return

    spreadsheet.share(
        share_with,
        perm_type="user",
        role="writer",
    )


def write_google_sheets_workbook(
    workbook_title: str,
    raw_df: pd.DataFrame,
    summaries: dict[str, pd.DataFrame],
    metadata: dict[str, Any],
    share_with: str | None = None,
) -> str:
    """
    Create a Google Sheets workbook and write telemetry analytics tabs.

    Args:
        workbook_title:
            Title for the new Google Sheets workbook.

        raw_df:
            Raw parsed telemetry DataFrame.

        summaries:
            Dictionary of summary DataFrames. Expected keys:
                - daily_summary
                - hourly_summary
                - stop_summary
                - weekday_summary
                - operational_summary

        metadata:
            Pipeline metadata to write to the Metadata tab.

        share_with:
            Optional Google account email to share the workbook with.

    Returns:
        The Google Sheets URL.
    """
    client = get_gspread_client()
    spreadsheet = create_spreadsheet(
        client=client,
        workbook_title=workbook_title,
    )

    metadata_df = make_metadata_dataframe(metadata)

    tabs = [
        ("Metadata", metadata_df),
        ("Daily Summary", summaries.get("daily_summary", pd.DataFrame())),
        ("Hourly Summary", summaries.get("hourly_summary", pd.DataFrame())),
        ("Stop Summary", summaries.get("stop_summary", pd.DataFrame())),
        ("Weekday Summary", summaries.get("weekday_summary", pd.DataFrame())),
        ("Operational Summary", summaries.get("operational_summary", pd.DataFrame())),
        ("Raw Data", raw_df),
    ]

    # Reuse the default first worksheet instead of leaving "Sheet1" around.
    try:
        spreadsheet.sheet1.update_title("Metadata")
    except Exception:
        # If this fails, write_tab will still create/use a Metadata tab.
        pass

    for sheet_name, df in tabs:
        write_tab(
            spreadsheet=spreadsheet,
            sheet_name=sheet_name,
            df=df,
        )

    reorder_tabs(
        spreadsheet=spreadsheet,
        ordered_tab_names=[sheet_name for sheet_name, _ in tabs],
    )

    share_spreadsheet(
        spreadsheet=spreadsheet,
        share_with=share_with,
    )

    return spreadsheet.url