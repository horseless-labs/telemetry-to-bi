import json
from pathlib import Path

import pandas as pd


def write_local_artifacts(
    output_path: Path,
    raw_df: pd.DataFrame,
    summaries: dict[str, pd.DataFrame],
    metadata: dict,
) -> None:
    print(f"Exporting BI artifacts to {output_path.parent}...")

    try:
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            summaries["daily_summary"].to_excel(writer, sheet_name="Daily Summary", index=False)
            summaries["hourly_summary"].to_excel(writer, sheet_name="Hourly Summary", index=False)
            summaries["stop_summary"].to_excel(writer, sheet_name="Stop Summary", index=False)
            summaries["weekday_summary"].to_excel(writer, sheet_name="Weekday Summary", index=False)
            summaries["operational_summary"].to_excel(writer, sheet_name="Op Summary", index=False)

            meta_df = pd.DataFrame(list(metadata.items()), columns=["Metric", "Value"])
            meta_df.to_excel(writer, sheet_name="Metadata", index=False)

        print(f"  -> Saved Excel artifact: {output_path.name}")

    except Exception as exc:
        print(f"  -> Warning: Excel export failed ({exc}). Skipping Excel.")

    csv_dir = output_path.parent / f"{output_path.stem}_csvs"
    csv_dir.mkdir(exist_ok=True, parents=True)

    exports = {
        "raw_data": raw_df,
        **summaries,
    }

    for name, df in exports.items():
        if df.empty:
            continue

        csv_file = csv_dir / f"{name}.csv"
        df_clean = df.copy()

        numeric_cols = df_clean.select_dtypes(include=["float64", "float32"]).columns
        df_clean[numeric_cols] = df_clean[numeric_cols].round(4)

        df_clean.to_csv(
            csv_file,
            index=False,
            encoding="utf-8-sig",
            lineterminator="\r\n",
        )

    with open(csv_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4, default=str)

    print(f"  -> Saved clean CSVs to: {csv_dir.name}/")