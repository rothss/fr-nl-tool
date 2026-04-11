import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

function parseArgs(argv) {
  const opts = {
    cdpUrl: process.env.FR_CDP_URL || process.env.OPM_EDGE_CDP_URL || "http://127.0.0.1:9222",
    baseUrl: process.env.FR_BASE_URL || process.env.OPM_BASE_URL || "http://localhost:8075/webroot/decision",
    reportPath: "",
    outputFile: "",
    batchRoot: process.env.FR_BATCH_ROOT || process.env.OPM_BATCH_ROOT || "./fr_batch",
    waitMs: 5000,
    filtersJson: "{}",
    domProfileDir: process.env.FR_DOM_PROFILE_DIR || process.env.OPM_DOM_PROFILE_DIR || "./fr_mirror/search_index/dom_profiles",
  };
  const next = (i) => {
    if (i + 1 >= argv.length) throw new Error(`Missing value for ${argv[i]}`);
    return argv[i + 1];
  };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === "--cdp-url") {
      opts.cdpUrl = next(i);
      i += 1;
    } else if (a === "--base-url") {
      opts.baseUrl = next(i);
      i += 1;
    } else if (a === "--report-path") {
      opts.reportPath = next(i);
      i += 1;
    } else if (a === "--output-file") {
      opts.outputFile = next(i);
      i += 1;
    } else if (a === "--batch-root") {
      opts.batchRoot = next(i);
      i += 1;
    } else if (a === "--wait-ms") {
      opts.waitMs = Number(next(i));
      i += 1;
    } else if (a === "--filters-json") {
      opts.filtersJson = next(i);
      i += 1;
    } else if (a === "--dom-profile-dir") {
      opts.domProfileDir = next(i);
      i += 1;
    } else {
      throw new Error(`Unknown argument: ${a}`);
    }
  }
  if (!opts.reportPath) throw new Error("Missing --report-path");
  if (!opts.outputFile) throw new Error("Missing --output-file");
  return opts;
}

function loadPlaywright(batchRoot) {
  try {
    return require("playwright");
  } catch (_) {
    const fallback = path.join(batchRoot, "node_modules", "playwright");
    return require(fallback);
  }
}

function isZip(buf) {
  return buf && buf.length > 4 && buf[0] === 0x50 && buf[1] === 0x4b;
}

function normalizeText(s) {
  return String(s || "")
    .replace(/[（）()\s]/g, "")
    .replace(/[—–]/g, "-")
    .toLowerCase()
    .trim();
}

function widgetCandidates(filterKey) {
  const m = {
    flight_no: ["FLT_NO", "FLIGHT_NO", "FLIGHTNO", "HBH", "航班号"],
    flight_date: ["DATE", "DATE_S", "DATE_E", "STAT_DATE", "DT", "RQ", "航班日期", "日期"],
    segment: ["SEGMENT", "LEG", "ROUTE", "CITY_PAIR", "航段", "航线"],
    segment_text: ["SEGMENT", "LEG", "ROUTE", "CITY_PAIR", "航段", "航线"],
    company: ["COMP_CODE", "COMPANY", "COMP", "航司", "公司"],
    aircraft_type: ["AC_TYPE", "AIRCRAFT_TYPE", "机型", "FLEET"],
    depart_time: ["DEP_TIME", "TIME", "DEPTIME", "时刻", "起飞时刻"],
    rank_scope: ["TOP_BOTTOM", "RANK_SCOPE", "RANK_TYPE", "排序范围", "前后十", "前十后十", "十航班"],
    first_flight: ["FIRST_FLIGHT", "IS_FIRST_FLIGHT", "NEW_ROUTE", "新开航线", "首航", "是否首航"],
  };
  return m[filterKey] || [];
}

function fuzzyWidgetMatch(allNames, candidates) {
  const lowered = (allNames || []).map((x) => String(x || ""));
  for (const c of candidates) {
    const exact = lowered.find((n) => n === c);
    if (exact) return exact;
  }
  const candNorm = candidates.map((x) => normalizeText(x));
  for (const n of lowered) {
    const nn = normalizeText(n);
    if (candNorm.some((c) => c && (nn.includes(c) || c.includes(nn)))) {
      return n;
    }
  }
  return null;
}

