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
  function table(head, rows) {
    return h("table", null, [h("thead", null, [h("tr", null, head.map(function (x) { return h("th", null, [x]); }))]),
      h("tbody", null, rows.map(function (r) { return h("tr", null, r.map(function (c) {
        return c && c.td ? h("td", { "class": c.cls }, [c.td]) : h("td", null, [c]); })); }))]);
  }

  // Wheel zoom stays off until the reader clicks the map, so scrolling the page never gets trapped in it.
  var map = L.map("map", { worldCopyJump: true, minZoom: 1, maxZoom: 8, zoomSnap: 0.5, scrollWheelZoom: false })
    .setView([24, 20], 2);
  map.once("click", function () { map.scrollWheelZoom.enable(); });
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution("Natural Earth · State Dept · EASA · NGA · FAA · UK FCDO (OGL v3.0)");
  var layers = {};

  function levelColor(n) { return n ? css("--l" + n) : css("--land"); }

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
        .bindTooltip(tip(p.title + (p.until ? "\nUntil " + when(p.until) : "") + (key ? "\nUnusual: more ground stops at once than normal" : "")))
        .addTo(layers.faa);
    });
    layers.faa.addTo(map);

    layers.tfr = L.geoJSON({ type: "FeatureCollection", features: (d.tfr || []).map(function (t) {
      return { type: "Feature", geometry: t.geometry, properties: t }; }) }, {
      style: function (f) { var key = f.properties.tier === "anomaly";
        return { color: key ? css("--tfr-key") : css("--tfr"), weight: key ? 2 : 1.4, fillOpacity: key ? 0.18 : 0.1 }; },
      onEachFeature: function (f, lyr) {
        var t = f.properties;
        lyr.bindTooltip(tip(t.title + "\n" + [t.floor, t.ceiling].filter(Boolean).join(" to ")
          + (t.effective ? "\nFrom " + when(t.effective) : "") + (t.until ? "\nUntil " + when(t.until) : "")
          + (t.tier === "anomaly" ? "\nNew in the last 72 hours" : "")), { sticky: true });
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
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--nav-key") }), "launch, military, mines, GNSS"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--nav") }), "other maritime warnings"]),
      h("span", null, [h("span", { "class": "posture-icon", style: "display:inline-block;padding:0 4px;margin-right:4px" }, ["OD"]), "embassy status"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--faa") }), "FAA airport program"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--faa-key") }), "unusual number of ground stops"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--tfr") }), "FAA flight restriction"]),
      h("span", null, [h("span", { "class": "dt", style: "background:" + css("--tfr-key") }), "new launch or security restriction"]));
  }

  function lists(d) {
    var post = d.advisories.filter(function (a) { return POSTURE[a.posture]; });
    document.getElementById("posture").replaceChildren(post.length ? table(["Country", "Status", "What the advisory says"],
      post.map(function (a) { return [link(a.link, a.name), POSTURE[a.posture][1], a.sentence || "—"]; }))
      : h("p", { "class": "empty" }, ["No post is on authorized or ordered departure or has suspended operations."]));

    var cz = d.czibs.slice().sort(function (x, y) { return (x.valid_until || "9").localeCompare(y.valid_until || "9"); });
    document.getElementById("czibs").replaceChildren(table(["Bulletin", "Airspace", "Valid until"],
      cz.map(function (b) { return [b.number, b.subject, { td: day(b.valid_until), cls: "num" }]; })));

    var ch = d.changes;
    document.getElementById("changes").replaceChildren(ch.length ? table(["When", "Where", "Change"], ch.map(function (c) {
      var what = c.kind === "level" ? "Advisory level " + c.from + " to " + c.to
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
        return [FAA_WORD[p.program] + (p.tier === "anomaly" ? " (unusual)" : ""),
          p.airport + (p.airport_name ? " " + p.airport_name : ""), what, { td: when(p.until), cls: "num" }]; }))
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

    var tf = (d.tfr || []).slice().sort(function (x, y) {
      return (y.tier === "anomaly") - (x.tier === "anomaly") || (x.effective || "").localeCompare(y.effective || ""); });
    document.getElementById("tfrs").replaceChildren(tf.length ? table(["NOTAM", "Type", "Where", "From", "Until"],
      tf.map(function (t) {
        var where = t.title.replace(/^FAA TFR [^:]+: /, "");
        return [link(t.link, t.notam_id), String(t.type || "").toLowerCase() + (t.tier === "anomaly" ? " (new)" : ""), where,
          { td: when(t.effective), cls: "num" }, { td: when(t.until), cls: "num" }]; }))
      : h("p", { "class": "empty" }, [(d.health["faa-tfr"] || {}).state === "fresh"
          ? "The FAA lists no flight restriction with an area." : "No current FAA TFR data: see Sources below."]));

    var hi = d.advisories.filter(function (a) { return a.level >= 3; })
      .sort(function (x, y) { return y.level - x.level || x.name.localeCompare(y.name); });
    document.getElementById("levels").replaceChildren(table(["Level", "Place", "Advice"], hi.map(function (a) {
      return [{ td: h("span", { "class": "lvl lvl-" + a.level }, [a.level]) }, link(a.link, a.name), a.level_text]; })));

    var names = { "state-travel-advisories": "State Department travel advisories", "us-embassy-alerts": "US embassy alerts",
      "easa-czib": "EASA conflict-zone bulletins", "nga-navwarnings": "NGA warnings to mariners",
      "faa-nas-status": "FAA airport status (ground stops, delay programs, closures)",
      "faa-tfr": "FAA temporary flight restrictions", "uk-fcdo-travel-advice": "UK FCDO foreign travel advice" };
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
  Promise.all(["geo/world.json", "data/map.json"].map(function (u) {
    return fetch(u, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); });
  })).then(function (x) {
    draw(x[0], x[1]);
    lists(x[1]);
    T.onChange(function () { lists(x[1]); });
  }).catch(function (e) {
    document.getElementById("map").replaceChildren(h("p", { "class": "empty", style: "padding:16px" }, ["The data could not be loaded (" + e.message + ")."]));
  });
})();
