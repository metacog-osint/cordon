# Cordon method (doctrine summary)

Cordon collects official warnings that tell people to stay away: US travel advisories and embassy departure status,
EASA conflict-zone bulletins for aircraft, and NGA's navigational warnings for ships. It states them in the terms of
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

## Anomaly versus warning
Everything Cordon publishes is a measurement of what an authority said (kind observation). A level change or a
departure order in the last 30 days is an anomaly against the previous value. Cordon makes no judgment of its own;
those come through warning problem CD-WP-1 and through Verdict, which scores forecasts of renewals and changes.

## Places
Countries are drawn at a label point inside the country (the kit's Natural Earth points), not at the capital. Gaza and
the West Bank, which State files under Israel's code, are placed by hand. NGA positions are drawn as written.

## Gaps and no data
A source that fails keeps its last good data and is marked in `data/health.json`; the page shows its age. Embassy
alert feeds were down on 31 Oct 2026 ("Technical Difficulties"), so that layer may be empty.
