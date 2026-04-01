import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

function parseArgs(argv) {
  const opts = {
    cdpUrl: process.env.OPM_EDGE_CDP_URL || "http://127.0.0.1:9333",
    baseUrl: process.env.OPM_BASE_URL || "https://opm.hnair.net/webroot/decision",
    reportPath: "",
    outputFile: "",
    batchRoot: process.env.OPM_BATCH_ROOT || "C:/Users/ZhuanZ/opm_batch",
    waitMs: 8000,
    filtersJson: "{}",
    componentKeyword: "",
    extype: "simple",
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
    } else if (a === "--component-keyword") {
      opts.componentKeyword = next(i);
      i += 1;
    } else if (a === "--extype") {
      opts.extype = next(i);
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

function normalizeText(s) {
  return String(s || "")
    .replace(/[（）()\s]/g, "")
    .replace(/[—–]/g, "-")
    .toLowerCase()
    .trim();
}

function widgetCandidates(filterKey) {
  const m = {
    flight_date: ["DATE", "DATE_S", "DATE_E", "STAT_DATE", "DT", "RQ", "航班日期", "日期"],
    company: ["COMP_CODE", "COMPANY", "COMP", "航司", "公司", "航司名称", "公司名称"],
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

async function waitForReportReady(page, timeoutMs = 120000) {
  const started = Date.now();
  let stableRounds = 0;
  while (Date.now() - started < timeoutMs) {
    const state = await page.evaluate(() => {
      const text = String((document.body && document.body.innerText) || "");
      const busyText = /正在处理|请等待|加载中/.test(text);
      const g = window._g && window._g();
      if (!g) return { ok: false, reason: "g_missing", busyText };
      const reports = [];
      for (let i = 0; i < 120; i += 1) {
        const name = `report${i}`;
        try {
          const w = g.getWidgetByName ? g.getWidgetByName(name) : null;
          if (!w) continue;
          reports.push({
            name,
            hasReport: !!w.report,
            hasData: !!w.dataPageResult,
            loading: w._loading,
            canExport: typeof w.exportReportToExcel === "function",
          });
        } catch (_) {}
      }
      const hasReport = reports.length > 0;
      const hasLoadedExportable = reports.some(
        (r) => r.canExport && r.hasReport && r.hasData && !r.loading
      );
      const allNotLoading = reports.every((r) => !r.loading);
      return { ok: true, busyText, hasReport, hasLoadedExportable, allNotLoading, reports };
    });

    if (state && state.ok && state.hasReport && state.hasLoadedExportable && state.allNotLoading && !state.busyText) {
      stableRounds += 1;
      if (stableRounds >= 2) {
        return state;
      }
    } else {
      stableRounds = 0;
    }
    await page.waitForTimeout(1500);
  }
  const finalState = await page.evaluate(() => {
    const g = window._g && window._g();
    const reports = [];
    if (g) {
      for (let i = 0; i < 120; i += 1) {
        const name = `report${i}`;
        try {
          const w = g.getWidgetByName ? g.getWidgetByName(name) : null;
          if (!w) continue;
          reports.push({
            name,
            hasReport: !!w.report,
            hasData: !!w.dataPageResult,
            loading: w._loading,
            canExport: typeof w.exportReportToExcel === "function",
          });
        } catch (_) {}
      }
    }
    const body = String((document.body && document.body.innerText) || "");
    return { reports, bodyTextHead: body.slice(0, 2000) };
  });
  throw new Error(`report_not_ready_timeout: ${JSON.stringify(finalState)}`);
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
    const readyState = await waitForReportReady(page, 120000);

    const meta = await page.evaluate(() => {
      const g = window._g && window._g();
      if (!g) return { ok: false, reason: "g_missing" };
      const names = new Set();
      try {
        if (g.parameterEl && g.parameterEl.widgetNameMap) {
          Object.keys(g.parameterEl.widgetNameMap).forEach((k) => names.add(k));
        }
      } catch (_) {}
      try {
        for (let i = 0; i < 80; i += 1) {
          const n = `report${i}`;
          const w = g.getWidgetByName ? g.getWidgetByName(n) : null;
          if (w) names.add(n);
        }
      } catch (_) {}
      return { ok: true, sid: g.currentSessionID, widgetNames: Array.from(names) };
    });
    if (!meta.ok) throw new Error(meta.reason || "meta_failed");

    const setPayload = {};
    const allNames = meta.widgetNames || [];
    const dateStart = (typeof filters.date_start === "string" && filters.date_start) || "";
    const dateEnd = (typeof filters.date_end === "string" && filters.date_end) || "";
    if (dateStart || dateEnd) {
      const n1 = fuzzyWidgetMatch(allNames, ["DATE_S", "START_DATE", ...widgetCandidates("flight_date")]);
      const n2 = fuzzyWidgetMatch(allNames, ["DATE_E", "END_DATE", ...widgetCandidates("flight_date")]);
      if (n1) setPayload[n1] = String(dateStart || dateEnd);
      if (n2) setPayload[n2] = String(dateEnd || dateStart);
    }
    if (filters.company) {
      const n = fuzzyWidgetMatch(allNames, widgetCandidates("company"));
      if (n) setPayload[n] = String(filters.company);
    }

    const commit = await page.evaluate(async ({ setPayload }) => {
      const g = window._g && window._g();
      if (!g) return { ok: false, reason: "g_missing" };
      const pe = g.parameterEl;
      const setResult = [];
      if (pe) {
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
        for (const [k, v] of Object.entries(setPayload || {})) {
          setResult.push({ widget: k, ok: setOne(k, v), value: v });
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
      }

      const cands = [];
      for (let i = 0; i < 80; i += 1) {
        const name = `report${i}`;
        try {
          const w = g.getWidgetByName ? g.getWidgetByName(name) : null;
          if (!w) continue;
          const canExport = typeof w.exportReportToExcel === "function";
          const title = String((w.options && (w.options.text || w.options.title || w.options.widgetName)) || "");
          cands.push({ name, title, canExport });
        } catch (_) {}
      }
      return { ok: true, setResult, cands };
    }, { setPayload });
    if (!commit.ok) throw new Error(commit.reason || "commit_failed");

    const keyword = normalizeText(opts.componentKeyword);
    const cands = (commit.cands || []).filter((x) => x && x.canExport);
    if (!cands.length) throw new Error("no_exportable_report_component");
    let picked = cands[0];
    if (keyword) {
      const hit = cands.find((c) => normalizeText(c.name).includes(keyword) || normalizeText(c.title).includes(keyword));
      if (hit) picked = hit;
    }

    const downloadPromise = page.waitForEvent("download", { timeout: 120000 });
    await page.evaluate(({ name, extype }) => {
      const g = window._g && window._g();
      const w = g && g.getWidgetByName ? g.getWidgetByName(name) : null;
      if (!w || typeof w.exportReportToExcel !== "function") throw new Error("component_export_not_supported");
      w.exportReportToExcel(extype || "simple");
    }, { name: picked.name, extype: opts.extype || "simple" });

    const download = await downloadPromise;
    fs.mkdirSync(path.dirname(opts.outputFile), { recursive: true });
    await download.saveAs(opts.outputFile);
    const st = fs.statSync(opts.outputFile);
    console.log(
      JSON.stringify(
        {
          ok: true,
          outputFile: opts.outputFile,
          bytes: st.size,
          picked,
          cands,
          setResult: commit.setResult || [],
          readyState,
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
