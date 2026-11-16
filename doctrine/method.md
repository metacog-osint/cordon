# Cordon method (doctrine summary)

Cordon collects official warnings that tell people to stay away: US travel advisories and embassy departure status,
the UK's, Canada's and New Zealand's travel advice, CDC's travel health notices, EASA conflict-zone bulletins and the FAA's flight prohibitions and advisories for foreign airspace for aircraft, NGA's navigational warnings for ships, and
the FAA's ground stops, ground delay programs, airport closures and temporary flight restrictions. It states them in the terms of
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
- **UK FCDO foreign travel advice** (GOV.UK Content API, keyless, Open Government Licence v3.0): for about 226
  countries, the FCDO's "advise against" statements (all travel or all but essential travel, to parts or the whole
  country) and its own one-line note of each update. A country's page is read only when the FCDO updates it.
- **FAA temporary flight restrictions** (`tfr.faa.gov`, keyless): the list, and for each TFR its NOTAM text, UTC
  times, floor and ceiling, and the FAA's own outline. Each detail file is read once per NOTAM number.
- **FAA Prohibitions, Restrictions and Notices** (`faa.gov/air_traffic/publications/us_restrictions`, one page,
  keyless; a US Government work, as Cordon reads it, since the FAA states no licence there): for each country or
  region the FAA lists, its Special Federal Aviation Regulations (prohibitions) and its KICZ security NOTAMs
  (prohibitions, advisories of potentially hazardous airspace, and pointers to an SFAR), each with the FAA's own
  title, document and the FIR codes it names; FAA background notices are kept as links. Routing rules for US
  territory, CFR sections, ICAO letters and DOT or OFAC notices on the page are not read. The page gives no dates.
- **Government of Canada travel advice and advisories** (`data.international.gc.ca` open data, keyless, Open
  Government Licence - Canada): for about 230 places, Canada's level (exercise normal security precautions, a high
  degree of caution, avoid non-essential travel, avoid all travel), whether it has regional advisories, and its own
  label and one-line note of each update. One file a run.
- **New Zealand SafeTravel travel advice** (`safetravel.govt.nz/destinations`, keyless; Crown copyright under CC BY
  4.0, credited to the Ministry of Foreign Affairs and Trade): for about 222 destinations, New Zealand's level (no
  advice level, exercise normal safety and security precautions, exercise increased caution, avoid non-essential
  travel, do not travel) and the day of its latest update, from the list the destinations page carries; and from each
  country's page, MFAT's note under its headline, which on every page that has one says other levels apply in some
  areas (MFAT words it four ways; the feed title says "other levels apply in some areas" and keeps MFAT's words in
  `measures.regional_note`). A country page is read only when its update day
  moves.
- **CDC travel health notices** (`wwwnc.cdc.gov/travel/rss/notices.xml`, keyless, US public domain; CDC asks for
  credit, a no-endorsement disclaimer and unaltered substance): every notice in force, at CDC's level (1 Practice Usual
  Precautions to 4 Avoid All Travel), with the disease, CDC's summary, the places it names and CDC's date.

