from io import StringIO

import pandas as pd


def clean_id_column(series: pd.Series) -> pd.Series:
    return (
        series
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .replace({"<NA>": pd.NA, "nan": pd.NA, "NaN": pd.NA, "": pd.NA})
    )


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

    has_stop_id = df.get(
        "stop_id",
        pd.Series(index=df.index, dtype="string"),
    ).notna()

    df["record_type"] = "unknown"
    df.loc[has_lat_lon, "record_type"] = "vehicle_position"
    df.loc[has_stop_id & ~has_lat_lon, "record_type"] = "stop_prediction"
    df.loc[has_stop_id & has_lat_lon, "record_type"] = "stop_with_position"

    return df