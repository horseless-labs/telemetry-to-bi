#!/usr/bin/env python3

import argparse
import os
import subprocess
from io import StringIO
from pathlib import Path

import pandas as pd
from tqdm import tqdm

import json

## about to be redundant?
from openpyxl.styles import Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

# Google Sheets
import gspread
from gspread_dataframe import set_with_dataframe
from google.oauth2.service_account import Credentials

def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def clean_id_column(series: pd.Series) -> pd.Series:
    return (
        series
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .replace({"<NA>": pd.NA, "nan": pd.NA, "NaN": pd.NA, "": pd.NA})
    )

def run_influx_query(
    bucket: str,
    org: str,
    token: str,
    route_id: str,
    start: str,
    stop: str,
) -> str:
    flux_query = f'''
from(bucket:"{bucket}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => r.route_id == "{route_id}")
  |> filter(fn: (r) =>
    r._field == "delay_seconds" or
    r._field == "lat" or
    r._field == "lon"
  )
  |> toFloat()
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
  |> group(columns: [])
  |> pivot(
    rowKey: ["_time", "route_id", "stop_id", "trip_id", "vehicle_id"],
    columnKey: ["_field"],
    valueColumn: "_value"
  )
  |> keep(columns: [
    "_time",
    "route_id",
    "stop_id",
    "trip_id",
    "vehicle_id",
    "delay_seconds",
    "lat",
    "lon"
  ])
  |> sort(columns: ["_time"])
'''

    cmd = [
        "influx",
        "query",
        flux_query,
        "--org",
        org,
        "--token",
        token,
        "--raw",
    ]

    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Influx query failed.\n\n"
            f"STDOUT:\n{result.stdout}\n\n"
            f"STDERR:\n{result.stderr}"
        )

    return result.stdout