## Anomaly versus warning
Everything Cordon publishes is a measurement of what an authority said (kind observation). A level change or a
departure order in the last 30 days is an anomaly against the previous value. So is a navigational warning of a
security incident, mines, piracy, GNSS interference, a launch or a military exercise issued in the last 72 hours,
against the warnings in force
before it; every other warning is routine, and each says whether it is new. An FAA ground stop is an anomaly when
more ground stops are in effect at once than Cordon's own counts make normal (`faa_counts.jsonl`, 30 days: one more
than the 99th percentile, never under 3; a prior of 4 until 72 counts exist), or when the FAA lists it against a
center or the whole system instead of one airport. A single ground stop on a normal day, every ground delay program
and every closure is routine. Cordon reports the reason the FAA lists ("wind", "other") and never infers a cause.
A change of the FCDO's statements for a country in the last 30 days is an anomaly against its previous statements;
countries where the FCDO advises against some travel, or that it updated in the last 72 hours, are listed as routine.
Cordon does not rank the FCDO's statements against the State Department's levels. A TFR for security or a
special notice issued in the last 72 hours is an anomaly against the TFRs listed before it, when it is of some
impact and not a re-issue (since 15 Nov 2026, Tom's request that alerts weigh what a restriction does). Impact is
measured from the FAA's own outline, floor, ceiling and times: high when within 56 km (30 nm) of one of the FAA's
Core 30 airports with a ceiling of 3,000 ft or more, when it covers 2,500 km2 or more, or when it reaches FL180 (the
floor of Class A) over 500 km2 or more; moderate when it reaches FL180 over 100 km2 or more, covers 250 km2 or more,
or lies within 56 km of a Core 30 airport; low otherwise (since 16 Nov 2026, a smaller column to FL180 or above, such
as a range's 29 km2 munitions test, is low: traffic steps around it) (a small, low TFR away from the busiest airports, as most volcano, fire and range
TFRs are). Low-impact TFRs stay routine. A VIP TFR is an anomaly only at high impact. A re-issue is a new TFR of
the same type whose bounding box overlaps by half or more one Cordon held before it, still listed or gone within 14
days (the FAA cancels a changed TFR and reissues it under a new number); it is routine and names the one it repeats,
unless it is larger (area over 1.25 times, or a higher ceiling). The statutory TFRs over stadiums and Disney parks
are standing; every other TFR is routine. Space operations TFRs are read and
kept in Cordon's data but left off its feed and map: Launch publishes them and marks one issued in the last 72 hours
an anomaly by the same rule (since 14 Nov 2026).
An SFAR or KICZ NOTAM that Cordon saw the FAA list or withdraw for a country or region in the last 30 days makes
that section an anomaly against what the FAA listed before (none on the first read); every other section with an
SFAR or KICZ NOTAM is routine. Cordon reports the FAA's own words (prohibition, advisory, pointer) and does not rank
them against EASA's bulletins. The FAA's notices bind US operators; they are not a statement about other airlines.
A change of Canada's level or regional advisories for a place in the last 30 days is an anomaly against what Cordon
held before; so is an update in the last 72 hours that Canada itself labels an advisory change, or whose note starts
with its risk level section (the label alone missed one: Mexico, 12 Nov 2026). Places above Canada's lowest level or
with regional advisories, and places it updated in the last 72 hours, are listed as routine; editorial changes and
updates to the embassy contacts section alone do not count as updates. Cordon does not rank Canada's levels against
the State Department's or the UK's.
A change of New Zealand's level for a destination, or of its note of other levels in some areas, in the last 30
days is an anomaly against what Cordon held before. Destinations at "Exercise increased caution" or above, with such
a note, or updated in the last 72 hours (MFAT gives the day only) are listed as routine. Cordon does not rank New
Zealand's levels against any other government's.
A CDC notice that Cordon sees appear, or change level, in the last 30 days is an anomaly against the notices it held
before; every other notice is routine, and one CDC dated in the last 72 hours is marked new. A notice CDC withdraws is
recorded as a change. Cordon does not rank CDC's health levels against any travel advisory level.
Cordon makes no judgment of its own;
those come through warning problem CD-WP-1 and through Verdict, which scores forecasts of renewals and changes.

## Places
Countries are drawn at a label point inside the country (the kit's Natural Earth points), not at the capital. Gaza and
the West Bank, which State files under Israel's code, are placed by hand. NGA positions are drawn as written, in the
shape the warning's words give: "area bound by" is a polygon, "trackline joining" a line, and "within N miles of" a
position a circle (a 32-sided polygon; NGA's miles are nautical). "Within N miles of trackline joining" is drawn as
the line, with N in `measures.corridor_half_width_m`; circle radii are in `measures.radius_m`. Positions with none of
these words are points. A shape that crosses 180 degrees keeps its longitudes continuous (some run past 180), so it is
drawn across the date line and not the long way round. Warning text over 6,000 characters is cut, and the cut says so.
NGA broadcasts some warnings in two series (NAVAREA XII and HYDROPAC) and neither copy cites the other, so Cordon
matches them on their words: same category, same time groups, and the same positions in the same order, at most a
fifth of them more than 0.05 degrees apart (fewer than three positions must match exactly), from different series.
The hazard is drawn once, under the NAVAREA copy (otherwise the earliest issued); the other copies are listed in
`measures.rebroadcasts` with every position that differs, as each was written, and counted in the health block's
`rebroadcasts_merged`. FAA
programs are drawn at the airport coordinates the FAA publishes with them; a program listed against a center or the
whole system is drawn at the US label point. The FAA's prohibitions and advisories are drawn as the country's outline
on the map and placed at its label point in the feed; the three sections that name a sea or region (Central America's
Pacific waters, the Pacific Ocean, the Persian Gulf and Gulf of Oman) have no point and link the FAA's page. FCDO, Canadian and New Zealand advice is placed at the country's label point (the Azores, which
Canada advises on apart from Portugal, at Ponta Delgada). A CDC notice is placed at the label point of each
country it names: from its Country List when CDC gives one (the pieces after "including" are parts of the country
before them; a territory such as "Azores (Portugal)" is placed in the country in its parentheses), otherwise from the
title. CDC dates notices without a time; Cordon shows that date and keeps the GMT stamp CDC gives. TFRs are drawn with
the outline the FAA publishes (its circles already turned into rings; a circle given only by centre and radius is a
32-sided polygon) and tagged with the country from the FAA's own state field (Puerto Rico, Guam and the other
territories by their own codes, everything else US), not from the outline, because coarse borders would tag a TFR at
Brownsville as Mexico. Standing nationwide TFRs with no area are not listed; the health block counts them (`no_shape`).
US items with a shape (TFRs, FAA programs at their airports) also carry `subdivisions`, the ISO 3166-2 code of each
US state they are in (kit 0.5.7): the FAA's state field for a TFR, else the states the outline or point falls in on
Natural Earth's 1:10m outlines (right to about 1 km at a state line). An item placed at a country's label point gets
none, so a notice for the whole country is never read as one for Kansas.

## Gaps and no data
A source that fails keeps its last good data and is marked in `data/health.json`; the page shows its age. NGA
serves one daily file per area: when one fails and the others answer, that area keeps its earlier warnings, the
health detail and `held_areas` say so, and after 48 hours held its warnings are withheld. Embassy
alert feeds were down on 31 Oct 2026 ("Technical Difficulties"), so that layer may be empty. FAA programs last hours,
so the FAA list goes stale after 3 hours without a good fetch and is then withheld; from a held list (the latest fetch
failed) a program past its listed end time is dropped. TFRs go stale after 6 hours without a good list; a TFR past
its own expiry is dropped and counted (`expired`). Canada's index, New Zealand's list, CDC's notices and the FAA's prohibitions page go stale after 48 hours. The FCDO list goes stale after 48 hours; a country page that fails
keeps its last statements and is asked for again on the next run.