function pickOptionValue(options, expectedText) {
  if (!Array.isArray(options) || options.length === 0) return null;
  const want = normalizeText(expectedText);
  if (!want) return null;
  const exact = options.find((o) => normalizeText(o.text || o.value || "") === want);
  if (exact) return exact.value || exact.text;
  const contains = options.find((o) => normalizeText(o.text || "").includes(want));
  if (contains) return contains.value || contains.text;
  return null;
}

function domProfileCacheFile(reportPath, domProfileDir) {
  const safe = Buffer.from(String(reportPath || ""), "utf8").toString("hex");
  return path.join(domProfileDir, `${safe}.json`);
}

function loadDomProfile(reportPath, domProfileDir) {
  try {
    const p = domProfileCacheFile(reportPath, domProfileDir);
    if (!fs.existsSync(p)) return null;
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (_) {
    return null;
  }
}

function saveDomProfile(reportPath, domProfileDir, data) {
  try {
    const p = domProfileCacheFile(reportPath, domProfileDir);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, JSON.stringify(data, null, 2), "utf8");
  } catch (_) {}
}

function labelCandidates(filterKey) {
  const m = {
    date_start: ["开始日期", "起始日期", "日期开始", "航班日期", "日期"],
    date_end: ["结束日期", "截止日期", "日期结束", "航班日期", "日期"],
    flight_date: ["航班日期", "日期"],
    company: ["航司", "公司"],
    flight_no: ["航班号"],
    aircraft_type: ["机型"],
    depart_time: ["时刻", "起飞时刻"],
    segment: ["航段", "航线", "城市对"],
    rank_scope: ["排名数", "排序范围", "前后十", "前十后十"],
    first_flight: ["首航", "是否首航", "新开航线"],
  };
  return m[filterKey] || [];
}

