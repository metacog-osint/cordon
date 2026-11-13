# Cordon method (doctrine summary)

Cordon collects official warnings that tell people to stay away: US travel advisories and embassy departure status,
EASA conflict-zone bulletins for aircraft, NGA's navigational warnings for ships, and the FAA's ground stops, ground
delay programs and airport closures. It states them in the terms of
The Intelligence Company's doctrine kit (`doctrine/kit/`).

## What it collects (hourly, GitHub Actions)
- **State Department travel advisories**, from State's official JSON: level 1 to 4 and the full text for about 218
  places. State's dates do not move when the text changes, so a revision is found by hashing the text.
- **Departure status** (authorized or ordered departure, suspended operations): there is no field, so Cordon reads it
  from the advisory text with a phrase set. "Suspended operations" counts only when the sentence names the embassy.
  Every change is flagged for a person to review before it counts.
- **US embassy alerts**, from each post's RSS feed, for every level 3 and 4 country plus a fixed list.
- **EASA Conflict Zone Information Bulletins**: number, revision, status and validity date.
- **NGA navigational warnings in force**, with positions read from the text and a category from the wording.
- **FAA National Airspace System status** (`nasstatus.faa.gov/api/airport-events`, the JSON behind the FAA's NAS
  status page; keyless): ground stops, ground delay programs and airport closures in effect, with the reason in the
  FAA's own words and UTC start and end times. Each run's count of programs goes to `data/faa_counts.jsonl`.

## Anomaly versus warning
Everything Cordon publishes is a measurement of what an authority said (kind observation). A level change or a
departure order in the last 30 days is an anomaly against the previous value. So is a navigational warning of a
security incident, mines, piracy or GNSS interference issued in the last 72 hours, against the warnings in force
before it; every other warning is routine, and each says whether it is new. An FAA ground stop is an anomaly when
more ground stops are in effect at once than Cordon's own counts make normal (`faa_counts.jsonl`, 30 days: one more
than the 99th percentile, never under 3; a prior of 4 until 72 counts exist), or when the FAA lists it against a
center or the whole system instead of one airport. A single ground stop on a normal day, every ground delay program
and every closure is routine. Cordon reports the reason the FAA lists ("wind", "other") and never infers a cause.
Cordon makes no judgment of its own;
those come through warning problem CD-WP-1 and through Verdict, which scores forecasts of renewals and changes.

## Places
Countries are drawn at a label point inside the country (the kit's Natural Earth points), not at the capital. Gaza and
the West Bank, which State files under Israel's code, are placed by hand. NGA positions are drawn as written. FAA
programs are drawn at the airport coordinates the FAA publishes with them; a program listed against a center or the
whole system is drawn at the US label point.

## Gaps and no data
A source that fails keeps its last good data and is marked in `data/health.json`; the page shows its age. Embassy
alert feeds were down on 31 Oct 2026 ("Technical Difficulties"), so that layer may be empty. FAA programs last hours,
so the FAA list goes stale after 3 hours without a good fetch and is then withheld; from a held list (the latest fetch
failed) a program past its listed end time is dropped.
