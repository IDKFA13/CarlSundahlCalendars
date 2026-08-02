#!/usr/bin/env python3
"""Convert a CSV file of events into an .ics calendar file."""

import argparse
import csv
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ALIASES = {
    "summary": ["summary", "subject", "title", "name", "event"],
    "start": ["start", "start date", "startdate", "dtstart", "begin", "start time"],
    "end": ["end", "end date", "enddate", "dtend", "finish", "end time"],
    "description": ["description", "notes", "details", "body"],
    "location": ["location", "place", "venue"],
    "uid": ["uid", "id", "event id", "event_id"],
}


def escape_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "\\n")


def parse_value(raw_value: Optional[str]) -> Tuple[Optional[object], Optional[str]]:
    if raw_value is None:
        return None, None
    text = str(raw_value).strip()
    if not text:
        return None, None

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text), "DATE"

    date_only_formats = {"%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"}

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt in date_only_formats:
                return parsed.date(), "DATE"
            return parsed, "DATETIME"
        except ValueError:
            continue

    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt, "DATETIME"
    except ValueError as exc:
        raise ValueError(f"Unsupported date value: {raw_value!r}") from exc


def format_ics_datetime(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
            return value.strftime("%Y%m%dT%H%M%SZ")
        return value.strftime("%Y%m%dT%H%M%S")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    raise TypeError(f"Unsupported value type: {type(value)!r}")


def find_column(fieldnames: List[str], aliases: List[str]) -> Optional[str]:
    lowered = {name.strip().lower(): name for name in fieldnames}
    for alias in aliases:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    return None


def resolve_mapping(fieldnames: List[str], explicit_columns: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
    mapping: Dict[str, Optional[str]] = {}
    for key, aliases in ALIASES.items():
        explicit = explicit_columns.get(key)
        if explicit:
            mapping[key] = explicit
        else:
            mapping[key] = find_column(fieldnames, aliases)
    return mapping


def build_event(row: Dict[str, str], index: int, mapping: Dict[str, Optional[str]]) -> str:
    summary = row.get(mapping["summary"], "") if mapping["summary"] else f"Event {index + 1}"
    start_raw = row.get(mapping["start"], "") if mapping["start"] else ""
    end_raw = row.get(mapping["end"], "") if mapping["end"] else ""
    description = row.get(mapping["description"], "") if mapping["description"] else ""
    location = row.get(mapping["location"], "") if mapping["location"] else ""
    uid = row.get(mapping["uid"], "") if mapping["uid"] else f"event-{index + 1}"

    start_value, _ = parse_value(start_raw) if start_raw else (None, None)
    if start_value is None:
        raise ValueError(f"Row {index + 2}: missing or invalid start date")

    if end_raw:
        end_value, _ = parse_value(end_raw)
    else:
        end_value = start_value

    lines = [
        "BEGIN:VEVENT",
        f"UID:{escape_text(uid)}",
        f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{format_ics_datetime(start_value)}",
        f"DTEND:{format_ics_datetime(end_value)}",
        f"SUMMARY:{escape_text(summary)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{escape_text(description)}")
    if location:
        lines.append(f"LOCATION:{escape_text(location)}")
    lines.append("END:VEVENT")
    return "\n".join(lines)


def convert_csv_to_ics(input_path: Path, output_path: Path, explicit_columns: Dict[str, Optional[str]], delimiter: str) -> None:
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("The CSV file appears to be empty or missing headers")

        mapping = resolve_mapping(reader.fieldnames, explicit_columns)

        events = []
        for index, row in enumerate(reader):
            if not any((value or "").strip() for value in row.values()):
                continue
            events.append(build_event(row, index, mapping))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("BEGIN:VCALENDAR\n")
        handle.write("VERSION:2.0\n")
        handle.write("PRODID:-//CSV to ICS Converter//EN\n")
        for event in events:
            handle.write(event + "\n")
        handle.write("END:VCALENDAR\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a CSV file with events into an .ics calendar file")
    parser.add_argument("input_csv", help="Path to the input CSV file")
    parser.add_argument("output_ics", help="Path to the output .ics file")
    parser.add_argument("--summary-column", dest="summary_column")
    parser.add_argument("--start-column", dest="start_column")
    parser.add_argument("--end-column", dest="end_column")
    parser.add_argument("--description-column", dest="description_column")
    parser.add_argument("--location-column", dest="location_column")
    parser.add_argument("--uid-column", dest="uid_column")
    parser.add_argument("--delimiter", default=",", help="CSV delimiter (default: comma)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_csv).expanduser().resolve()
    output_path = Path(args.output_ics).expanduser().resolve()

    explicit_columns = {
        "summary": args.summary_column,
        "start": args.start_column,
        "end": args.end_column,
        "description": args.description_column,
        "location": args.location_column,
        "uid": args.uid_column,
    }

    convert_csv_to_ics(input_path, output_path, explicit_columns, args.delimiter)
    print(f"Created calendar file: {output_path}")


if __name__ == "__main__":
    main()
