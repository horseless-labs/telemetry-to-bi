import argparse
import os
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from telemetry_to_bi.pipeline import run_pipeline


def require_env(name: str) -> str:
    value = os.environ.get(name)

    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")

    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export route-level transit telemetry analytics.",
    )

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

    return parser.parse_args()


def resolve_dates(args: argparse.Namespace) -> tuple[str, str]:
    if args.date:
        return args.date, args.date

    if args.start_date and args.end_date:
        return args.start_date, args.end_date

    raise RuntimeError("Use either --date or both --start-date and --end-date.")


def main() -> None:
    args = parse_args()

    bucket = require_env("INFLUX_BUCKET")
    org = require_env("INFLUX_ORG")
    token = require_env("INFLUX_TOKEN")

    start_date, end_date = resolve_dates(args)

    export_dir = Path("exports") / args.route_id
    export_dir.mkdir(parents=True, exist_ok=True)

    date_label = args.date or f"{args.start_date}_to_{args.end_date}"
    output_path = Path(
        args.output
        or export_dir / f"route_{args.route_id}_{date_label}_analytics.xlsx"
    )

    with tqdm(total=1, desc="Telemetry to BI") as pbar:
        metadata = run_pipeline(
            bucket=bucket,
            org=org,
            token=token,
            route_id=args.route_id,
            start_date=start_date,
            end_date=end_date,
            output_path=output_path,
            google_sheet=args.google_sheet,
            share_with=args.share_with,
        )
        pbar.update(1)

    print("\n--- Export Complete ---")
    print(f"Total rows: {metadata['num_raw_rows']:,}")

    if args.google_sheet:
        print(f"Google Sheet: {metadata.get('google_sheet_url')}")
    else:
        print(f"Summary Excel location: {output_path.resolve()}")
        print(f"CSV folder: {(output_path.parent / f'{output_path.stem}_csvs').resolve()}")


if __name__ == "__main__":
    main()