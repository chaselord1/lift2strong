#!/usr/bin/env python3
"""lift2strong — convert any lifting-app CSV into the Strong export format.

Most lifting apps (Liftoff, Hevy, Gym Log+, LiftShift, ...) can import a Strong CSV, so this is a
universal bridge: point it at whatever CSV your old app produced, tell it which columns are which
(or let it guess), and it writes a Strong-format file.

Strong format (verified against a real Strong export):
    Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,Notes,Workout Notes,RPE
    Date = 'YYYY-MM-DD HH:MM:SS'   Duration = '1h 5m'   numeric N/A = 0   RPE blank
    No unit column: weights are taken in whatever unit the importing app is set to.

Usage:
    python lift2strong.py input.csv [-o strong.csv] [options]

Options:
    --col FIELD=HEADER      Map a field to a column header when auto-detect guesses wrong.
                            Fields: date time workout workout_id duration exercise set side weight
                                    reps distance seconds notes rpe
                            e.g. --col exercise="Movement" --col weight="Load (lb)"
    --names FILE            JSON {"old exercise name": "new name"} applied before writing.
    --bodyweight FILE       Text file, one exercise per line, written with weight 0
                            (for apps that log bodyweight-inclusive load).
    --ignore FILE           Text file, one exercise per line, dropped entirely (PR summaries etc.).
    --no-merge-sides        Keep R/L rows as separate sets instead of merging equal pairs.
    --default-time HH:MM    Clock time for rows that have a date but no time (default 09:00).
                            Extra workouts on the same day get +1 minute each.
    --keep-empty-sets       Keep rows with no set number (default: dropped as non-set rows).

Only the standard library is used.
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime

FIELDS = ["date", "time", "workout", "workout_id", "duration", "exercise", "set", "side", "weight",
          "reps", "distance", "seconds", "notes", "rpe"]

# lower-cased header aliases per field; first match wins
ALIASES = {
    "date": ["date", "workout date", "date_iso", "day", "datetime", "start time", "start_time", "started"],
    "time": ["time", "start time", "clock"],
    "workout": ["workout name", "workout", "title", "routine", "session", "name"],
    "workout_id": ["workout id", "workout_id", "session id", "session_id", "id"],
    "duration": ["duration", "total time", "total_time", "workout duration", "length"],
    "exercise": ["exercise name", "exercise", "exercise_name", "movement", "lift", "exercise title"],
    "set": ["set order", "set", "set_order", "set number", "set_number", "set index", "set #"],
    "side": ["side", "arm", "leg", "limb"],
    "weight": ["weight", "weight (lbs)", "weight (lb)", "weight (kg)", "weight_lbs", "weight_kg", "load", "lbs", "kg"],
    "reps": ["reps", "repetitions", "rep", "rep count"],
    "distance": ["distance", "distance (mi)", "distance (km)", "distance_mi", "distance_km", "miles", "km"],
    "seconds": ["seconds", "duration (s)", "time (s)", "set duration", "hold", "elapsed"],
    "notes": ["notes", "note", "comment", "comments"],
    "rpe": ["rpe", "rir", "effort"],
}

DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y",
    "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%Y/%m/%d",
]

NUM = re.compile(r"-?\d+(?:\.\d+)?")
MMSS = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")  # h:mm:ss or mm:ss


def detect_columns(headers, overrides):
    """Return {field: header} using overrides first, then alias matching."""
    low = {h.lower().strip(): h for h in headers}
    cols = {}
    used = set()
    for f, h in overrides.items():
        if h not in headers:
            sys.exit(f"--col {f}={h!r}: no such column. Columns: {headers}")
        cols[f] = h
        used.add(h)
    for f in FIELDS:
        if f in cols:
            continue
        for a in ALIASES[f]:
            h = low.get(a)
            if h and h not in used:
                cols[f] = h
                used.add(h)
                break
    return cols


def parse_date(s, default_time):
    s = (s or "").strip()
    if not s:
        return None, False
    for fmt in DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt)
            has_time = "%H" in fmt
            if not has_time:
                hh, mm = default_time
                d = d.replace(hour=hh, minute=mm, second=0)
            return d, has_time
        except ValueError:
            pass
    # last resort: pull a YYYY-MM-DD out of the string
    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        hh, mm = default_time
        return datetime.strptime(m.group(1), "%Y-%m-%d").replace(hour=hh, minute=mm), False
    return None, False


def num(s):
    m = NUM.search(s or "")
    return m.group(0) if m else "0"


def to_seconds(s):
    """'15:00' -> 900, '1:05:00' -> 3900, '45' -> 45, '1h 5m' -> 3900."""
    s = (s or "").strip()
    if not s:
        return "0"
    m = MMSS.match(s)
    if m:
        h, mi, se = (int(m.group(1) or 0), int(m.group(2)), int(m.group(3)))
        return str(h * 3600 + mi * 60 + se)
    h = re.search(r"(\d+)\s*h", s)
    mi = re.search(r"(\d+)\s*m", s)
    if h or mi:
        return str((int(h.group(1)) if h else 0) * 3600 + (int(mi.group(1)) if mi else 0) * 60)
    return num(s).split(".")[0] if NUM.search(s) else "0"


def strong_duration(s):
    """Pass through '1h 5m' style; convert seconds or h:mm:ss into it."""
    s = (s or "").strip()
    if not s:
        return ""
    if re.search(r"\d+\s*[hm]", s):
        return s
    secs = int(to_seconds(s))
    if secs == 0:
        return ""
    return f"{secs // 3600}h {(secs % 3600) // 60}m" if secs >= 3600 else f"{(secs % 3600) // 60}m"


def read_list(path):
    if not path:
        return set()
    with open(path, encoding="utf-8-sig") as f:
        return {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}


def main():
    ap = argparse.ArgumentParser(description="Convert any lifting-app CSV into Strong format.")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--col", action="append", default=[], metavar="FIELD=HEADER")
    ap.add_argument("--names", help="JSON rename map")
    ap.add_argument("--bodyweight", help="exercises written with weight 0, one per line")
    ap.add_argument("--ignore", help="exercises to drop, one per line")
    ap.add_argument("--no-merge-sides", action="store_true")
    ap.add_argument("--default-time", default="09:00")
    ap.add_argument("--keep-empty-sets", action="store_true")
    args = ap.parse_args()

    overrides = {}
    for c in args.col:
        if "=" not in c:
            sys.exit(f"--col expects FIELD=HEADER, got {c!r}")
        f, h = c.split("=", 1)
        if f not in FIELDS:
            sys.exit(f"unknown field {f!r}; fields: {FIELDS}")
        overrides[f] = h
    hh, mm = (int(x) for x in args.default_time.split(":"))
    names = json.load(open(args.names, encoding="utf-8-sig")) if args.names else {}
    bodyweight = read_list(args.bodyweight)
    ignore = read_list(args.ignore)

    with open(args.input, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("input has no rows")
    cols = detect_columns(list(rows[0].keys()), overrides)
    for req in ("date", "exercise"):
        if req not in cols:
            sys.exit(f"could not find a {req} column; pass --col {req}=HEADER. Columns: {list(rows[0].keys())}")
    print("column mapping:", {k: v for k, v in cols.items()}, file=sys.stderr)

    def g(r, field):
        h = cols.get(field)
        return (r.get(h) or "").strip() if h else ""

    # ---- group rows into workouts, keeping file order ----
    workouts = OrderedDict()  # key -> dict(date, name, duration, exercises: OrderedDict(ex -> [rows]))
    skipped_date = 0
    for r in rows:
        ex = g(r, "exercise")
        if not ex or ex in ignore:
            continue
        # group by the ORIGINAL name; renaming happens at output so two source exercises that map to
        # the same target name keep their own R/L pairing and set numbering
        d, _ = parse_date(g(r, "date") + (" " + g(r, "time") if g(r, "time") and cols.get("time") != cols.get("date") else ""), (hh, mm))
        if d is None:
            d, _ = parse_date(g(r, "date"), (hh, mm))
        if d is None:
            skipped_date += 1
            continue
        key = g(r, "workout_id") or (d.strftime("%Y-%m-%d %H:%M") + "|" + g(r, "workout"))
        w = workouts.setdefault(key, dict(date=d, name=g(r, "workout"), duration=g(r, "duration"), exercises=OrderedDict()))
        w["exercises"].setdefault(ex, []).append(r)

    # ---- stamp same-day workouts 1 minute apart when the source had no clock time ----
    by_min = defaultdict(list)
    for k, w in workouts.items():
        by_min[w["date"].strftime("%Y-%m-%d %H:%M")].append(k)
    for keys in by_min.values():
        for i, k in enumerate(keys):
            if i:
                workouts[k]["date"] = workouts[k]["date"].replace(minute=(workouts[k]["date"].minute + i) % 60)

    out = []
    for w in workouts.values():
        base = [w["date"].strftime("%Y-%m-%d %H:%M:%S"), w["name"], strong_duration(w["duration"])]
        for ex_src, exrows in w["exercises"].items():
            ex = names.get(ex_src, ex_src)
            # bucket by set number (or sequential if none); a set number that already exists in the
            # current block starts a new block (same exercise logged twice in one workout)
            blocks, buckets = [], OrderedDict()
            seq = 0
            for r in exrows:
                s = g(r, "set")
                if not s and not args.keep_empty_sets and cols.get("set"):
                    continue  # label-less rows (summaries) when the file does have set numbers
                if not s:
                    seq += 1
                    s = str(seq)
                if s in buckets and len(buckets[s]) >= 2:
                    blocks.append(buckets)
                    buckets = OrderedDict()
                buckets.setdefault(s, []).append(r)
            blocks.append(buckets)
            order = 0
            for _, sides in [(k, v) for b in blocks for k, v in b.items()]:
                if len(sides) == 2 and not args.no_merge_sides:
                    a, b = sides
                    if {g(a, "side").upper()[:1], g(b, "side").upper()[:1]} == {"R", "L"} and \
                            num(g(a, "weight")) == num(g(b, "weight")) and num(g(a, "reps")) == num(g(b, "reps")):
                        sides = [a]
                for r in sides:
                    order += 1
                    weight = "0" if ex in bodyweight else num(g(r, "weight"))
                    reps = num(g(r, "reps"))
                    secs = to_seconds(g(r, "seconds"))
                    dist = num(g(r, "distance"))
                    note = g(r, "notes")
                    if len(sides) > 1 and g(r, "side"):
                        note = (note + " " if note else "") + f"{g(r, 'side')} side"
                    out.append(base + [ex, order, weight, reps, dist, secs, note, "", g(r, "rpe")])

    out_path = args.output or os.path.splitext(args.input)[0] + "_strong.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["Date", "Workout Name", "Duration", "Exercise Name", "Set Order", "Weight", "Reps",
                     "Distance", "Seconds", "Notes", "Workout Notes", "RPE"])
        wr.writerows(out)
    print(f"{len(out)} set rows across {len(workouts)} workouts -> {out_path}"
          + (f"  ({skipped_date} rows skipped: unparseable date)" if skipped_date else ""), file=sys.stderr)


if __name__ == "__main__":
    main()
