#!/usr/bin/env python3

"""
Infer a rough schema from InfluxDB line protocol exports.

This script reads one or more .lp files and extracts:

- measurement names
- tag keys
- field keys
- sampled row counts

It is intended for schema discovery from exports created with:

    influxd inspect export-lp

Example usage:

    python3 scripts/infer_influx_schema.py schema_exports/*.lp

Write output to a file:

    python3 scripts/infer_influx_schema.py schema_exports/*.lp \
      > schema_exports/inferred_schema.txt
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Iterable


Schema = dict[str, dict[str, set[str] | int]]


def split_unescaped(text: str, delimiter: str) -> list[str]:
    """
    Split a string on delimiter characters that are not escaped.

    Influx line protocol allows escaped commas, spaces, and equals signs
    in measurement names, tag keys, tag values, and field keys.

    Example:

        "bus\\,stop,route=red" split on comma becomes:

        ["bus\\,stop", "route=red"]
    """
    parts: list[str] = []
    buffer: list[str] = []
    escaped = False

    for char in text:
        if escaped:
            buffer.append(char)
            escaped = False
        elif char == "\\":
            buffer.append(char)
            escaped = True
        elif char == delimiter:
            parts.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)

    parts.append("".join(buffer))
    return parts


def split_first_unescaped_space(line: str) -> tuple[str, str]:
    """
    Split line protocol into the part before the first unescaped space
    and the rest.

    Line protocol is broadly:

        measurement,tags fields timestamp
    """
    escaped = False

    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == " ":
            return line[:index], line[index + 1 :]

    return line, ""


def unescape_identifier(text: str) -> str:
    """
    Make escaped line protocol identifiers easier to read.
    """
    return (
        text.replace("\\ ", " ")
        .replace("\\,", ",")
        .replace("\\=", "=")
        .replace("\\\\", "\\")
    )


def parse_line_protocol_schema(line: str) -> tuple[str, set[str], set[str]] | None:
    """
    Parse one line of Influx line protocol and return:

        measurement, tag_keys, field_keys

    This does not parse values. It only extracts schema-level names.
    """
    line = line.strip()

    if not line or line.startswith("#"):
        return None

    key_part, rest = split_first_unescaped_space(line)

    if not key_part or not rest:
        return None

    field_part, _timestamp_part = split_first_unescaped_space(rest)

    key_bits = split_unescaped(key_part, ",")
    if not key_bits:
        return None

    measurement = unescape_identifier(key_bits[0])

    tag_keys: set[str] = set()
    for tag_assignment in key_bits[1:]:
        if "=" not in tag_assignment:
            continue

        tag_key, _tag_value = tag_assignment.split("=", 1)
        tag_keys.add(unescape_identifier(tag_key))

    field_keys: set[str] = set()
    for field_assignment in split_unescaped(field_part, ","):
        if "=" not in field_assignment:
            continue

        field_key, _field_value = field_assignment.split("=", 1)
        field_keys.add(unescape_identifier(field_key))

    return measurement, tag_keys, field_keys


def infer_schema(paths: Iterable[Path]) -> Schema:
    schema: Schema = defaultdict(
        lambda: {
            "tags": set(),
            "fields": set(),
            "rows": 0,
        }
    )

    for path in paths:
        if not path.exists():
            print(f"WARNING: file not found: {path}")
            continue

        if not path.is_file():
            print(f"WARNING: not a file: {path}")
            continue

        with path.open("r", encoding="utf-8", errors="ignore") as file:
            for line in file:
                parsed = parse_line_protocol_schema(line)

                if parsed is None:
                    continue

                measurement, tag_keys, field_keys = parsed

                schema[measurement]["tags"].update(tag_keys)      # type: ignore[union-attr]
                schema[measurement]["fields"].update(field_keys)  # type: ignore[union-attr]
                schema[measurement]["rows"] += 1                  # type: ignore[operator]

    return schema


def print_schema(schema: Schema) -> None:
    if not schema:
        print("No schema information found.")
        return

    for measurement in sorted(schema):
        info = schema[measurement]

        tags = sorted(info["tags"])      # type: ignore[arg-type]
        fields = sorted(info["fields"])  # type: ignore[arg-type]
        rows = info["rows"]

        print()
        print(f"MEASUREMENT: {measurement}")
        print(f"ROWS SAMPLED: {rows}")

        print("TAGS:")
        if tags:
            for tag in tags:
                print(f"  - {tag}")
        else:
            print("  - none found")

        print("FIELDS:")
        if fields:
            for field in fields:
                print(f"  - {field}")
        else:
            print("  - none found")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Infer measurement, tag, and field schema from InfluxDB line protocol files."
    )

    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="One or more line protocol files, usually *.lp",
    )

    args = parser.parse_args()

    schema = infer_schema(args.files)
    print_schema(schema)


if __name__ == "__main__":
    main()