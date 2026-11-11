"""Streaming Apple Health export parser; run in the network-disabled Python worker."""
from __future__ import annotations

import hashlib
import io
import math
import zipfile
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from defusedxml.ElementTree import iterparse

METRICS = {
    "HKQuantityTypeIdentifierStepCount": ("steps", "count", "sum"),
    "HKQuantityTypeIdentifierHeartRate": ("heart_rate", "count/min", "mean"),
    "HKQuantityTypeIdentifierRestingHeartRate": ("resting_heart_rate", "count/min", "mean"),
    "HKQuantityTypeIdentifierActiveEnergyBurned": ("active_energy", "kcal", "sum"),
    "HKQuantityTypeIdentifierDistanceWalkingRunning": ("distance", "km", "sum"),
}
MAX_XML = 256_000_000


class ExportLimitError(ValueError):
    pass


class LimitedReader:
    def __init__(self, source):
        self.source, self.size = source, 0

    def read(self, size=-1):
        data = self.source.read(min(size if size >= 0 else 65536, 65536))
        self.size += len(data)
        if self.size > MAX_XML:
            raise ValueError("Apple Health XML exceeds 256 MB.")
        return data


def health_date(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise ValueError("Health records require dates with a time zone.") from None


def parse_export(raw, timezone, days=90):
    if not 1 <= days <= 365 or not raw or len(raw) > 64_000_000:
        raise ValueError("Choose 1–365 days and an export of at most 64 MB.")
    archive = None
    try:
        if raw.startswith(b"PK"):
            archive = zipfile.ZipFile(io.BytesIO(raw))
            matches = [x for x in archive.infolist() if x.filename in {"export.xml", "apple_health_export/export.xml"}]
            if len(matches) != 1 or len(archive.infolist()) > 10000:
                raise ValueError("ZIP must contain exactly one Apple Health export.xml.")
            entry = matches[0]
            if entry.file_size > MAX_XML or entry.flag_bits & 1:
                raise ValueError("Encrypted or oversized Apple Health export.")
            stream = archive.open(entry)
        else:
            stream = io.BytesIO(raw)
        with stream:
            return aggregate(LimitedReader(stream), timezone, days)
    except (zipfile.BadZipFile, KeyError):
        raise ValueError("Invalid Apple Health export archive.") from None
    finally:
        if archive:
            archive.close()


def aggregate(stream, timezone, days):
    zone = ZoneInfo(timezone)
    today = datetime.now(zone).date()
    first = today - timedelta(days=days - 1)
    groups, sleep, seen = {}, {}, set()
    skipped = samples = 0
    root = None

    def add(day, metric, source, unit, aggregation, value):
        key = (str(day), metric, source, unit)
        if key not in groups:
            if len(groups) >= 12000:
                raise ExportLimitError("Too many daily health groups; choose a shorter period.")
            groups[key] = {"date": str(day), "metric": metric, "source": source, "unit": unit,
                           "aggregation": aggregation, "sum": 0.0, "count": 0,
                           "min": value, "max": value}
        row = groups[key]
        row["sum"] += value
        row["count"] += 1
        row["min"], row["max"] = min(row["min"], value), max(row["max"], value)

    for event, elem in iterparse(stream, events=("start", "end"), forbid_entities=True, forbid_external=True):
        if root is None:
            root = elem
            if root.tag != "HealthData":
                raise ValueError("This is not an Apple Health export.")
        if event != "end" or elem.tag not in {"Record", "Workout"}:
            continue
        samples += 1
        if samples > 1_000_000:
            raise ValueError("Export exceeds one million records; choose a smaller export.")
        attrs = elem.attrib
        source = attrs.get("sourceName", "Unknown source")[:100]
        kind = attrs.get("type", "")
        try:
            start = health_date(attrs.get("startDate", "")).astimezone(zone)
            end = health_date(attrs.get("endDate", attrs.get("startDate", ""))).astimezone(zone)
            if end < start or end.date() < first or start.date() > today:
                skipped += 1
                continue
            signature = hashlib.blake2b(repr(sorted(attrs.items())).encode(), digest_size=16).digest()
            if signature in seen:
                skipped += 1
                continue
            seen.add(signature)
            if kind == "HKCategoryTypeIdentifierSleepAnalysis":
                value = attrs.get("value", "")
                if value not in {"HKCategoryValueSleepAnalysisAsleep", "HKCategoryValueSleepAnalysisAsleepUnspecified",
                                 "HKCategoryValueSleepAnalysisAsleepCore", "HKCategoryValueSleepAnalysisAsleepDeep",
                                 "HKCategoryValueSleepAnalysisAsleepREM"}:
                    continue
                current = max(start, datetime.combine(first, datetime.min.time(), zone))
                end = min(end, datetime.combine(today + timedelta(days=1), datetime.min.time(), zone))
                while current < end:
                    stop = min(end, datetime.combine(current.date() + timedelta(days=1), datetime.min.time(), zone))
                    sleep.setdefault((str(current.date()), source), []).append((current.timestamp(), stop.timestamp()))
                    current = stop
            elif elem.tag == "Workout":
                minutes = (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 60
                if first <= start.date() <= today and 0 <= minutes <= 1440:
                    add(start.date(), "workout_minutes", source, "min", "sum", minutes)
            elif kind in METRICS and first <= start.date() <= today:
                metric, unit, method = METRICS[kind]
                value = float(attrs.get("value", "nan"))
                actual_unit = attrs.get("unit", "")
                if metric == "distance" and actual_unit == "m":
                    value, actual_unit = value / 1000, "km"
                if metric == "active_energy" and actual_unit == "kJ":
                    value, actual_unit = value / 4.184, "kcal"
                if not math.isfinite(value) or not 0 <= value <= 1_000_000_000 or actual_unit != unit:
                    skipped += 1
                    continue
                add(start.date(), metric, source, unit, method, value)
        except ExportLimitError:
            raise
        except (ValueError, OverflowError):
            skipped += 1
        finally:
            elem.clear()
            root.clear()
    for (day, source), intervals in sleep.items():
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        add(day, "sleep_minutes", source, "min", "sum", sum(b - a for a, b in merged) / 60)
    rows = []
    for key in sorted(groups):
        row = groups[key]
        total = row.pop("sum")
        row["value"] = round(total / row["count"] if row["aggregation"] == "mean" else total, 3)
        row["min"], row["max"] = round(row["min"], 3), round(row["max"], 3)
        rows.append(row)
    if not rows:
        raise ValueError("No supported health records in the selected period.")
    return {"days": days, "first_date": str(first), "last_date": str(today), "rows": rows,
            "records_scanned": samples, "records_skipped": skipped,
            "warnings": ["Daily values are separated by source; overlapping devices/apps must not be added together.",
                         "Missing records are unknown, not zero. Summaries describe recorded data, not diagnoses."]}
