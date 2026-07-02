import pandas as pd


def aggregate_delay(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
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
    if df.empty or "delay_seconds" not in df.columns:
        return pd.DataFrame()

    group_cols = ["service_date", "route_id"]

    if "record_type" in df.columns:
        group_cols.append("record_type")

    return aggregate_delay(df, group_cols)


def make_hourly_route_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "delay_seconds" not in df.columns:
        return pd.DataFrame()

    group_cols = ["service_date", "route_id"]

    if "record_type" in df.columns:
        group_cols.append("record_type")

    group_cols.append("hour")

    return aggregate_delay(df, group_cols)


def make_weekday_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "delay_seconds" not in df.columns or "weekday" not in df.columns:
        return pd.DataFrame()

    group_cols = ["route_id", "weekday"]
    summary = aggregate_delay(df, group_cols)

    weekday_order = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]

    summary["weekday"] = pd.Categorical(
        summary["weekday"],
        categories=weekday_order,
        ordered=True,
    )

    return summary.sort_values("weekday")


def make_operational_period_summary(df: pd.DataFrame) -> pd.DataFrame:
    if (
        df.empty
        or "delay_seconds" not in df.columns
        or "operational_period" not in df.columns
    ):
        return pd.DataFrame()

    group_cols = ["service_date", "route_id", "operational_period"]

    return aggregate_delay(df, group_cols)


def make_stop_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "delay_seconds" not in df.columns or "stop_id" not in df.columns:
        return pd.DataFrame()

    if df["stop_id"].isna().all():
        return pd.DataFrame()

    if "record_type" in df.columns:
        df = df[df["record_type"].isin(["stop_prediction", "stop_with_position"])].copy()
    else:
        df = df[df["stop_id"].notna()].copy()

    if df.empty:
        return pd.DataFrame()

    group_cols = ["service_date", "route_id", "stop_id"]

    return aggregate_delay(df, group_cols)


def build_summaries(raw_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "daily_summary": make_daily_route_summary(raw_df),
        "hourly_summary": make_hourly_route_summary(raw_df),
        "stop_summary": make_stop_summary(raw_df),
        "weekday_summary": make_weekday_summary(raw_df),
        "operational_summary": make_operational_period_summary(raw_df),
    }