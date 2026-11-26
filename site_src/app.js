/* Cordon map page. Reads data/map.json (built by tools/cordon.py) and geo/world.json (Natural Earth outlines with ISO
 * codes). Text is inserted as text, never HTML. Times go through the shared TicTime module; calendar dates (bulletin
 * expiries) are shown as plain dates. */
(function () {
  "use strict";
  var T = window.TicTime;
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var POSTURE = { authorized_departure: ["AD", "Authorized departure"], ordered_departure: ["OD", "Ordered departure"],
    suspended_operations: ["S", "Suspended operations"] };
  var NAV = { launch: "Launches and space debris", gnss: "GNSS (GPS) interference or testing", military: "Military exercises and firing",
    mines: "Mines and ordnance", piracy: "Piracy", security: "Security incidents", ice: "Ice and icebergs", restricted_area: "Restricted areas", search_and_rescue: "Search and rescue",
    pollution: "Pollution", port: "Ports", cable_pipeline: "Cable and pipeline work", wreck: "Wrecks and drifting objects",
    hazard: "Reefs, groundings, obstructions", underwater_ops: "Underwater work and salvage", drilling_survey: "Drilling and surveys",
    shoal: "Shoals", aids_to_navigation: "Lights and buoys", radio_service: "Radio and NAVTEX services", other: "Other" };
  var KEY_NAV = { launch: 1, gnss: 1, military: 1, mines: 1, piracy: 1, security: 1 };
  var FAA_WORD = { ground_stop: "Ground stop", ground_delay: "Ground delay program", closure: "Closed" };
  var UK_ALERT = { avoid_all_travel_to_whole_country: "all travel to the whole country",
    avoid_all_but_essential_travel_to_whole_country: "all but essential travel to the whole country",
    avoid_all_travel_to_parts: "all travel to parts", avoid_all_but_essential_travel_to_parts: "all but essential travel to parts" };
  var NZ_LEVEL = { normal: "No advice level at this time", low: "Exercise normal safety and security precautions",
    medium: "Exercise increased caution", high: "Avoid non-essential travel", avoid: "Do not travel" };
  var NZ_RANK = { normal: 0, low: 1, medium: 2, high: 3, avoid: 4 };
  var JP_LEVEL = { 0: "no danger level in force", 1: "Level 1: Exercise caution", 2: "Level 2: Avoid non-essential travel",
    3: "Level 3: Do not travel", 4: "Level 4: Evacuate, do not travel" };
  var NL_COLOUR = { groen: "Green", geel: "Yellow", oranje: "Orange", rood: "Red" };
  var NL_RANK = { green: 0, yellow: 1, orange: 2, red: 3 };
  var CA_LEVEL = { 0: "Exercise normal security precautions", 1: "Exercise a high degree of caution",
    2: "Avoid non-essential travel", 3: "Avoid all travel" };
  function ukWords(list) {
    if (!list) return "not read";
    var order = Object.keys(UK_ALERT);
    var s = list.slice().sort(function (a, b) { return order.indexOf(a) - order.indexOf(b); });
    return s.length ? "Advises against " + s.map(function (x) { return UK_ALERT[x] || x.replace(/_/g, " "); }).join(" and ") : "No advice against travel";
  }

  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
  function h(tag, attrs, kids) {
    var e = document.createElement(tag);
    for (var k in attrs || {}) { if (attrs[k] != null) e.setAttribute(k, attrs[k]); }
    (kids || []).forEach(function (c) { if (c != null) e.append(c instanceof Node ? c : document.createTextNode(String(c))); });
    return e;
  }
  function day(d) { if (!d) return "—"; var p = String(d).slice(0, 10).split("-"); return Number(p[2]) + " " + MONTHS[Number(p[1]) - 1] + " " + p[0]; }
  function when(iso) { return iso ? T.format(iso) : "—"; }
  // Leaflet inserts a string tooltip as HTML; a text node keeps source text as text.
  function tip(text) { return h("div", { "class": "tip" }, [text]); }
  function link(url, text) { return url ? h("a", { href: url, rel: "noopener" }, [text]) : text; }
  // A table wider than a phone scrolls inside its own box (focusable, so the keyboard can scroll it too), so the
  // page itself stays as wide as the screen and the house bar's buttons stay on it.
  // A long table shows its first rows (10 on a phone, 15 wider; each table puts flagged and higher-level rows
  // first) and "Show all N": the hub's tic-fold.js, at every width since 18 Nov 2026 (it was phones only). A table of
  // 25 rows or more also gets a find box. Without script, and in print, every row shows.
  function table(head, rows) {
    var attrs = { "data-tic-fold": "" };
    if (rows.length >= 25) attrs["data-tic-fold-find"] = "";
    return h("div", { "class": "tbl", tabindex: "0" }, [h("table", attrs, [h("thead", null, [h("tr", null, head.map(function (x) { return h("th", null, [x]); }))]),
      h("tbody", null, rows.map(function (r) {
        return h("tr", r.cls ? { "class": r.cls } : null, r.map(function (c) {
          return c && c.td ? h("td", { "class": c.cls }, [c.td]) : h("td", null, [c]); })); }))])]);
  }

  // Travel advice by destination (16 Nov 2026): one place, every government's advice side by side. The full
  // lists below fold away (open on wider screens at load); a link to anything inside them opens the fold.
  var TOP = { state: function (a) { return a.level === 4; },
    fcdo: function (u) { return (u.alert_status || []).indexOf("avoid_all_travel_to_whole_country") >= 0; },
    canada: function (c) { return c.level === 3; }, safetravel: function (c) { return c.level === "avoid"; } };
  function byIso(list) {
    var m = {};
    (list || []).forEach(function (x) { (x.iso ? [x.iso] : x.countries || []).forEach(function (c) { (m[c] = m[c] || []).push(x); }); });
    return m;
  }
  function placeName(x, prefix) { return x.name || x.title.replace(prefix, "").split(":")[0]; }
  function fresh(d, key) { return (d.health[key] || {}).state === "fresh"; }
  function destination(d) {
    // Dates only, with the year, in the viewer's zone: the governments update on very different cycles.
    function date(iso) { return iso ? T.format(iso, { year: true, time: false }) : "—"; }
    var src = { state: byIso(d.advisories), fcdo: byIso(d.fcdo), canada: byIso(d.canada), safetravel: byIso(d.safetravel), cdc: byIso(d.cdc),
      japan: byIso((d.japan || []).filter(function (c) { return !c.type_en; })), netherlands: byIso(d.netherlands) };
    var names = {};
    [["netherlands", /^Netherlands, /], ["japan", /^Japan, /], ["safetravel", /^New Zealand, /], ["canada", /^Canada, /], ["fcdo", /^UK FCDO, /], ["state", null]].forEach(function (p) {
      Object.keys(src[p[0]]).forEach(function (iso) { names[iso] = placeName(src[p[0]][iso][0], p[1]); }); });
    var sel = document.getElementById("dest");
    if (sel.options.length < 2) {
      Object.keys(names).sort(function (a, b) { return names[a].localeCompare(names[b]); }).forEach(function (iso) {
        sel.append(h("option", { value: iso }, [names[iso]])); });
      sel.addEventListener("change", function () { show(sel.value); });
    }
    function show(iso) {
      var out = document.getElementById("dest-out");
      var rel = document.getElementById("dest-related");
      if (!iso || !names[iso]) { out.replaceChildren(); rel.hidden = true; return; }
      if (window.TicRelated) { var nm = {}; nm[iso] = names[iso]; TicRelated.render(rel, { countries: [iso], here: "cordon", names: nm, level: 2 }); }
      var rows = [];
      function none(key, text) { return fresh(d, key) ? text : "No current data: see Sources."; }
      (src.state[iso] || []).forEach(function (a) {
        rows.push(["US State Department", link(a.link, (a.name !== names[iso] ? a.name + ": " : "") + "Level " + a.level + ", " + a.level_text),
          { td: date(a.updated), cls: "num" }]);
        if (POSTURE[a.posture]) rows.push(["US embassy", POSTURE[a.posture][1] + (a.sentence ? ": " + a.sentence : ""), "—"]);
      });
      if (!src.state[iso]) rows.push(["US State Department", none("state-travel-advisories", "No advisory for this place"), "—"]);
      (src.fcdo[iso] || []).forEach(function (u) { rows.push(["UK FCDO", link(u.link, ukWords(u.alert_status)), { td: date(u.updated), cls: "num" }]); });
      if (!src.fcdo[iso]) rows.push(["UK FCDO", none("uk-fcdo-travel-advice", "No advice against travel"), "—"]);
      (src.canada[iso] || []).forEach(function (c) { rows.push(["Canada", link(c.link, c.advisory), { td: date(c.updated), cls: "num" }]); });
      if (!src.canada[iso]) rows.push(["Canada", none("gac-travel-advisories", "Nothing above “Exercise normal security precautions”"), "—"]);
      (src.safetravel[iso] || []).forEach(function (c) {
        rows.push(["New Zealand", link(c.link, c.advice + (c.regional_note ? " (" + c.regional_note + ")" : "")),
          { td: c.updated ? day(c.updated) : "—", cls: "num" }]); });
      if (!src.safetravel[iso]) rows.push(["New Zealand", none("nz-mfat-safetravel", "Nothing above normal safety and security precautions"), "—"]);
      (src.japan[iso] || []).forEach(function (c) {
        rows.push(["Japan", link(c.link, c.advice + (c.levels && c.levels.length > 1 ? " (other levels in some areas)" : "")),
          { td: day(c.updated_day), cls: "num" }]); });
      if (!src.japan[iso]) rows.push(["Japan", none("jp-mofa-overseas-safety", "Nothing above Level 1 (exercise caution)"), "—"]);
      (src.netherlands[iso] || []).forEach(function (c) {
        rows.push(["Netherlands", link(c.link, c.advice + (c.regional ? " (the colour differs by area)" : "")),
          { td: c.updated ? date(c.updated) : "—", cls: "num" }]); });
      if (!src.netherlands[iso]) rows.push(["Netherlands", none("nl-minbuza-travel-advice", "Green, or not listed"), "—"]);
      (src.cdc[iso] || []).forEach(function (n) {
        rows.push(["CDC health notice", link(n.link, "Level " + n.level + ": " + n.title.replace(/^CDC Level [^:]+: /, "")),
          { td: n.date ? day(n.date) : date(n.published), cls: "num" }]); });
      if (!src.cdc[iso]) rows.push(["CDC health notice", none("cdc-travel-notices", "No travel health notice"), "—"]);
      out.replaceChildren(h("h3", { "class": "dest-name" }, [names[iso]]),
        table(["Government", "Advice", "Updated"], rows.map(function (r) { return [{ td: r[0], cls: "gov" }, r[1], r[2]]; })));
    }
    // Quick picks: places where two or more governments are at their highest level for the whole country.
    var top = Object.keys(names).filter(function (iso) {
      return ["state", "fcdo", "canada", "safetravel"].filter(function (k) { return (src[k][iso] || []).some(TOP[k]); }).length >= 2;
    }).sort(function (a, b) { return names[a].localeCompare(names[b]); });
    document.getElementById("dest-top").replaceChildren(top.length ? h("div", { "class": "dest-top" }, [
      h("p", { "class": "small muted" }, ["Where two or more governments advise against all travel to the whole country:"]),
      h("div", { "class": "chips" }, top.map(function (iso) {
        var b = h("button", { type: "button", "class": "chip" }, [names[iso]]);
        b.addEventListener("click", function () { sel.value = iso; show(iso); sel.focus(); });
        return b; }))]) : null);
    show(sel.value);
  }
  var folds = document.getElementById("travel-lists");
  if (folds && window.matchMedia("(min-width: 761px)").matches) folds.open = true;
  function openFold() {
    var id = decodeURIComponent(location.hash.slice(1)), el = id && document.getElementById(id);
    var f = el && el.closest("details");
    if (f && !f.open) { f.open = true; el.scrollIntoView(); }
  }
  openFold();
  window.addEventListener("hashchange", openFold);

  // Wheel zoom stays off until the reader clicks the map, so scrolling the page never gets trapped in it.
  var map = L.map("map", { worldCopyJump: true, minZoom: 1, maxZoom: 8, zoomSnap: 0.5, scrollWheelZoom: false })
    .setView([24, 20], 2);
  map.once("click", function () { map.scrollWheelZoom.enable(); });
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution("Natural Earth · State Dept · EASA · NGA · FAA · UK FCDO (OGL v3.0) · Global Affairs Canada (OGL-Canada) · NZ MFAT (CC BY 4.0) · CDC");
  var layers = {};

  function levelColor(n) { return n ? css("--l" + n) : css("--land"); }

  // "My area" (tic-area.js, Tom 15 Nov 2026): place-bound notices outside the viewer's area are dimmed, not hidden.
  // Travel advice is about destinations, so it is never dimmed.
  var A = window.TicArea;
  function inArea(item) { return !A || A.contains(item); }
  function keepBase(lyr) {
    lyr._base = { opacity: lyr.options.opacity == null ? 1 : lyr.options.opacity, fillOpacity: lyr.options.fillOpacity };
  }
  function dim(d) {
    var n = { tfr: [0, 0], faa: [0, 0], nav: [0, 0], notam: [0, 0] };
    [["tfr", "tfr"], ["navwarn", "nav"], ["faa", "faa"], ["notam", "notam"]].forEach(function (pair) {
      var group = layers[pair[0]];
      if (!group) return;
      group.eachLayer(function (lyr) {
        var item = lyr._item || (lyr.feature && { subdivisions: lyr.feature.properties.subdivisions, geometry: lyr.feature.geometry });
        var ok = inArea(item);
        if (lyr._base) lyr.setStyle(ok ? lyr._base : { opacity: 0.18, fillOpacity: 0.03 });
        if (ok) { n[pair[1]][0] += 1; if ((lyr._item || lyr.feature.properties).tier === "anomaly") n[pair[1]][1] += 1; }
      });
    });
    var note = document.getElementById("area-note");
    if (!A || A.get().kind === "all") {
      note.textContent = "Area: everywhere. Choose one with the Area button at the top to dim flight restrictions, airport " +
        "programs, maritime warnings and NOTAMs elsewhere.";
      return;
    }
    function part(c, one, many) { return c[0] + " " + (c[0] === 1 ? one : many) + (c[1] ? " (" + c[1] + " flagged)" : ""); }
    note.textContent = "Your area: " + A.label() + ". In it: " + part(n.tfr, "flight restriction", "flight restrictions") +
      ", " + part(n.faa, "FAA airport program", "FAA airport programs") + ", " +
      part(n.nav, "maritime warning", "maritime warnings") + ", " + part(n.notam, "ranked NOTAM", "ranked NOTAMs") +
      ". The rest are dimmed.";
  }

  function draw(world, d) {
    var byIso = {};
    d.advisories.forEach(function (a) { if (a.iso && (!byIso[a.iso] || a.level > byIso[a.iso].level)) byIso[a.iso] = a; });
    var adv = d.advisories.filter(function (a) { return a.iso; });

    layers.advisories = L.geoJSON(world, {
      style: function (f) {
        var a = byIso[f.properties.iso];
        return { color: css("--border"), weight: 0.6, fillColor: levelColor(a && a.level), fillOpacity: a ? 0.9 : 0.6 };
      },
      onEachFeature: function (f, lyr) {
        var all = adv.filter(function (a) { return a.iso === f.properties.iso; });
        var text = all.length ? all.map(function (a) { return a.name + ": Level " + a.level + ", " + a.level_text; }).join("\n")
          : f.properties.name + ": no US advisory listed";
        lyr.bindTooltip(tip(text), { sticky: true });
      }
    }).addTo(map);

    var czibIso = {};
    d.czibs.forEach(function (b) { b.countries.forEach(function (c) { (czibIso[c] = czibIso[c] || []).push(b); }); });
    layers.czib = L.geoJSON({ type: "FeatureCollection", features: world.features.filter(function (f) { return czibIso[f.properties.iso]; }) }, {
      style: { color: css("--czib"), weight: 2.2, dashArray: "6 4", fill: false },
      onEachFeature: function (f, lyr) {
        lyr.bindTooltip(tip(czibIso[f.properties.iso].map(function (b) {
          return "EASA " + b.number + ": " + b.subject + " (valid until " + day(b.valid_until) + ")"; }).join("\n")), { sticky: true });
      }
    }).addTo(map);

    var prnIso = {};
    (d.faaprn || []).forEach(function (s) { s.countries.forEach(function (c) { (prnIso[c] = prnIso[c] || []).push(s); }); });
    layers.prn = L.geoJSON({ type: "FeatureCollection", features: world.features.filter(function (f) { return prnIso[f.properties.iso]; }) }, {
      style: { color: css("--prn"), weight: 2, dashArray: "1 5", lineCap: "round", fill: false },
      onEachFeature: function (f, lyr) {
        lyr.bindTooltip(tip(prnIso[f.properties.iso].map(function (s) { return s.title; }).join("\n")), { sticky: true });
      }
    }).addTo(map);

    layers.posture = L.layerGroup();
    d.advisories.forEach(function (a) {
      var p = POSTURE[a.posture];
      var c = d.points["cordon:advisory:" + a.key];
      if (!p || !c) return;
      L.marker([c[1], c[0]], { icon: L.divIcon({ className: "posture-icon", html: "", iconSize: [26, 18] }), keyboard: true,
        title: a.name + ": " + p[1] })
        .bindTooltip(tip(a.name + ": US embassy, " + p[1].toLowerCase() + (a.sentence ? "\n" + a.sentence : "")))
        .on("add", function (ev) { ev.target.getElement().textContent = p[0]; })
        .addTo(layers.posture);
    });
    layers.posture.addTo(map);

    layers.navwarn = L.geoJSON({ type: "FeatureCollection", features: d.warnings.map(function (w) {
      return { type: "Feature", geometry: w.geometry, properties: w }; }) }, {
      pointToLayer: function (f, ll) {
        var key = KEY_NAV[f.properties.category];
        return L.circleMarker(ll, { radius: key ? 4.5 : 3, weight: key ? 1.5 : 1, color: key ? css("--nav-key") : css("--nav"),
          fillColor: key ? css("--nav-key") : css("--nav"), fillOpacity: key ? 0.85 : 0.45 });
      },
      style: function (f) { var key = KEY_NAV[f.properties.category];
        return { color: key ? css("--nav-key") : css("--nav"), weight: 1.5, fillOpacity: 0.12 }; },
      onEachFeature: function (f, lyr) {
        keepBase(lyr);
        var w = f.properties;
        lyr.bindTooltip(tip(w.number + " (" + (NAV[w.category] || w.category) + ")\n" + [w.sea, w.place].filter(Boolean).join(", ")
          + "\n" + w.headline + (w.also ? "\nAlso broadcast as " + w.also.join(", ") : "")), { sticky: true });
      }
    }).addTo(map);

    layers.faa = L.layerGroup();
    (d.faa || []).forEach(function (p) {
      if (!p.coordinates) return;
      var key = p.tier === "anomaly";
      L.circleMarker([p.coordinates[1], p.coordinates[0]], { radius: key ? 7 : (p.program === "closure" ? 4 : 5.5),
        weight: key ? 2 : 1.5, color: key ? css("--faa-key") : css("--faa"), fillColor: key ? css("--faa-key") : css("--faa"),
        fillOpacity: p.program === "closure" ? 0.2 : 0.75 })
        .on("add", function (ev) { keepBase(ev.target); })
        .bindTooltip(tip(p.title + (p.until ? "\nUntil " + when(p.until) : "") + (key ? "\nUnusual: more ground stops at once than normal" : "")))
        .addTo(layers.faa);
      layers.faa.getLayers()[layers.faa.getLayers().length - 1]._item = { subdivisions: p.subdivisions, tier: p.tier,
        geometry: { type: "Point", coordinates: p.coordinates } };
    });
    layers.faa.addTo(map);

    layers.tfr = L.geoJSON({ type: "FeatureCollection", features: (d.tfr || []).map(function (t) {
      return { type: "Feature", geometry: t.geometry, properties: t }; }) }, {
      style: function (f) { var key = f.properties.tier === "anomaly";
        return { color: key ? css("--tfr-key") : css("--tfr"), weight: key ? 2 : 1.4, fillOpacity: key ? 0.18 : 0.1 }; },
      onEachFeature: function (f, lyr) {
        keepBase(lyr);
        var t = f.properties;
        lyr.bindTooltip(tip(t.title + "\n" + [t.floor, t.ceiling].filter(Boolean).join(" to ")
          + (t.effective ? "\nFrom " + when(t.effective) : "") + (t.until ? "\nUntil " + when(t.until) : "")
          + (t.impact ? "\nImpact " + t.impact + (t.impact_basis && t.impact_basis.length ? ": " + t.impact_basis.join("; ") : "") : "")
          + (t.reissue_of ? "\nRe-issue of " + t.reissue_of : "")
          + (t.tier === "anomaly" ? "\nNew in the last 72 hours, and of some impact" : "")), { sticky: true });
      }
    }).addTo(map);

    // Ranked international NOTAMs (cordon/significance.py): the area the text draws, or the Q line circle dashed.
    layers.notam = L.geoJSON({ type: "FeatureCollection", features: (d.notams || []).filter(function (t) { return t.geometry; })
      .map(function (t) { return { type: "Feature", geometry: t.geometry, properties: t }; }) }, {
      style: function (f) { var key = f.properties.tier === "anomaly"; var env = f.properties.precision !== "area";
        return { color: key ? css("--notam-key") : css("--notam"), weight: key ? 2 : 1.4, fillOpacity: key ? 0.16 : 0.08,
                 dashArray: env ? "4 4" : null }; },
      pointToLayer: function (f, ll) { return L.circleMarker(ll, { radius: 5 }); },
      onEachFeature: function (f, lyr) {
        keepBase(lyr);
        var t = f.properties, s = t.significance || {};
        lyr.bindTooltip(tip(t.title + "\n" + [t.lower, t.upper].filter(Boolean).join(" to ")
          + (t.start ? "\nFrom " + when(t.start) : "") + (t.until ? "\nUntil " + when(t.until) : "")
          + "\nRanked " + (s.tier || "") + (s.reasons && s.reasons.length ? ": " + s.reasons.join("; ") : "")
          + (t.precision !== "area" ? "\nArea: the Q line circle, an envelope" : "")), { sticky: true });
      }
    }).addTo(map);

    document.querySelectorAll(".layers input").forEach(function (box) {
      box.addEventListener("change", function () {
        var l = layers[box.getAttribute("data-layer")];
        if (box.checked) l.addTo(map); else map.removeLayer(l);
      });
    });

    var lg = document.getElementById("legend");
    lg.replaceChildren(
      h("span", null, [h("span", { "class": "sw", style: "background:" + css("--l1") }), "Level 1"]),
      h("span", null, [h("span", { "class": "sw", style: "background:" + css("--l2") }), "2"]),
      h("span", null, [h("span", { "class": "sw", style: "background:" + css("--l3") }), "3"]),
      h("span", null, [h("span", { "class": "sw", style: "background:" + css("--l4") }), "4"]),
      h("span", null, [h("span", { "class": "ln" }), "EASA bulletin"]),
      h("span", null, [h("span", { "class": "ln prn" }), "FAA prohibition or advisory"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--nav-key") }), "launch, military, mines, GNSS"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--nav") }), "other maritime warnings"]),
      h("span", null, [h("span", { "class": "posture-icon", style: "display:inline-block;padding:0 4px;margin-right:4px" }, ["OD"]), "embassy status"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--faa") }), "FAA airport program"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--faa-key") }), "unusual number of ground stops"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--tfr") }), "FAA flight restriction"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--tfr-key") }), "new restriction of some impact"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--notam") }), "ranked international NOTAM"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--notam-key") }), "significant NOTAM, new"]));
  }

  // Header row (tic-shell): counts from this build. A source that is not fresh is withheld from the map, so its tile
  // says "no current data" rather than showing a zero that would read as nothing in force.
  function header(d) {
    var level4 = d.advisories.filter(function (a) { return a.level === 4; }).length;
    var posts = d.advisories.filter(function (a) { return POSTURE[a.posture]; }).length;
    var us = fresh(d, "state-travel-advisories");
    var tiles = [
      ["US Level 4 (Do Not Travel)", us ? level4 : null],
      ["US embassies on departure or suspended", us ? posts : null],
      ["EASA conflict-zone bulletins", fresh(d, "easa-czib") ? d.czibs.length : null],
      ["FAA prohibitions and advisories abroad", fresh(d, "faa-prohibitions-notices") ? d.faaprn.length : null],
      ["Warnings to mariners", fresh(d, "nga-navwarnings") ? d.warnings.length : null],
      ["Changes in the last 30 days", d.changes.length]
    ];
    document.getElementById("tiles").replaceChildren.apply(document.getElementById("tiles"), tiles.map(function (t) {
      return h("div", { "class": "tile" }, [h("span", { "class": "k" }, [t[0]]),
        h("span", { "class": "v" }, [t[1] === null ? "\u2014" : String(t[1])]),
        t[1] === null ? h("span", { "class": "k" }, ["No current data"]) : ""]);
    }));
    var kids = [h("span", { "class": "tic-reading-k" }, ["Today\u2019s reading"])];
    if (us) {
      kids.push(h("b", {}, [String(level4)]), (level4 === 1 ? " place is" : " places are") + " at US Level 4 (Do Not Travel) and ",
        h("b", {}, [String(posts)]), (posts === 1 ? " US embassy is" : " US embassies are") + " on departure status or suspended. ");
    }
    kids.push(h("b", {}, [String(d.changes.length)]), (d.changes.length === 1 ? " change" : " changes") + " in the last 30 days.");
    document.getElementById("reading").replaceChildren.apply(document.getElementById("reading"), kids);
  }

  function lists(d) {
    header(d);
    destination(d);
    var post = d.advisories.filter(function (a) { return POSTURE[a.posture]; });
    document.getElementById("posture").replaceChildren(post.length ? table(["Country", "Status", "What the advisory says"],
      post.map(function (a) { return [link(a.link, a.name), POSTURE[a.posture][1], a.sentence || "—"]; }))
      : h("p", { "class": "empty" }, ["No post is on authorized or ordered departure or has suspended operations."]));

    var cz = d.czibs.slice().sort(function (x, y) { return (x.valid_until || "9").localeCompare(y.valid_until || "9"); });
    document.getElementById("czibs").replaceChildren(table(["Bulletin", "Airspace", "Valid until"],
      cz.map(function (b) { return [b.number, b.subject, { td: day(b.valid_until), cls: "num" }]; })));

    var ch = d.changes;
    document.getElementById("changes").replaceChildren(ch.length ? table(["When", "Where", "Change"], ch.map(function (c) {
      var what = c.lane === "faaprn" ? "FAA " + (c.kind === "new" ? "listed " : "withdrew ") + (c.label || c.key)
          + (c.entry_kind ? " (" + c.entry_kind + ")" : "")
        : c.lane === "cdc" ? (c.kind === "new" ? "New CDC health notice, level " + c.to
          : c.kind === "level" ? "CDC health notice level " + c.from + " to " + c.to
          : c.kind === "removed" ? "CDC health notice removed (was level " + c.from + ")" : c.kind)
        : c.lane === "japan" ? (c.kind === "level" ? "Japan's danger level: " + (JP_LEVEL[c.from] || c.from) + " to " + (JP_LEVEL[c.to] || c.to)
          : "Japan: levels in force in some areas changed (" + (c.from || []).join(", ") + " to " + (c.to || []).join(", ") + ")")
        : c.lane === "netherlands" ? (c.kind === "level" ? "Netherlands' colour: " + (NL_COLOUR[c.from] || c.from) + " to " + (NL_COLOUR[c.to] || c.to)
          : "Netherlands: colours in force in some areas changed (" + (c.from || []).map(function (x) { return NL_COLOUR[x] || x; }).join(", ")
            + " to " + (c.to || []).map(function (x) { return NL_COLOUR[x] || x; }).join(", ") + ")")
        : c.lane === "safetravel" ? (c.kind === "level" ? "New Zealand's advice: " + (NZ_LEVEL[c.from] || c.from) + " to " + (NZ_LEVEL[c.to] || c.to)
          : c.kind === "regional" ? "New Zealand: " + (c.to ? (c.from ? "note changed to \u201c" + c.to + "\u201d" : "now " + c.to) : "other levels in some areas removed") : c.kind)
        : c.lane === "canada" ? (c.kind === "level" ? "Canada's advisory: " + (CA_LEVEL[c.from] || c.from) + " to " + (CA_LEVEL[c.to] || c.to)
          : c.kind === "regional" ? "Canada: regional advisories " + (c.to ? "added" : "removed") : c.kind)
        : c.kind === "level" ? "Advisory level " + c.from + " to " + c.to
        : c.kind === "posture" ? "Embassy status " + String(c.from).replace(/_/g, " ") + " to " + String(c.to).replace(/_/g, " ") + " (under review)"
        : c.kind === "text" ? "Advisory text revised" : c.kind === "revised" ? "Bulletin revised: " + c.to[0] + ", valid until " + day(c.to[1])
        : c.kind === "status" ? "Bulletin " + c.from + " to " + c.to : c.kind === "new" ? "New"
        : c.kind === "alert" ? "UK FCDO advice: " + ukWords(c.from).toLowerCase() + " to " + ukWords(c.to).toLowerCase() : c.kind;
      return [{ td: when(c.at), cls: "num" }, c.name || c.subject || c.number, what]; }))
      : h("p", { "class": "empty" }, ["No changes recorded yet. Collection began on 31 Oct 2026."]));

    var counts = {};
    d.warnings.forEach(function (w) { counts[w.category] = (counts[w.category] || 0) + 1; });
    var cats = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; });
    var max = Math.max.apply(null, cats.map(function (c) { return counts[c]; }).concat([1]));
    document.getElementById("navcats").replaceChildren(h("div", { "class": "bars" }, cats.reduce(function (acc, c) {
      return acc.concat([h("span", null, [NAV[c] || c]),
        h("span", null, [h("div", { "class": "bar" + (KEY_NAV[c] ? " key" : ""), style: "width:" + Math.max(2, 100 * counts[c] / max) + "%" })]),
        h("span", { "class": "num" }, [counts[c]])]); }, [])));

    var fp = (d.faa || []).slice().sort(function (x, y) {
      var o = { ground_stop: 0, ground_delay: 1, closure: 2 };
      return o[x.program] - o[y.program] || x.airport.localeCompare(y.airport); });
    document.getElementById("faa").replaceChildren(fp.length ? table(["Program", "Airport", "As the FAA lists it", "Until"],
      fp.map(function (p) {
        var what = p.program === "closure" ? (p.notam || "—")
          : "Reason: " + (p.reason || "none given") + (p.avg_delay_min != null ? "; average delay " + Math.round(p.avg_delay_min) + " min" : "");
        var row = [FAA_WORD[p.program] + (p.tier === "anomaly" ? " (unusual)" : ""),
          p.airport + (p.airport_name ? " " + p.airport_name : ""), what, { td: when(p.until), cls: "num" }];
        if (p.coordinates && !inArea({ subdivisions: p.subdivisions, geometry: { type: "Point", coordinates: p.coordinates } })) row.cls = "outside";
        return row; }))
      : h("p", { "class": "empty" }, [(d.health["faa-nas-status"] || {}).state === "fresh"
          ? "The FAA lists no ground stop, ground delay program or airport closure."
          : "No current FAA data: see Sources below."]));

    var uk = (d.fcdo || []).slice().sort(function (x, y) {
      return (y.tier === "anomaly") - (x.tier === "anomaly") || (y.updated || "").localeCompare(x.updated || ""); });
    document.getElementById("fcdo").replaceChildren(uk.length ? table(["Place", "UK FCDO advice", "Latest update", "Updated"],
      uk.map(function (u) {
        var name = u.title.replace(/^UK FCDO, /, "").split(":")[0];
        return [link(u.link, name), ukWords(u.alert_status) + (u.tier === "anomaly" ? " (changed; was: " + (u.from_advice || "—") + ")" : ""),
          u.new ? (u.change || "—") : "—", { td: when(u.updated), cls: "num" }]; }))
      : h("p", { "class": "empty" }, [(d.health["uk-fcdo-travel-advice"] || {}).state === "fresh"
          ? "The FCDO advises against travel nowhere." : "No current UK FCDO data: see Sources below."]));

    var hn = (d.cdc || []).slice().sort(function (x, y) {
      return (y.tier === "anomaly") - (x.tier === "anomaly") || y.level - x.level || (y.published || "").localeCompare(x.published || ""); });
    document.getElementById("cdc").replaceChildren(hn.length ? table(["Level", "Notice", "Places", "CDC's date"],
      hn.map(function (n) {
        var what = n.title.replace(/^CDC Level [^:]+: /, "");
        var where = n.countries.length > 4 ? n.countries.length + " countries" : n.countries.join(", ") || "—";
        var note = n.tier === "anomaly" ? (n.change === "new" ? " (new)" : " (was level " + n.from_level + ")") : "";
        return [{ td: h("span", { "class": "lvl lvl-" + n.level }, [n.level]) }, link(n.link, what + note),
          where, { td: n.date ? day(n.date) : when(n.published), cls: "num" }]; }))
      : h("p", { "class": "empty" }, [(d.health["cdc-travel-notices"] || {}).state === "fresh"
          ? "CDC lists no travel health notice." : "No current CDC data: see Sources below."]));

    // The page lists Canada's two highest levels, changes and fresh updates; the feed carries every place above level 0.
    var ca = (d.canada || []).filter(function (c) { return c.level >= 2 || c.tier === "anomaly" || c.new; })
      .sort(function (x, y) { return (y.tier === "anomaly") - (x.tier === "anomaly") || y.level - x.level
        || (y.updated || "").localeCompare(x.updated || ""); });
    document.getElementById("canada").replaceChildren(ca.length ? table(["Place", "Canada's advice", "Latest update", "Updated"],
      ca.map(function (c) {
        var name = c.title.replace(/^Canada, /, "").split(":")[0];
        var was = c.tier !== "anomaly" ? "" : c.from_advice ? " (changed; was: " + c.from_advice + ")"
          : c.from_regional != null ? " (regional advisories " + (c.regional ? "added" : "removed") + ")" : " (Canada lists an advisory change)";
        return [link(c.link, name), c.advisory + was, c.new ? (c.update || "—") : "—", { td: when(c.updated), cls: "num" }]; }))
      : h("p", { "class": "empty" }, [(d.health["gac-travel-advisories"] || {}).state === "fresh"
          ? "Canada advises avoiding travel nowhere and lists no change." : "No current Government of Canada data: see Sources below."]));

    // The page lists New Zealand's two highest levels, changes and fresh updates; the feed carries the rest.
    var nz = (d.safetravel || []).filter(function (c) { return NZ_RANK[c.level] >= 3 || c.tier === "anomaly" || c.new; })
      .sort(function (x, y) { return (y.tier === "anomaly") - (x.tier === "anomaly") || NZ_RANK[y.level] - NZ_RANK[x.level]
        || (y.updated || "").localeCompare(x.updated || ""); });
    document.getElementById("safetravel").replaceChildren(nz.length ? table(["Place", "New Zealand's advice", "Other levels", "Updated"],
      nz.map(function (c) {
        var name = c.title.replace(/^New Zealand, /, "").split(":")[0];
        var was = c.tier !== "anomaly" ? "" : c.from_advice ? " (changed; was: " + c.from_advice + ")" : " (regional note changed)";
        return [link(c.link, name), c.advice + was, c.regional_note || "—", { td: c.updated ? day(c.updated) : "—", cls: "num" }]; }))
      : h("p", { "class": "empty" }, [(d.health["nz-mfat-safetravel"] || {}).state === "fresh"
          ? "New Zealand advises against travel nowhere and lists no change." : "No current New Zealand data: see Sources below."]));

    // Japan: levels 3 and 4, changes and fresh danger updates; the feed carries level 2 as well.
    var jl = (d.japan || []).filter(function (c) { return !c.type_en && (c.level >= 3 || c.tier === "anomaly" || c.new); })
      .sort(function (x, y) { return (y.tier === "anomaly") - (x.tier === "anomaly") || y.level - x.level
        || (y.updated || "").localeCompare(x.updated || ""); });
    document.getElementById("japan").replaceChildren(jl.length ? table(["Place", "Japan's advice", "Latest danger notice (Japanese)", "Updated"],
      jl.map(function (c) {
        var name = c.title.replace(/^Japan, /, "").split(":")[0];
        var was = c.tier !== "anomaly" ? "" : c.from_advice ? " (changed; was: " + c.from_advice + ")"
          : c.declared_move ? " (Japan's notice: levels " + c.declared_move + ")" : " (levels in some areas changed)";
        return [link(c.link, name), c.advice + (c.levels && c.levels.length > 1 ? " (other levels in some areas)" : "") + was,
          h("span", { lang: "ja" }, [c.title_ja || "—"]), { td: day(c.updated_day), cls: "num" }]; }))
      : h("p", { "class": "empty" }, [fresh(d, "jp-mofa-overseas-safety")
          ? "Japan advises against travel nowhere and lists no change." : "No current Japanese data: see Sources below."]));
    var jn = (d.japan || []).filter(function (c) { return c.type_en; })
      .sort(function (x, y) { return (y.issued || "").localeCompare(x.issued || ""); });
    document.getElementById("japan-notices").replaceChildren(jn.length ? table(["Place", "Kind", "Headline (Japanese, as published)", "Issued"],
      jn.map(function (c) {
        var name = c.title.replace(/^Japan, /, "").split(":")[0];
        return [link(c.link, name), c.type_en.charAt(0).toUpperCase() + c.type_en.slice(1), h("span", { lang: "ja" }, [c.title_ja || ""]),
          { td: when(c.issued), cls: "num" }]; }))
      : h("p", { "class": "empty" }, [fresh(d, "jp-mofa-overseas-safety")
          ? "Japan's embassies and consulates have posted no notice in the last 72 hours." : "No current Japanese data: see Sources below."]));

    var nlr = (d.netherlands || []).filter(function (c) { return NL_RANK[c.colour] >= 2 || c.tier === "anomaly" || c.new; })
      .sort(function (x, y) { return (y.tier === "anomaly") - (x.tier === "anomaly") || NL_RANK[y.colour] - NL_RANK[x.colour]
        || x.title.localeCompare(y.title); });
    document.getElementById("netherlands").replaceChildren(nlr.length ? table(["Place", "Netherlands' advice", "Updated"],
      nlr.map(function (c) {
        var name = c.title.replace(/^Netherlands, /, "").split(":")[0];
        var was = c.tier !== "anomaly" ? "" : c.from_advice ? " (changed; was: " + c.from_advice + ")" : " (colours in some areas changed)";
        return [link(c.link, name), c.advice + (c.regional ? " (the colour differs by area)" : "") + was,
          { td: c.updated ? T.format(c.updated, { year: true, time: false }) : "—", cls: "num" }]; }))
      : h("p", { "class": "empty" }, [fresh(d, "nl-minbuza-travel-advice")
          ? "The Netherlands advises against travel nowhere and lists no change." : "No current Dutch data: see Sources below."]));

    var PRN_RANK = { prohibition: 0, advisory: 1, pointer: 2, notice: 3 };
    var pr = (d.faaprn || []).slice().sort(function (x, y) {
      return (y.tier === "anomaly") - (x.tier === "anomaly") || PRN_RANK[x.strongest] - PRN_RANK[y.strongest]
        || x.title.localeCompare(y.title); });
    document.getElementById("prn").replaceChildren(pr.length ? table(["Where", "What the FAA lists", "FIRs"],
      pr.map(function (s) {
        var name = s.title.replace(/^FAA, /, "").split(": ")[0];
        var list = h("span", null, (s.entries || []).reduce(function (acc, e, i) {
          return acc.concat((i ? ["; "] : []).concat([link(e.url, e.label), " (" + e.kind + ")"])); }, []));
        var was = s.tier !== "anomaly" ? "" : " \u2014 changed" + ((s.added || []).length ? "; new: " + s.added.join(", ") : "")
          + ((s.removed || []).length ? "; withdrawn: " + s.removed.join(", ") : "");
        return [link(s.link, name), h("span", null, [list, was]), (s.firs || []).join(" ") || "\u2014"]; }))
      : h("p", { "class": "empty" }, [(d.health["faa-prohibitions-notices"] || {}).state === "fresh"
          ? "The FAA lists no prohibition or advisory for foreign airspace." : "No current FAA data: see Sources below."]));

    var tf = (d.tfr || []).slice().sort(function (x, y) {
      return (y.tier === "anomaly") - (x.tier === "anomaly") || (x.effective || "").localeCompare(y.effective || ""); });
    document.getElementById("tfrs").replaceChildren(tf.length ? table(["NOTAM", "Type", "Where", "Impact", "From", "Until"],
      tf.map(function (t) {
        var where = t.title.replace(/^FAA TFR [^:]+: /, "");
        var row = [link(t.link, t.notam_id), String(t.type || "").toLowerCase() + (t.tier === "anomaly" ? " (new)" : "")
          + (t.reissue_of ? " (re-issue)" : ""), where, t.impact || "—",
          { td: when(t.effective), cls: "num" }, { td: when(t.until), cls: "num" }];
        if (!inArea(t)) row.cls = "outside";
        return row; }))
      : h("p", { "class": "empty" }, [(d.health["faa-tfr"] || {}).state === "fresh"
          ? "The FAA lists no flight restriction with an area." : "No current FAA TFR data: see Sources below."]));

    var nt = (d.notams || []).slice().sort(function (x, y) {
      return (y.tier === "anomaly") - (x.tier === "anomaly") || ((y.significance || {}).tier === "significant")
        - ((x.significance || {}).tier === "significant") || (x.start || "").localeCompare(y.start || ""); });
    document.getElementById("notams").replaceChildren(nt.length ? table(["NOTAM", "Where", "What", "Ranked", "From", "Until"],
      nt.map(function (t) {
        var s = t.significance || {};
        var row = [t.number + (t.tier === "anomaly" ? " (new)" : ""), [t.location, t.fir].filter(function (x, i, a) {
            return x && a.indexOf(x) === i; }).join(" / ") + ((t.countries || []).length ? " (" + t.countries.join(", ") + ")" : ""),
          h("span", null, [h("strong", null, [t.subject || "NOTAM"]), ": " + (t.text || "").replace(/\s+/g, " ").slice(0, 220)
            + ((t.text || "").length > 220 ? " ..." : "")]),
          (s.tier || "") + (s.reasons && s.reasons.length ? ": " + s.reasons.join("; ") : ""),
          { td: when(t.start), cls: "num" }, { td: when(t.until), cls: "num" }];
        if (!inArea(t)) row.cls = "outside";
        return row; }))
      : h("p", { "class": "empty" }, [(d.health["faa-nms"] || {}).state === "fresh"
          ? "No international NOTAM is ranked notable or significant now." : "No current NOTAM data: see Sources below."]));

    var hi = d.advisories.filter(function (a) { return a.level >= 3; })
      .sort(function (x, y) { return y.level - x.level || x.name.localeCompare(y.name); });
    document.getElementById("levels").replaceChildren(table(["Level", "Place", "Advice"], hi.map(function (a) {
      return [{ td: h("span", { "class": "lvl lvl-" + a.level }, [a.level]) }, link(a.link, a.name), a.level_text]; })));

    var names = { "state-travel-advisories": "State Department travel advisories", "us-embassy-alerts": "US embassy alerts",
      "easa-czib": "EASA conflict-zone bulletins", "nga-navwarnings": "NGA warnings to mariners",
      "faa-nas-status": "FAA airport status (ground stops, delay programs, closures)",
      "faa-tfr": "FAA temporary flight restrictions",
      "faa-nms": "NOTAMs (FAA NMS-API)",
      "faa-prohibitions-notices": "FAA prohibitions and advisories for foreign airspace", "uk-fcdo-travel-advice": "UK FCDO foreign travel advice",
      "gac-travel-advisories": "Government of Canada travel advisories",
      "nz-mfat-safetravel": "New Zealand SafeTravel advice",
      "jp-mofa-overseas-safety": "Japan overseas safety information (MOFA)",
      "nl-minbuza-travel-advice": "Netherlands travel advice",
      "cdc-travel-notices": "CDC travel health notices" };
    document.getElementById("health").replaceChildren(table(["Source", "Last good", "Status"], Object.keys(names).map(function (k) {
      var s = d.health[k] || {};
      var old = s.state === "stale" || s.state === "never";
      var bad = !s.last_ok || (s.failures || 0) > 0 || old;
      return [names[k], { td: when(s.last_ok), cls: "num" },
        { td: h("span", { "class": bad ? "bad" : "ok" }, [(old ? "Stale, not shown: " : "") + (s.detail || "—")]) }]; })));

    document.getElementById("asof").setAttribute("datetime", d.generated_at);
    T.renderAll(document);
  }

  T.mountSettings(document.getElementById("time-settings"));
  Promise.all(["geo/world.json", "data/map.json", "geo/states.json"].map(function (u) {
    return fetch(u, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); });
  })).then(function (x) {
    if (A) A.mountSettings(document.getElementById("area-settings"), x[2].states);
    draw(x[0], x[1]);
    lists(x[1]);
    dim(x[1]);
    T.onChange(function () { lists(x[1]); });
    if (A) A.onChange(function () { lists(x[1]); dim(x[1]); });
  }).catch(function (e) {
    document.getElementById("map").replaceChildren(h("p", { "class": "empty", style: "padding:16px" }, ["The data could not be loaded (" + e.message + ")."]));
  });
})();
