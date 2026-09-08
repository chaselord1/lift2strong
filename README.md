# lift2strong

Convert **any lifting-app CSV** into the **Strong export format** — the de-facto interchange file that
Liftoff, Hevy, Gym Log+, LiftShift and most other trackers can import ("Import from Strong").

Switching apps and the old one won't export in a format the new one takes? Get its data out as a CSV
by whatever means (built-in export, a scraper, a support request), run it through this, import the result.

- Single file, standard library only, Python 3.8+
- Auto-detects column names; override any of them with `--col`
- Parses the usual date formats (ISO, `MM/DD/YYYY`, `March 1, 2026`, with or without a time)
- Merges paired `R` / `L` rows into one dumbbell set when weight and reps match
- Cardio → `Distance` + `Seconds`; timed sets (`0:45`, `1:05:00`, `45`) → `Seconds`
- Optional rename map, bodyweight list and ignore list as plain config files

## Usage

```bash
python lift2strong.py workouts.csv
# -> workouts_strong.csv
```

It prints the column mapping it guessed. If a guess is wrong, name the column:

```bash
python lift2strong.py hevy.csv --col exercise=exercise_title --col set=set_index --col weight=weight_kg
```

Fields you can map: `date time workout workout_id duration exercise set side weight reps distance seconds notes rpe`.
Only `date` and `exercise` are required; everything else is optional.

### Config files

| Flag | File | Purpose |
|---|---|---|
| `--names` | JSON `{"old": "new"}` | Rename exercises to the names the target app knows (unknown names usually become muscle-less custom exercises). `examples/liftoff_names.json` is a starter for Liftoff. |
| `--bodyweight` | one name per line | Write these with weight 0 — for apps that log bodyweight-inclusive load ("Pull Ups 150 lbs") when the target expects added weight only. |
| `--ignore` | one name per line | Drop these rows entirely (PR summaries some apps emit as pseudo-exercises). |

```bash
python lift2strong.py lifts.csv --names examples/liftoff_names.json --bodyweight examples/bodyweight.txt --ignore examples/ignore.txt
```

Other options: `--no-merge-sides` (keep R/L as separate sets), `--default-time 09:00` (clock time for
date-only rows; extra workouts on the same day get +1 minute), `--keep-empty-sets`.

## Output

```
Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,Notes,Workout Notes,RPE
2026-03-01 17:30:00,Push Day,,Bench Press (Barbell),1,60,10,0,0,,,
```

Dates are `YYYY-MM-DD HH:MM:SS`, duration `1h 5m`, numeric N/A is `0`. The Strong format has **no unit
column** — set the importing app to the unit your numbers are in before importing.

## Notes

- Workouts are grouped by a `workout_id` column if there is one, otherwise by date + workout name.
- Set order restarts at 1 per exercise per workout, as Strong does.
- If a file has set numbers, rows without one are dropped (they're usually summaries); `--keep-empty-sets` keeps them.
