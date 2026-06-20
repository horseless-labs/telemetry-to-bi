#!/usr/bin/env python3

import argparse
import os
import subprocess
from io import StringIO
from pathlib import Path

import pandas as pd


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def run_influx_query(
    container_name: str,
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
        "docker",
        "exec",
        "-e",
        f"INFLUX_TOKEN={token}",
        container_name,
        "influx",
        "query",
        flux_query,
        "--org",
        org,
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

    # Drop Influx metadata columns and blank columns.
    drop_cols = [
        col
        for col in df.columns
        if str(col).startswith("Unnamed")
        or col == ""
        or col in {"result", "table", "_start", "_stop", "_measurement"}
    ]

    df = df.drop(columns=drop_cols, errors="ignore")

    # Remove accidental repeated header rows, just in case.
    if "_time" in df.columns:
        df = df[df["_time"] != "_time"]

    if "_time" in df.columns:
        df["_time"] = pd.to_datetime(df["_time"], errors="coerce", utc=True)
        df["_time"] = df["_time"].dt.tz_convert("UTC").dt.tz_localize(None)

    for col in ["delay_seconds", "lat", "lon"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["route_id", "stop_id", "trip_id", "vehicle_id"]:
        if col in df.columns:
            df[col] = df[col].astype("string")

    if "_time" in df.columns:
        df["service_date"] = df["_time"].dt.date
        df["hour"] = df["_time"].dt.hour
        df["weekday"] = df["_time"].dt.day_name()

    if "lat" in df.columns:
        df["lat_suspicious"] = df["lat"].notna() & ~df["lat"].between(35, 50)

    if "lon" in df.columns:
        df["lon_suspicious"] = df["lon"].notna() & ~df["lon"].between(-90, -70)

    return df


def make_daily_route_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "delay_seconds" not in df.columns:
        return pd.DataFrame()

    group_cols = ["service_date", "route_id"]

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


def make_hourly_route_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "delay_seconds" not in df.columns:
        return pd.DataFrame()

    group_cols = ["service_date", "route_id", "hour"]

    return (
        df.groupby(group_cols, dropna=False)
        .agg(
            num_points=("delay_seconds", "count"),
            avg_delay_seconds=("delay_seconds", "mean"),
            median_delay_seconds=("delay_seconds", "median"),
            p90_delay_seconds=("delay_seconds", lambda s: s.quantile(0.90)),
            max_delay_seconds=("delay_seconds", "max"),
        )
        .reset_index()
    )


def make_stop_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "delay_seconds" not in df.columns or "stop_id" not in df.columns:
        return pd.DataFrame()

    if df["stop_id"].isna().all():
        return pd.DataFrame()

    group_cols = ["service_date", "route_id", "stop_id"]

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


def write_excel(
    output_path: Path,
    raw_df: pd.DataFrame,
    daily_summary: pd.DataFrame,
    hourly_summary: pd.DataFrame,
    stop_summary: pd.DataFrame,
    metadata: dict,
) -> None:
    data_dictionary = pd.DataFrame(
        [
            ["_time", "Timestamp of observation"],
            ["route_id", "Transit route identifier"],
            ["stop_id", "Stop identifier, if present"],
            ["trip_id", "Trip identifier, if present"],
            ["vehicle_id", "Vehicle identifier, if present"],
            ["delay_seconds", "Schedule delay in seconds"],
            ["lat", "Latitude"],
            ["lon", "Longitude"],
            ["service_date", "Date derived from _time"],
            ["hour", "Hour of day derived from _time"],
            ["weekday", "Weekday derived from _time"],
            ["pct_on_time", "Share of records between -60 and 300 seconds delay"],
            ["pct_late_5min", "Share of records more than 5 minutes late"],
            ["pct_late_10min", "Share of records more than 10 minutes late"],
        ],
        columns=["column", "description"],
    )

    run_metadata = pd.DataFrame(
        list(metadata.items()),
        columns=["setting", "value"],
    )

    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        raw_df.to_excel(writer, sheet_name="Raw Data", index=False)
        daily_summary.to_excel(writer, sheet_name="Daily Route Summary", index=False)
        hourly_summary.to_excel(writer, sheet_name="Hourly Summary", index=False)

        if not stop_summary.empty:
            stop_summary.to_excel(writer, sheet_name="Stop Summary", index=False)

        data_dictionary.to_excel(writer, sheet_name="Data Dictionary", index=False)
        run_metadata.to_excel(writer, sheet_name="Run Metadata", index=False)

        workbook = writer.book

        header_format = workbook.add_format(
            {
                "bold": True,
                "bg_color": "#D9EAF7",
                "border": 1,
            }
        )

        percent_format = workbook.add_format({"num_format": "0.0%"})
        seconds_format = workbook.add_format({"num_format": "0.0"})
        datetime_format = workbook.add_format({"num_format": "yyyy-mm-dd hh:mm:ss"})

        for sheet_name, sheet_df in {
            "Raw Data": raw_df,
            "Daily Route Summary": daily_summary,
            "Hourly Summary": hourly_summary,
            "Stop Summary": stop_summary,
            "Data Dictionary": data_dictionary,
            "Run Metadata": run_metadata,
        }.items():
            if sheet_name not in writer.sheets or sheet_df.empty:
                continue

            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes(1, 0)

            for col_idx, col_name in enumerate(sheet_df.columns):
                worksheet.write(0, col_idx, col_name, header_format)

                width = max(
                    len(str(col_name)) + 2,
                    min(28, int(sheet_df[col_name].astype(str).str.len().quantile(0.95)) + 2)
                    if not sheet_df.empty
                    else 12,
                )
                worksheet.set_column(col_idx, col_idx, width)

                if col_name == "_time":
                    worksheet.set_column(col_idx, col_idx, 22, datetime_format)
                elif col_name.startswith("pct_"):
                    worksheet.set_column(col_idx, col_idx, 14, percent_format)
                elif "delay_seconds" in col_name:
                    worksheet.set_column(col_idx, col_idx, 18, seconds_format)

            worksheet.autofilter(0, 0, len(sheet_df), max(0, len(sheet_df.columns) - 1))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export one route/day from local Docker InfluxDB to Excel."
    )

    parser.add_argument("--route-id", required=True)
    parser.add_argument("--date", required=True, help="Service date, e.g. 2026-05-04")
    parser.add_argument("--container", default="local-influx")
    parser.add_argument("--output", default=None)

    args = parser.parse_args()

    bucket = require_env("INFLUX_BUCKET")
    org = require_env("INFLUX_ORG")
    token = require_env("INFLUX_TOKEN")

    start = f"{args.date}T00:00:00Z"

    # Simple next-day stop. Good enough for UTC-based first pass.
    stop_date = (pd.to_datetime(args.date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    stop = f"{stop_date}T00:00:00Z"

    output_path = Path(
        args.output
        or f"route_{args.route_id}_{args.date}_analytics.xlsx"
    )

    print(f"Querying route {args.route_id} from {start} to {stop}...")

    csv_text = run_influx_query(
        container_name=args.container,
        bucket=bucket,
        org=org,
        token=token,
        route_id=args.route_id,
        start=start,
        stop=stop,
    )

    raw_df = parse_influx_csv(csv_text)

    print("Columns after parsing:")
    print(list(raw_df.columns))

    if "_time" in raw_df.columns:
        header_rows = raw_df[raw_df["_time"].astype(str).eq("_time")]
        print(f"Repeated header rows remaining: {len(header_rows)}")

    for col in ["lat", "lon", "delay_seconds"]:
        if col in raw_df.columns:
            print(f"{col} sample:")
            print(raw_df[col].dropna().head(10).to_string(index=False))

    print(f"Rows returned: {len(raw_df):,}")

    daily_summary = make_daily_route_summary(raw_df)
    hourly_summary = make_hourly_route_summary(raw_df)
    stop_summary = make_stop_summary(raw_df)

    metadata = {
        "container": args.container,
        "bucket": bucket,
        "org": org,
        "route_id": args.route_id,
        "start": start,
        "stop": stop,
        "output": str(output_path),
        "raw_rows": len(raw_df),
    }

    write_excel(
        output_path=output_path,
        raw_df=raw_df,
        daily_summary=daily_summary,
        hourly_summary=hourly_summary,
        stop_summary=stop_summary,
        metadata=metadata,
    )

    print(f"Excel export complete: {output_path}")


if __name__ == "__main__":
    main()