async function applyDomFallback(page, filters, reportPath, domProfileDir) {
  const cachedProfile = loadDomProfile(reportPath, domProfileDir);
  const result = await page.evaluate(
    async ({ filters, labelAliases, cachedProfile }) => {
      const norm = (s) =>
        String(s || "")
          .replace(/[：:（）()\s]/g, "")
          .replace(/[—–]/g, "-")
          .toLowerCase()
          .trim();
      const isVisible = (el) => {
        if (!el || !(el instanceof Element)) return false;
        const st = window.getComputedStyle(el);
        if (!st || st.display === "none" || st.visibility === "hidden") return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      };
      const textElements = Array.from(document.querySelectorAll("div, span, label, td"))
        .filter((el) => isVisible(el) && el.childElementCount === 0)
        .map((el) => ({
          el,
          text: String(el.innerText || el.textContent || "").trim(),
          rect: el.getBoundingClientRect(),
        }))
        .filter((it) => it.text && it.text.length <= 18);
      const controls = Array.from(document.querySelectorAll("input.fr-trigger-texteditor, input[type='text'], textarea, select"))
        .filter((el) => isVisible(el))
        .map((el) => ({ el, rect: el.getBoundingClientRect() }));

      const matchLabel = (control, keys) => {
        const wanted = (keys || []).map((k) => norm(k)).filter(Boolean);
        let best = null;
        for (const item of textElements) {
          const t = norm(item.text);
          if (!t || !wanted.some((w) => t.includes(w) || w.includes(t))) continue;
          const sameRow = Math.abs(item.rect.top - control.rect.top) <= 24;
          const leftSide = item.rect.right <= control.rect.left + 80;
          const above = item.rect.bottom <= control.rect.top + 12;
          if (!sameRow && !above) continue;
          if (!leftSide && !above) continue;
          const dx = Math.max(0, control.rect.left - item.rect.right);
          const dy = Math.abs(control.rect.top - item.rect.top);
          const score = dx + dy * 2;
          if (!best || score < best.score) best = { ...item, score };
        }
        return best;
      };

      const setTextLike = (el, value) => {
        if (!el) return false;
        try {
          el.focus();
          if ("value" in el) el.value = value;
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
          el.blur();
          return true;
        } catch (_) {
          return false;
        }
      };

      const planned = [];
      const dateStart =
        (typeof filters.date_start === "string" && filters.date_start) ||
        (Array.isArray(filters.flight_date) && filters.flight_date.length > 0 ? String(filters.flight_date[0]) : "");
      const dateEnd =
        (typeof filters.date_end === "string" && filters.date_end) ||
        (Array.isArray(filters.flight_date) && filters.flight_date.length > 0 ? String(filters.flight_date[0]) : "");
      if (dateEnd) planned.push({ key: "date_end", value: dateEnd });
      if (dateStart) planned.push({ key: "date_start", value: dateStart });
      if (filters.company) planned.push({ key: "company", value: String(filters.company) });
      if (filters.flight_no && Array.isArray(filters.flight_no) && filters.flight_no.length > 0) planned.push({ key: "flight_no", value: String(filters.flight_no[0]) });
      if (filters.aircraft_type) planned.push({ key: "aircraft_type", value: String(filters.aircraft_type) });
      if (filters.depart_time) planned.push({ key: "depart_time", value: String(filters.depart_time) });
      if (filters.segment_from && filters.segment_to) planned.push({ key: "segment", value: `${filters.segment_from}-${filters.segment_to}` });
      if (filters.rank_scope) planned.push({ key: "rank_scope", value: "10" });

      const usedControls = new Set();
      const applied = [];
      const learned = {};
      for (const item of planned) {
        const aliases = labelAliases[item.key] || [];
        let picked = null;
        const cached = cachedProfile && cachedProfile.fields ? cachedProfile.fields[item.key] : null;
        if (cached && Number.isInteger(cached.controlIndex) && controls[cached.controlIndex] && !usedControls.has(controls[cached.controlIndex].el)) {
          picked = { control: controls[cached.controlIndex], label: cached.labelText ? { text: cached.labelText } : null };
        }
        for (const control of controls) {
          if (picked) break;
          if (usedControls.has(control.el)) continue;
          const label = matchLabel(control, aliases);
          if (!label) continue;
          picked = { control, label };
          break;
        }
        if (!picked && item.key === "date_end") {
          const remaining = controls.filter((c) => !usedControls.has(c.el));
          if (remaining.length > 0) picked = { control: remaining[0], label: null };
        }
        if (!picked && item.key === "date_start") {
          const remaining = controls.filter((c) => !usedControls.has(c.el));
          if (remaining.length > 0) picked = { control: remaining[0], label: null };
        }
        if (!picked && item.key === "rank_scope") {
          const remaining = controls.filter((c) => !usedControls.has(c.el));
          if (remaining.length >= 2) picked = { control: remaining[1], label: null };
          else if (remaining.length > 0) picked = { control: remaining[0], label: null };
        }
        if (!picked) {
          applied.push({ field: item.key, ok: false, value: item.value, reason: "control_not_found" });
          continue;
        }
        const ok = setTextLike(picked.control.el, item.value);
        usedControls.add(picked.control.el);
        const controlIndex = controls.findIndex((c) => c.el === picked.control.el);
        learned[item.key] = {
          controlIndex,
          labelText: picked.label ? picked.label.text : null,
        };
        applied.push({
          field: item.key,
          ok,
          value: item.value,
          label: picked.label ? picked.label.text : null,
        });
      }
      await new Promise((resolve) => setTimeout(resolve, 400));
      const btn = Array.from(document.querySelectorAll("button")).find((b) => String(b.innerText || b.textContent || "").includes("查询"));
      if (!btn) {
        return { ok: false, reason: "query_button_missing", setResult: applied };
      }
      btn.click();
      await new Promise((resolve) => setTimeout(resolve, 4000));
      const g = window._g && window._g();
      return {
        ok: true,
        sid: g && g.currentSessionID,
        referer: location.href,
        servletURL: (g && g.servletURL) || (window.FR && window.FR.servletURL),
        setResult: applied,
        domProfile: {
          controlCount: controls.length,
          fields: learned,
        },
      };
    },
    {
      filters,
      labelAliases: {
        date_start: labelCandidates("date_start"),
        date_end: labelCandidates("date_end"),
        flight_date: labelCandidates("flight_date"),
        company: labelCandidates("company"),
        flight_no: labelCandidates("flight_no"),
        aircraft_type: labelCandidates("aircraft_type"),
        depart_time: labelCandidates("depart_time"),
        segment: labelCandidates("segment"),
        rank_scope: labelCandidates("rank_scope"),
        first_flight: labelCandidates("first_flight"),
      },
      cachedProfile,
    }
  );
  if (result && result.ok && result.domProfile && result.domProfile.fields) {
    saveDomProfile(reportPath, domProfileDir, result.domProfile);
  }
  return result;
}

