# arrow-to-strong

Turns workout data scraped from the **Arrow** fitness app into a **Strong-format CSV**, which
**Liftoff** (and most other lifting apps) can import via "Import from Strong".

Arrow has no export. The input CSVs here come from a separate adb/uiautomator scraper that reads
Arrow's workout-history screens off an Android phone and writes:

- `arrow_workouts.csv` — one row per workout (id, date, name, total time, volume)
- `arrow_lifts.csv` — one row per set, per side (`R`/`L` for dumbbell work)
- `arrow_cardio.csv` — distance / time rows for cardio entries

## Usage

```bash
python to_strong.py /path/to/folder-with-arrow-csvs
# -> arrow_strong_import.csv in that folder
```

## What it does

- Writes the Strong header `Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,Notes,Workout Notes,RPE`
  (verified against a real Strong export). Dates are `YYYY-MM-DD HH:MM:SS`; Arrow has no clock time, so
  every workout is stamped 09:00 (+1 min per extra workout that day).
- Merges Arrow's `R`/`L` rows into one set when weight and reps match (a two-dumbbell set); keeps them
  as two sets, with a side note, when they differ.
- Maps cardio to `Distance` + `Seconds`; timed sets (planks etc.) to `Seconds`.
- Drops Arrow's `PRs` / `Timed PRs` / `Activity PRs` highlight blocks (they duplicate real sets).
- `NAME_MAP` renames the Arrow exercise names Liftoff's importer doesn't recognize to Liftoff's own names,
  so they get muscle data instead of becoming custom exercises.
- `BODYWEIGHT` lists bodyweight-based exercises written with weight 0 (Arrow shows bodyweight-inclusive load).

Edit `NAME_MAP` / `BODYWEIGHT` for your own exercise names. No dependencies beyond the standard library.
