#!/usr/bin/env python3

import argparse
import os
import subprocess
from io import StringIO
from pathlib import Path

import pandas as pd
from tqdm import tqdm


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
    
    # 1. ALWAYS write the raw dataframe to a CSV directly
    raw_csv_path = output_path.with_name(f"{output_path.stem}_raw.csv")
    raw_df.to_csv(raw_csv_path, index=False)
    
    metadata.update({
        "raw_csv_output": str(raw_csv_path.resolve()),
        "raw_rows_exported": len(raw_df),
    })

    # 2. Setup the Data Dictionary for the Excel Summary File
    data_dictionary = pd.DataFrame(
        [
            ["_time", "Timestamp of observation"],
            ["route_id", "Transit route identifier"],
            ["stop_id", "Stop identifier, if present"],
            ["delay_seconds", "Schedule delay in seconds"],
            ["service_date", "Date derived from _time"],
            ["hour", "Hour of day derived from _time"],
            ["weekday", "Weekday derived from _time"],
            ["operational_period", "Peak AM (6-8), Peak PM (15-17), or Off-Peak"],
            ["pct_late_5min", "Share of records more than 5 minutes late"],
        ],
        columns=["column", "description"],
    )

    run_metadata = pd.DataFrame(list(metadata.items()), columns=["setting", "value"])

    # 3. Write ONLY the summaries to Excel (Fixes the memory/hanging bug)
    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        daily_summary.to_excel(writer, sheet_name="Daily Summary", index=False)
        hourly_summary.to_excel(writer, sheet_name="Hourly Summary", index=False)
        weekday_summary.to_excel(writer, sheet_name="Weekday Summary", index=False)
        operational_summary.to_excel(writer, sheet_name="Peak vs Off-Peak", index=False)
        
        if not stop_summary.empty:
            stop_summary.to_excel(writer, sheet_name="Stop Summary", index=False)

        data_dictionary.to_excel(writer, sheet_name="Data Dictionary", index=False)
        run_metadata.to_excel(writer, sheet_name="Run Metadata", index=False)

        workbook = writer.book
        header_format = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
        percent_format = workbook.add_format({"num_format": "0.0%"})
        seconds_format = workbook.add_format({"num_format": "0.0"})

        sheets_to_format = {
            "Daily Summary": daily_summary,
            "Hourly Summary": hourly_summary,
            "Weekday Summary": weekday_summary,
            "Peak vs Off-Peak": operational_summary,
            "Stop Summary": stop_summary,
            "Data Dictionary": data_dictionary,
            "Run Metadata": run_metadata,
        }

        for sheet_name, sheet_df in sheets_to_format.items():
            if sheet_name not in writer.sheets or sheet_df.empty:
                continue

            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes(1, 0)

            for col_idx, col_name in enumerate(sheet_df.columns):
                worksheet.write(0, col_idx, col_name, header_format)
                width = max(
                    len(str(col_name)) + 2,
                    min(28, int(sheet_df[col_name].astype(str).str.len().quantile(0.95)) + 2) if not sheet_df.empty else 12,
                )
                worksheet.set_column(col_idx, col_idx, width)

                if str(col_name).startswith("pct_"):
                    worksheet.set_column(col_idx, col_idx, 14, percent_format)
                elif "delay_seconds" in str(col_name):
                    worksheet.set_column(col_idx, col_idx, 18, seconds_format)
            
            worksheet.autofilter(0, 0, len(sheet_df), max(0, len(sheet_df.columns) - 1))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export transit analytics pipeline.")
    parser.add_argument("--route-id", required=True)
    parser.add_argument("--date", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output", default=None)

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
    print(f"Raw CSV location: {output_path.with_name(f'{output_path.stem}_raw.csv').resolve()}")
    print(f"Summary Excel location: {output_path.resolve()}")

if __name__ == "__main__":
    main()