async function run() {
  process.env.NO_PROXY = "127.0.0.1,localhost";
  process.env.no_proxy = "127.0.0.1,localhost";
  process.env.ALL_PROXY = "";
  process.env.all_proxy = "";

  const opts = parseArgs(process.argv.slice(2));
  const filters = JSON.parse(opts.filtersJson || "{}");
  const { chromium } = loadPlaywright(opts.batchRoot);
  const browser = await chromium.connectOverCDP(opts.cdpUrl);
  const context = browser.contexts()[0];
  if (!context) throw new Error(`No browser context from CDP: ${opts.cdpUrl}`);
  const page = await context.newPage();
  try {
    const viewUrl = `${opts.baseUrl}/view/form?viewlet=${encodeURIComponent(opts.reportPath)}&op=view`;
    await page.goto(viewUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
    await page.waitForTimeout(opts.waitMs);

    const baseMeta = await page.evaluate(() => {
      const g = window._g && window._g();
      if (!g || !g.parameterEl) return { ok: false, reason: "parameterEl_missing" };
      const pe = g.parameterEl;
      const names = new Set();
      try {
        if (pe.widgetNameMap) {
          Object.keys(pe.widgetNameMap).forEach((k) => names.add(k));
        }
      } catch (_) {}
      try {
        const ws = typeof pe.getWidgets === "function" ? pe.getWidgets() : [];
        for (const w of ws || []) {
          if (w && typeof w.getName === "function") names.add(w.getName());
          if (w && w.options && w.options.name) names.add(w.options.name);
        }
      } catch (_) {}
      return {
        ok: true,
        sid: g.currentSessionID,
        referer: location.href,
        servletURL: g.servletURL || (window.FR && window.FR.servletURL),
        widgetNames: Array.from(names),
      };
    });
    if (!baseMeta.ok) throw new Error(baseMeta.reason || "missing_parameter_panel");

    const resolved = [];
    const setPayload = {};
    const allNames = baseMeta.widgetNames || [];
    const dateStart =
      (typeof filters.date_start === "string" && filters.date_start) ||
      (Array.isArray(filters.flight_date) && filters.flight_date.length > 0 ? String(filters.flight_date[0]) : "");
    const dateEnd =
      (typeof filters.date_end === "string" && filters.date_end) ||
      (Array.isArray(filters.flight_date) && filters.flight_date.length > 0 ? String(filters.flight_date[0]) : "");
    if (dateStart || dateEnd) {
      const n1 = fuzzyWidgetMatch(allNames, ["DATE_S", "START_DATE", ...widgetCandidates("flight_date")]);
      const n2 = fuzzyWidgetMatch(allNames, ["DATE_E", "END_DATE", ...widgetCandidates("flight_date")]);
      if (n1) setPayload[n1] = String(dateStart || dateEnd);
      if (n2) setPayload[n2] = String(dateEnd || dateStart);
      if (!n1 && !n2) {
        const ns = fuzzyWidgetMatch(allNames, widgetCandidates("flight_date"));
        if (ns) setPayload[ns] = String(dateEnd || dateStart);
      }
    }
    if (filters.flight_no && Array.isArray(filters.flight_no) && filters.flight_no.length > 0) {
      const n = fuzzyWidgetMatch(allNames, widgetCandidates("flight_no"));
      if (n) setPayload[n] = String(filters.flight_no[0]);
    }
    if (filters.company) {
      const n = fuzzyWidgetMatch(allNames, widgetCandidates("company"));
      if (n) setPayload[n] = String(filters.company);
    }
    if (filters.aircraft_type) {
      const n = fuzzyWidgetMatch(allNames, widgetCandidates("aircraft_type"));
      if (n) setPayload[n] = String(filters.aircraft_type);
    }
    if (filters.depart_time) {
      const n = fuzzyWidgetMatch(allNames, widgetCandidates("depart_time"));
      if (n) setPayload[n] = String(filters.depart_time);
    }
    if (filters.segment_from && filters.segment_to) {
      const n = fuzzyWidgetMatch(allNames, widgetCandidates("segment"));
      if (n) setPayload[n] = `${filters.segment_from}-${filters.segment_to}`;
    }
    if (filters.rank_scope) {
      const n = fuzzyWidgetMatch(allNames, widgetCandidates("rank_scope"));
      if (n) setPayload[n] = String(filters.rank_scope);
    }
    if (filters.first_flight) {
      const n = fuzzyWidgetMatch(allNames, widgetCandidates("first_flight"));
      if (n) setPayload[n] = "首航";
    }

    const mappedEntries = Object.entries(setPayload);
    for (const [name, rawValue] of mappedEntries) {
      let finalValue = rawValue;
      try {
        const r = await context.request.post(`${opts.baseUrl}/view/form?op=widget&widgetname=${encodeURIComponent(name)}`, {
          headers: {
            referer: baseMeta.referer,
            sessionid: baseMeta.sid,
          },
          form: { reload: "true" },
          timeout: 30000,
        });
        const txt = await r.text();
        const arr = JSON.parse(txt);
        const picked = pickOptionValue(arr, String(rawValue));
        if (picked !== null && picked !== undefined && String(picked).length > 0) {
          finalValue = picked;
        }
      } catch (_) {}
      resolved.push({ widget: name, value: finalValue });
    }

    let commitMeta;
    if (resolved.length === 0) {
      commitMeta = await applyDomFallback(page, filters, opts.reportPath, opts.domProfileDir);
    } else {
      commitMeta = await page.evaluate(async ({ pairs }) => {
        const g = window._g && window._g();
        if (!g || !g.parameterEl) return { ok: false, reason: "parameterEl_missing" };
        const pe = g.parameterEl;
        const result = [];
        const setOne = (name, value) => {
          const w = pe.getWidgetByName ? pe.getWidgetByName(name) : null;
          if (!w) return false;
          try {
            if (typeof w.setValue === "function") {
              w.setValue(value);
              return true;
            }
          } catch (_) {}
          try {
            if (typeof w.setText === "function") {
              w.setText(value);
              return true;
            }
          } catch (_) {}
          return false;
        };
        for (const p of pairs || []) {
          const ok = setOne(p.widget, p.value);
          result.push({ ...p, ok });
        }
        await new Promise((resolve) => {
          let done = false;
          const fin = () => {
            if (!done) {
              done = true;
              resolve();
            }
          };
          try {
            g.parameterCommit(() => setTimeout(fin, 1200));
          } catch (_) {
            fin();
          }
          setTimeout(fin, 10000);
        });
        return {
          ok: true,
          sid: g.currentSessionID,
          referer: location.href,
          servletURL: g.servletURL || (window.FR && window.FR.servletURL),
          setResult: result,
        };
      }, { pairs: resolved });
    }
    if (!commitMeta.ok) throw new Error(commitMeta.reason || "failed_commit");
    if (!commitMeta.servletURL) throw new Error("servlet_url_missing");

    const baseOrigin = new URL(opts.baseUrl).origin;
    let servletUrl = commitMeta.servletURL;
    if (!servletUrl.startsWith("http")) {
      servletUrl = servletUrl.startsWith("/")
        ? `${baseOrigin}${servletUrl}`
        : `${opts.baseUrl.replace(/\/+$/, "")}/${servletUrl}`;
    }
    const resp = await context.request.post(servletUrl, {
      headers: {
        referer: commitMeta.referer,
        sessionid: commitMeta.sid,
      },
      form: {
        op: "export",
        sessionID: commitMeta.sid,
        format: "excel",
        extype: "simple",
      },
      timeout: 120000,
    });
    const body = Buffer.from(await resp.body());
    if (!isZip(body)) {
      const errPath = `${opts.outputFile}.error.html`;
      fs.mkdirSync(path.dirname(errPath), { recursive: true });
      fs.writeFileSync(errPath, body);
      throw new Error(`export_not_zip status=${resp.status()} errorSaved=${errPath}`);
    }
    fs.mkdirSync(path.dirname(opts.outputFile), { recursive: true });
    fs.writeFileSync(opts.outputFile, body);
    console.log(
      JSON.stringify(
        {
          ok: true,
          outputFile: opts.outputFile,
          bytes: body.length,
          status: resp.status(),
          widgetNames: allNames,
          mapped: resolved,
          setResult: commitMeta.setResult || [],
        },
        null,
        2
      )
    );
  } finally {
    try {
      await page.close();
    } catch (_) {}
    await browser.close();
  }
}

run().catch((err) => {
  console.error(err.stack || err);
  process.exit(1);
});