def parse_influx_csv(csv_text: str) -> pd.DataFrame:
    if not csv_text.strip():
        return pd.DataFrame()

    df = pd.read_csv(
        StringIO(csv_text),
        comment="#",
        low_memory=False,
    )

    drop_cols = [
        col
        for col in df.columns
        if str(col).startswith("Unnamed")
        or col == ""
        or col in {"result", "table", "_start", "_stop", "_measurement"}
    ]

    df = df.drop(columns=drop_cols, errors="ignore")

    if "_time" in df.columns:
        df = df[df["_time"] != "_time"]
        df["_time"] = pd.to_datetime(df["_time"], errors="coerce", utc=True)
        df["_time"] = df["_time"].dt.tz_convert("UTC").dt.tz_localize(None)

    for col in ["delay_seconds", "lat", "lon"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["route_id", "stop_id", "trip_id", "vehicle_id"]:
        if col in df.columns:
            df[col] = clean_id_column(df[col])

    if "_time" in df.columns:
        df["service_date"] = df["_time"].dt.date
        df["hour"] = df["_time"].dt.hour
        df["weekday"] = df["_time"].dt.day_name()
        
        df["operational_period"] = "Off-Peak"
        is_peak_am = df["hour"].between(6, 8, inclusive="both")
        is_peak_pm = df["hour"].between(15, 17, inclusive="both")
        
        df.loc[is_peak_am, "operational_period"] = "Peak AM"
        df.loc[is_peak_pm, "operational_period"] = "Peak PM"

    if "lat" in df.columns:
        df["lat_suspicious"] = df["lat"].notna() & ~df["lat"].between(35, 50)

    if "lon" in df.columns:
        df["lon_suspicious"] = df["lon"].notna() & ~df["lon"].between(-90, -70)

    has_lat_lon = (
        df.get("lat", pd.Series(index=df.index, dtype="float")).notna()
        & df.get("lon", pd.Series(index=df.index, dtype="float")).notna()
    )

    has_stop_id = (
        df.get("stop_id", pd.Series(index=df.index, dtype="string")).notna()
    )

    df["record_type"] = "unknown"
    df.loc[has_lat_lon, "record_type"] = "vehicle_position"
    df.loc[has_stop_id & ~has_lat_lon, "record_type"] = "stop_prediction"
    df.loc[has_stop_id & has_lat_lon, "record_type"] = "stop_with_position"

    return df


def _aggregate_delay(df: pd.DataFrame, group_cols: list) -> pd.DataFrame:
    return (
        df.groupby(group_cols, dropna=False)
        .agg(
            num_points=("delay_seconds", "count"),
            avg_delay_seconds=("delay_seconds", "mean"),
            median_delay_seconds=("delay_seconds", "median"),
            p90_delay_seconds=("delay_seconds", lambda s: s.quantile(0.90)),
            max_delay_seconds=("delay_seconds", "max"),
            pct_on_time=("delay_seconds", lambda s: s.between(-60, 300).mean()),
            pct_late_5min=("delay_seconds", lambda s: (s > 300).mean()),
            pct_late_10min=("delay_seconds", lambda s: (s > 600).mean()),
        )
        .reset_index()
    )

def make_daily_route_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "delay_seconds" not in df.columns: return pd.DataFrame()
    group_cols = ["service_date", "route_id"]
    if "record_type" in df.columns: group_cols.append("record_type")
    return _aggregate_delay(df, group_cols)

def make_hourly_route_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "delay_seconds" not in df.columns: return pd.DataFrame()
    group_cols = ["service_date", "route_id"]
    if "record_type" in df.columns: group_cols.append("record_type")
    group_cols.append("hour")
    return _aggregate_delay(df, group_cols)

def make_weekday_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "delay_seconds" not in df.columns or "weekday" not in df.columns:
        return pd.DataFrame()
    group_cols = ["route_id", "weekday"]
    summary = _aggregate_delay(df, group_cols)
    cats = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    summary['weekday'] = pd.Categorical(summary['weekday'], categories=cats, ordered=True)
    return summary.sort_values('weekday')

def make_operational_period_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "delay_seconds" not in df.columns or "operational_period" not in df.columns:
        return pd.DataFrame()
    group_cols = ["service_date", "route_id", "operational_period"]
    return _aggregate_delay(df, group_cols)

def make_stop_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "delay_seconds" not in df.columns or "stop_id" not in df.columns:
        return pd.DataFrame()
    if df["stop_id"].isna().all(): return pd.DataFrame()
    if "record_type" in df.columns:
        df = df[df["record_type"].isin(["stop_prediction", "stop_with_position"])].copy()
    else:
        df = df[df["stop_id"].notna()].copy()
    if df.empty: return pd.DataFrame()
    group_cols = ["service_date", "route_id", "stop_id"]
    return _aggregate_delay(df, group_cols)

# .xlsx outputs
def write_outputs(
    output_path: Path,
    raw_df: pd.DataFrame,
    daily_summary: pd.DataFrame,
    hourly_summary: pd.DataFrame,
    stop_summary: pd.DataFrame,
    weekday_summary: pd.DataFrame,
    operational_summary: pd.DataFrame,
    metadata: dict,
) -> None:
    """
    Writes a plain, unformatted Excel file for human review, 
    and clean CSVs for Power BI ingestion to bypass PBI model hangs.
    """
    print(f"Exporting BI artifacts to {output_path.parent}...")
    
    # 1. Write the Human-Readable Excel (Plain, no formatting to avoid OpenXML errors)
    try:
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            daily_summary.to_excel(writer, sheet_name="Daily Summary", index=False)
            hourly_summary.to_excel(writer, sheet_name="Hourly Summary", index=False)
            stop_summary.to_excel(writer, sheet_name="Stop Summary", index=False)
            weekday_summary.to_excel(writer, sheet_name="Weekday Summary", index=False)
            operational_summary.to_excel(writer, sheet_name="Op Summary", index=False)
            
            # Write metadata as a simple key-value sheet
            meta_df = pd.DataFrame(list(metadata.items()), columns=["Metric", "Value"])
            meta_df.to_excel(writer, sheet_name="Metadata", index=False)
        print(f"  -> Saved unformatted Excel artifact: {output_path.name}")
    except Exception as e:
        print(f"  -> Warning: Excel export failed ({e}). Skipping Excel.")

    # 2. Write the Machine-Readable CSVs for Power BI
    # Create a subfolder for this specific run's CSVs to keep things tidy
    csv_dir = output_path.parent / f"{output_path.stem}_csvs"
    csv_dir.mkdir(exist_ok=True, parents=True)

    # Dictionary of dataframes to export
    exports = {
        "raw_data": raw_df,
        "daily_summary": daily_summary,
        "hourly_summary": hourly_summary,
        "stop_summary": stop_summary,
        "weekday_summary": weekday_summary,
        "operational_summary": operational_summary
    }

    for name, df in exports.items():
        if not df.empty:
            csv_file = csv_dir / f"{name}.csv"
            # Create a clean copy to modify
            df_clean = df.copy()
            
            # Round ONLY numeric columns to 4 decimal places to prevent PBI hanging
            numeric_cols = df_clean.select_dtypes(include=['float64', 'float32']).columns
            df_clean[numeric_cols] = df_clean[numeric_cols].round(4)
            
            # Force Windows line endings (\r\n) and export
            df_clean.to_csv(
                csv_file, 
                index=False, 
                encoding="utf-8-sig", 
                lineterminator='\r\n'
            )
            
    # Dump metadata to JSON for good measure
    with open(csv_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4, default=str)

    print(f"  -> Saved clean CSVs to: {csv_dir.name}/ (Use these for Power BI)")

def get_gspread_client():
    import gspread

    auth_mode = os.environ.get("GOOGLE_AUTH_MODE", "oauth").strip().lower()

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    if auth_mode == "oauth":
        client_secret = require_env("GOOGLE_OAUTH_CLIENT_SECRET")
        token_file = os.environ.get("GOOGLE_OAUTH_TOKEN", "token.json").strip()

        return gspread.oauth(
            scopes=scopes,
            credentials_filename=client_secret,
            authorized_user_filename=token_file,
        )

    if auth_mode == "service_account":
        from google.oauth2.service_account import Credentials

        credentials_path = require_env("GOOGLE_APPLICATION_CREDENTIALS")

        credentials = Credentials.from_service_account_file(
            credentials_path,
            scopes=scopes,
        )

        return gspread.authorize(credentials)

    raise RuntimeError(
        f"Unknown GOOGLE_AUTH_MODE={auth_mode!r}. Use 'oauth' or 'service_account'."
    )

# Googel Sheets outputs
def write_google_sheets_workbook(
    workbook_title: str,
    raw_df: pd.DataFrame,
    daily_summary: pd.DataFrame,
    hourly_summary: pd.DataFrame,
    stop_summary: pd.DataFrame,
    weekday_summary: pd.DataFrame,
    operational_summary: pd.DataFrame,
    metadata: dict,
    share_with: str | None = None,
) -> str:
    """
    Create a Google Sheets workbook and write telemetry analytics tabs.

    Requires:
        pip install gspread gspread-dataframe google-auth

    Auth:
        export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"

    Returns:
        Google Sheets URL.
    """

    credentials_path = require_env("GOOGLE_APPLICATION_CREDENTIALS")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    client = get_gspread_client()
    spreadsheet = client.create(workbook_title)

    drive_folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

    if drive_folder_id:
        spreadsheet = client.create(
            workbook_title,
            folder_id=drive_folder_id,
        )
    else:
        spreadsheet = client.create(workbook_title)

    def sanitize_for_sheets(df: pd.DataFrame) -> pd.DataFrame:
        """
        Make dataframe values friendlier for Google Sheets.
        """
        if df is None or df.empty:
            return pd.DataFrame()

        cleaned = df.copy()

        for col in cleaned.columns:
            if pd.api.types.is_datetime64_any_dtype(cleaned[col]):
                cleaned[col] = cleaned[col].astype(str)

        # Convert Python date objects, nullable values, and NaN/NaT safely.
        cleaned = cleaned.astype(object)
        cleaned = cleaned.where(pd.notna(cleaned), "")

        return cleaned

    def write_tab(sheet_name: str, df: pd.DataFrame) -> None:
        df = sanitize_for_sheets(df)

        # Google Sheets tab names max out at 100 chars.
        sheet_name_clean = sheet_name[:100]

        try:
            worksheet = spreadsheet.worksheet(sheet_name_clean)
            worksheet.clear()
        except gspread.WorksheetNotFound:
            rows = max(len(df) + 10, 100)
            cols = max(len(df.columns) + 5, 20)
            worksheet = spreadsheet.add_worksheet(
                title=sheet_name_clean,
                rows=rows,
                cols=cols,
            )

        if df.empty:
            worksheet.update("A1", [["No data returned for this summary."]])
            return

        set_with_dataframe(
            worksheet,
            df,
            include_index=False,
            include_column_header=True,
            resize=True,
        )

        # Freeze header row.
        worksheet.freeze(rows=1)

        # Bold header row and give it a light fill.
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

        # Basic filter over the populated range.
        worksheet.set_basic_filter()

    metadata_df = pd.DataFrame(
        [{"metric": key, "value": str(value)} for key, value in metadata.items()]
    )

    tabs = [
        ("Metadata", metadata_df),
        ("Daily Summary", daily_summary),
        ("Hourly Summary", hourly_summary),
        ("Stop Summary", stop_summary),
        ("Weekday Summary", weekday_summary),
        ("Operational Summary", operational_summary),
        ("Raw Data", raw_df),
    ]

    # Reuse the default first sheet for Metadata instead of leaving Sheet1 around.
    first_worksheet = spreadsheet.sheet1
    first_worksheet.update_title("Metadata")

    for sheet_name, df in tabs:
        write_tab(sheet_name, df)

    # Move Raw Data to the end visually.
    try:
        raw_sheet = spreadsheet.worksheet("Raw Data")
        spreadsheet.reorder_worksheets(
            [
                spreadsheet.worksheet("Metadata"),
                spreadsheet.worksheet("Daily Summary"),
                spreadsheet.worksheet("Hourly Summary"),
                spreadsheet.worksheet("Stop Summary"),
                spreadsheet.worksheet("Weekday Summary"),
                spreadsheet.worksheet("Operational Summary"),
                raw_sheet,
            ]
        )
    except Exception:
        # Not fatal. The workbook is still usable.
        pass

    return spreadsheet.url

def main() -> None:
    parser = argparse.ArgumentParser(description="Export transit analytics pipeline.")
    parser.add_argument("--route-id", required=True)
    parser.add_argument("--date", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--google-sheet",
        action="store_true",
        help="Create a Google Sheets workbook instead of local Excel/CSV outputs.",
    )

    parser.add_argument(
        "--share-with",
        default=None,
        help="Optional Google account email to share the created workbook with.",
    )

    args = parser.parse_args()

    bucket = require_env("INFLUX_BUCKET")
    org = require_env("INFLUX_ORG")
    token = require_env("INFLUX_TOKEN")

    if args.date:
        start_date = pd.to_datetime(args.date)
        stop_date = start_date + pd.Timedelta(days=1)
    elif args.start_date and args.end_date:
        start_date = pd.to_datetime(args.start_date)
        stop_date = pd.to_datetime(args.end_date) + pd.Timedelta(days=1)
    else:
        raise RuntimeError("Use either --date or both --start-date and --end-date")

    start = start_date.strftime("%Y-%m-%dT00:00:00Z")
    stop = stop_date.strftime("%Y-%m-%dT00:00:00Z")

    export_dir = Path("exports") / args.route_id
    export_dir.mkdir(parents=True, exist_ok=True)
    date_label = args.date or f"{args.start_date}_to_{args.end_date}"
    output_path = Path(args.output or export_dir / f"route_{args.route_id}_{date_label}_analytics.xlsx")

    # Initialize Progress Bar
    pipeline_steps = 5
    with tqdm(total=pipeline_steps, desc="Pipeline Progress", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}]") as pbar:
        
        pbar.set_postfix_str(f"Querying InfluxDB (Route {args.route_id})...")
        csv_text = run_influx_query(bucket, org, token, args.route_id, start, stop)
        pbar.update(1)

        pbar.set_postfix_str("Parsing raw CSV data...")
        raw_df = parse_influx_csv(csv_text)
        pbar.update(1)

        pbar.set_postfix_str("Generating Dataframe summaries...")
        daily_summary = make_daily_route_summary(raw_df)
        hourly_summary = make_hourly_route_summary(raw_df)
        stop_summary = make_stop_summary(raw_df)
        weekday_summary = make_weekday_summary(raw_df)
        operational_summary = make_operational_period_summary(raw_df)
        pbar.update(1)

        metadata = {
            "bucket": bucket,
            "org": org,
            "route_id": args.route_id,
            "start": start,
            "stop": stop,
            "summary_excel_output": str(output_path.resolve()),
        }

        pbar.set_postfix_str("Writing CSV and Excel files to disk...")

        if args.google_sheet:
            workbook_title = f"Telemetry to BI - Route {args.route_id} - {date_label}"

            metadata["artifact_type"] = "google_sheets_workbook"

            sheet_url = write_google_sheets_workbook(
                workbook_title=workbook_title,
                raw_df=raw_df,
                daily_summary=daily_summary,
                hourly_summary=hourly_summary,
                stop_summary=stop_summary,
                weekday_summary=weekday_summary,
                operational_summary=operational_summary,
                metadata=metadata,
                share_with=args.share_with,
            )

            metadata["google_sheet_url"] = sheet_url
            print(f"  -> Created Google Sheets workbook: {sheet_url}")
        else:
            # Excel outputs
            write_outputs(
                output_path=output_path,
                raw_df=raw_df,
                daily_summary=daily_summary,
                hourly_summary=hourly_summary,
                stop_summary=stop_summary,
                weekday_summary=weekday_summary,
                operational_summary=operational_summary,
                metadata=metadata,
            )
        pbar.update(2) # Finish out the bar

    print(f"\n--- Export Complete ---")
    print(f"Total Rows: {len(raw_df):,}")

    if args.google_sheet:
        print("Output: Google Sheets workbook")
    else:
        print(f"Summary Excel location: {output_path.resolve()}")
        print(f"CSV folder: {(output_path.parent / f'{output_path.stem}_csvs').resolve()}")

if __name__ == "__main__":
    main()