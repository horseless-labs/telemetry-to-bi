from pathlib import Path

import pandas as pd

from telemetry_to_bi.extract import run_influx_query
from telemetry_to_bi.publish_files import write_local_artifacts
from telemetry_to_bi.publish_sheets import write_google_sheets_workbook
from telemetry_to_bi.summarize import build_summaries
from telemetry_to_bi.transform import parse_influx_csv


def run_pipeline(
    *,
    bucket: str,
    org: str,
    token: str,
    route_id: str,
    start_date: str,
    end_date: str,
    output_path: Path,
    google_sheet: bool = False,
    share_with: str | None = None,
) -> dict:
    start_dt = pd.to_datetime(start_date)
    stop_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)

    start = start_dt.strftime("%Y-%m-%dT00:00:00Z")
    stop = stop_dt.strftime("%Y-%m-%dT00:00:00Z")

    csv_text = run_influx_query(
        bucket=bucket,
        org=org,
        token=token,
        route_id=route_id,
        start=start,
        stop=stop,
    )

    raw_df = parse_influx_csv(csv_text)
    summaries = build_summaries(raw_df)

    metadata = {
        "bucket": bucket,
        "org": org,
        "route_id": route_id,
        "start": start,
        "stop": stop,
        "num_raw_rows": len(raw_df),
    }

    if google_sheet:
        workbook_title = f"Telemetry to BI - Route {route_id} - {start_date}_to_{end_date}"
        metadata["artifact_type"] = "google_sheets_workbook"

        sheet_url = write_google_sheets_workbook(
            workbook_title=workbook_title,
            raw_df=raw_df,
            summaries=summaries,
            metadata=metadata,
            share_with=share_with,
        )

        metadata["google_sheet_url"] = sheet_url

    else:
        metadata["artifact_type"] = "local_excel_csv"
        metadata["summary_excel_output"] = str(output_path.resolve())

        write_local_artifacts(
            output_path=output_path,
            raw_df=raw_df,
            summaries=summaries,
            metadata=metadata,
        )

    return metadata