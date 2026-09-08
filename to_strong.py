"""Convert the Arrow scrape CSVs into a Strong-format CSV that Liftoff's 'Import from Strong' accepts.

Strong format (verified against a real export):
  Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,Notes,Workout Notes,RPE
  Date = 'YYYY-MM-DD HH:MM:SS', Duration = '1h 5m', numeric N/A = 0, RPE blank. No unit column -> lbs assumed.
Arrow R/L pairs with equal weight+reps collapse to one set (a two-dumbbell set); unequal pairs stay as two sets.
"""
import csv, os, re, sys
from collections import defaultdict, OrderedDict

D = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()  # folder holding the arrow_*.csv files
# every bodyweight-based move (Arrow logs them as bodyweight + added, ~140-155 = Chase's BW) -> weight 0 (Chase 2026-09-08)
# names here are post-NAME_MAP
BODYWEIGHT = {"Dips", "Pull Ups", "Push Ups", "Muscle Up", "Hanging Knee Raise", "Decline Sit Up", "Decline Oblique Situp",
              "Sissy Squats", "Scapular Pulls", "Planks", "Handstand",
              "Chin Up", "Wide Grip Pull Up", "Neutral Grip Pull Ups", "Incline Push Up", "Tricep Dips", "Pistol Squat",
              "Bodyweight Squat", "Sit Ups", "Russian Twist", "Side Crunch", "Calf Raises", "Standing Calf Raise",
              "Dumbbell Calf Raise"}
# Arrow names Liftoff's Strong importer did not recognize (became muscle-less custom exercises on the 2026-09-08 import)
# -> Liftoff's own exercise names, found via its library search.
NAME_MAP = {
    "Barbell Forearm Curl Behind the Back": "Wrist Curl",
    "behind the back cable lateral raise": "Cable Lateral Raise",
    "Body Weight Squat": "Bodyweight Squat",
    "Cable Diverging Lat Pulldown": "Lat Pulldown",
    "Cable Lat Pull Through": "Straight Arm Pulldown",
    "Cable Seated Lateral Pull Down": "Lat Pulldown",
    "Decline Oblique Situp": "Side Crunch",
    "Dumbbell Calf Raises": "Dumbbell Calf Raise",
    "Dumbbell Low to High Chest Fly": "Dumbbell Fly",
    "Dumbbell Romanian Deadlift (RDL)": "Dumbbell Romanian Deadlift",
    "Inclined Leg Press Machine": "Sled Leg Press",
    "Rear Deltoid Fly Machine": "Machine Reverse Fly",
    "Standing Leg Curl Machine": "Standing Leg Curl",
}
OUT = os.path.join(D, "arrow_strong_import.csv")


def rows(name):
    p = os.path.join(D, name)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def secs(t):
    parts = [int(x) for x in re.findall(r"\d+", t)]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


def num(s):
    m = re.search(r"[\d.]+", s or "")
    return m.group(0) if m else "0"


workouts = {w["workout_id"]: w for w in rows("arrow_workouts.csv")}
lifts, cardio = rows("arrow_lifts.csv"), rows("arrow_cardio.csv")

# stable per-workout clock: 09:00 + 1 min per extra workout on the same day (first-scraped = most recent)
per_day = defaultdict(list)
for wid, w in workouts.items():
    per_day[w["date_iso"]].append(wid)
stamp = {}
for day, ids in per_day.items():
    for i, wid in enumerate(reversed(ids)):
        stamp[wid] = f"{day} 09:{i:02d}:00"

out = []
# lifts: group by workout -> exercise (in scrape order) -> set number -> sides
by_w = OrderedDict()
for r in lifts:
    if r["exercise"] in ("PRs", "Timed PRs", "Activity PRs") or r["set"] == "":
        continue  # Arrow's PR-highlight blocks: duplicates of real sets, not exercises
    by_w.setdefault(r["workout_id"], OrderedDict()).setdefault(r["exercise"], OrderedDict()).setdefault(r["set"], []).append(r)
for wid, exs in by_w.items():
    w = workouts.get(wid, {})
    base = [stamp.get(wid, w.get("date_iso", "") + " 09:00:00"), w.get("name", "Freestyle"), w.get("total_time", "")]
    for ex, sets in exs.items():
        ex = NAME_MAP.get(ex, ex)
        order = 0
        for _, sides in sets.items():
            if len(sides) == 2 and {s["side"] for s in sides} == {"R", "L"} and sides[0]["weight"] == sides[1]["weight"] and sides[0]["reps"] == sides[1]["reps"]:
                sides = [sides[0]]
            for s in sides:
                order += 1
                note = f"{s['side']} side" if len(sides) > 1 and s["side"] else ""
                tm = re.search(r"\b(\d{1,2}):(\d{2})\b", s.get("raw", "")) if not s["reps"] else None
                seconds = str(int(tm.group(1)) * 60 + int(tm.group(2))) if tm else "0"  # timed set (planks etc.)
                # Arrow shows bodyweight-inclusive load for these; Chase 2026-09-08: import them all as 0 (unweighted)
                weight = "0" if ex in BODYWEIGHT else (num(s["weight"]) if s["weight"] else "0")
                out.append(base + [ex, order, weight, num(s["reps"]) if s["reps"] else "0", "0", seconds, note, "", ""])

# cardio: one set per exercise with Distance + Seconds
by_c = OrderedDict()
n = defaultdict(int)
for r in cardio:  # rows come as Distance then Time per session; a workout can hold 2+ sessions of one exercise
    k = (r["workout_id"], r["exercise"])
    if r["field"] == "Distance" or n[k] == 0:
        n[k] += 1
    by_c.setdefault((k[0], k[1], n[k]), {})[r["field"]] = r["value"]
for (wid, ex, _), f in by_c.items():
    w = workouts.get(wid, {})
    base = [stamp.get(wid, w.get("date_iso", "") + " 09:00:00"), w.get("name", "Freestyle"), w.get("total_time", "")]
    out.append(base + [ex, 1, "0", "0", num(f.get("Distance", "0")), str(secs(f.get("Time", "0"))), "", "", ""])

out.sort(key=lambda r: (r[0], by_w and 0))  # keep date order; within a workout keep insertion order (stable sort)
with open(OUT, "w", newline="", encoding="utf-8") as f:
    wr = csv.writer(f)
    wr.writerow(["Date", "Workout Name", "Duration", "Exercise Name", "Set Order", "Weight", "Reps", "Distance", "Seconds", "Notes", "Workout Notes", "RPE"])
    wr.writerows(out)
print(f"{len(out)} set rows across {len(workouts)} workouts -> {OUT}")
