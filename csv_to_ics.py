#!/usr/bin/env python3
"""Convert a CSV file of events into an .ics calendar file."""

import argparse
import csv
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ALIASES = {
    "summary": ["summary", "subject", "title", "name", "event"],
    "start": ["start", "start date", "startdate", "dtstart", "begin"],
    "start_date": ["start date", "startdate", "start_date", "dtstart date"],
    "start_time": ["start time", "starttime", "start_time"],
    "end": ["end", "end date", "enddate", "dtend", "finish"],
    "end_date": ["end date", "enddate", "end_date", "dtend date"],
    "end_time": ["end time", "endtime", "end_time"],
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
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %I:%M:%S %p",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d %I:%M %p",
        "%Y/%m/%d %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %I:%M %p",
        "%d/%m/%Y %I:%M:%S %p",
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


def parse_time(raw_value: Optional[str]) -> Optional[time]:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unsupported time value: {raw_value!r}")


def combine_date_and_time(date_value: Optional[object], time_value: Optional[time]) -> Optional[object]:
    if date_value is None:
        return None
    if isinstance(date_value, datetime):
        return date_value
    if isinstance(date_value, date) and time_value is not None:
        return datetime.combine(date_value, time_value)
    return date_value


def format_ics_datetime(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
            return value.strftime("%Y%m%dT%H%M%SZ")
        return value.strftime("%Y%m%dT%H%M%S")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    raise TypeError(f"Unsupported value type: {type(value)!r}")


def format_ics_property(name: str, value: object) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return f"{name};VALUE=DATE:{format_ics_datetime(value)}"
    return f"{name}:{format_ics_datetime(value)}"


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
    description = row.get(mapping["description"], "") if mapping["description"] else ""
    location = row.get(mapping["location"], "") if mapping["location"] else ""
    uid = row.get(mapping["uid"], "") if mapping["uid"] else f"event-{index + 1}"

    start_date_raw = row.get(mapping["start_date"], "") if mapping.get("start_date") else ""
    start_time_raw = row.get(mapping["start_time"], "") if mapping.get("start_time") else ""
    start_raw = row.get(mapping["start"], "") if mapping.get("start") else ""

    end_date_raw = row.get(mapping["end_date"], "") if mapping.get("end_date") else ""
    end_time_raw = row.get(mapping["end_time"], "") if mapping.get("end_time") else ""
    end_raw = row.get(mapping["end"], "") if mapping.get("end") else ""

    if start_date_raw:
        start_date_value, _ = parse_value(start_date_raw)
        start_time_value = parse_time(start_time_raw) if start_time_raw else None
        start_value = combine_date_and_time(start_date_value, start_time_value)
    elif start_raw:
        start_value, _ = parse_value(start_raw)
    else:
        raise ValueError(f"Row {index + 2}: missing or invalid start date")

    if start_value is None:
        raise ValueError(f"Row {index + 2}: missing or invalid start date")

    if end_date_raw:
        end_date_value, _ = parse_value(end_date_raw)
        end_time_value = parse_time(end_time_raw) if end_time_raw else None
        end_value = combine_date_and_time(end_date_value, end_time_value)
    elif end_raw:
        end_value, _ = parse_value(end_raw)
    else:
        if isinstance(start_value, datetime):
            end_value = start_value + timedelta(hours=1)
        elif isinstance(start_value, date):
            end_value = start_value + timedelta(days=1)
        else:
            end_value = start_value

    lines = [
        "BEGIN:VEVENT",
        f"UID:{escape_text(uid)}",
        f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
        format_ics_property("DTSTART", start_value),
        format_ics_property("DTEND", end_value),
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
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CSV to ICS Converter//EN",
            "CALSCALE:GREGORIAN",
        ]
        lines.extend(events)
        lines.append("END:VCALENDAR")
        handle.write("\r\n".join(lines) + "\r\n")


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
