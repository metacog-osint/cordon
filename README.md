# Cordon

**Where governments and aviation and maritime authorities are warning people away, on one map.**
Map: https://cordon.theintelligence.company/ · Feed: https://cordon.theintelligence.company/data/feed.geojson

Cordon collects official warnings every hour, straight from the issuing authorities:

| Source | What it gives | Licence |
|---|---|---|
| US Department of State travel advisories (official JSON) | Level 1 to 4 and the full text for about 218 places | US public domain (seals and logos restricted) |
| Embassy departure status, read from that text | Authorized or ordered departure, suspended operations | as above |
| US embassy alerts (each post's RSS) | Security, demonstration, health and weather alerts | US public domain |
| EASA Conflict Zone Information Bulletins (CSV export) | Airspaces to avoid, with each bulletin's expiry | EASA content, reused with acknowledgement |
| NGA navigational warnings in force (MSI daily lists, or its API when that is current) | Launches, military activity, mines, GNSS trouble and other hazards to ships | US public domain |
| FAA National Airspace System status (the JSON behind nasstatus.faa.gov) | Ground stops, ground delay programs and airport closures in effect, with the FAA's airport coordinates | US Government work (17 U.S.C. 105); the FAA states no licence |
| FAA temporary flight restrictions (tfr.faa.gov list and detail files) | Space launches and recoveries, security, VIP movements, fires and other hazards, with the FAA's own outline and UTC times | US Government work (17 U.S.C. 105); the FAA states no licence |
| Government of Canada travel advice and advisories (open data index) | Canada's level for about 230 places, its regional advisories, and its note of each update | Open Government Licence - Canada |
| UK FCDO foreign travel advice (GOV.UK Content API) | Where the UK advises against all or all but essential travel, and the FCDO's note of each update, for about 226 countries | Open Government Licence v3.0 |

OSAC is not used: its terms bar republishing.

## How it reads the sources

- State's dates do not move when an advisory changes, so Cordon finds revisions by hashing the text.
- State's country codes are mostly FIPS 10-4. Fourteen advisories use ISO or State's own codes (Switzerland comes as
  "SR"), so the title decides for those. Gaza and the West Bank, filed under Israel's code, are placed by hand.
- Departure status has no field. Cordon reads it from the text with a phrase set; "suspended operations" counts only
  when the sentence names the embassy. Every change is flagged for a person to review.
- NGA warnings are plain text. Cordon reads the positions written in them, draws an "area bound by" as a polygon,
  sorts each warning into a category from its wording, and drops self-cancelling notices and in-force lists.
- FAA programs are reported as the FAA lists them, reason included ("wind", "other"); Cordon adds no cause. A ground
  stop is an anomaly when more are in effect at once than Cordon's own 30-day count makes normal, or when the FAA lists
  one against a center or the whole system. ATCSCC advisory text is not read: fly.faa.gov answered "No message" to
  plain requests on 13 Nov 2026.
- TFRs are drawn with the FAA's own outline. A space operations, security or special TFR issued in the last 72 hours
  is an anomaly; the standing statutory TFRs over stadiums and Disney parks never are. Nationwide notices with no area
  are counted in the health block, not listed.
- The FCDO's statements are reported as the FCDO words them; a change in the last 30 days is an anomaly. Cordon does
  not rank them against the State Department's levels. A country's page is read only when the FCDO updates it.
- Canada's levels are reported in Canada's words; a level or regional-advisory change in the last 30 days, or an
  update Canada itself marks as an advisory change, is an anomaly. Editorial changes and updates to embassy contacts
  alone are not listed as updates.
- A source that stops answering, or whose list has stopped moving, is marked stale in the feed's `health` block and
  on the page. A stale list of NGA warnings is withheld: it reads as no data, never as a quiet sea.

Everything Cordon publishes is a measurement of what an authority said, in The Intelligence Company's feed contract
v2 (`tic-feed/2`). Each item carries its authority's own ladder value (for example `state_travel_advisory:level_4`,
`state_post_posture:ordered_departure`, `easa_czib:active`) and passes the doctrine kit's tradecraft linter before it
is published. Method: `doctrine/method.md`.

## Running it

```
python tools/cordon.py collect   # fetch every source into data/ (a failing source keeps its last good data)
python tools/cordon.py build     # write site/ (map page, feed.geojson, map.json)
python tools/cordon.py check     # the feed passes the doctrine kit's linter; registers are valid
python tests/test_cordon.py
```

Standard-library Python only. `update.yml` runs hourly: collect, commit `data/` when its content changed, build and
publish to GitHub Pages. `data/changes.jsonl` keeps every level, posture and bulletin change, append-only.

Code under the MIT licence. A project of The Intelligence Company.
