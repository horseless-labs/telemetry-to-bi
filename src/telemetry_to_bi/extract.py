import subprocess


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