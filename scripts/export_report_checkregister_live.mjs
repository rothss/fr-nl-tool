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

    const meta = await page.evaluate(() => {
      const g = window._g && window._g();
      if (!g) return { ok: false, reason: "g_missing" };
      const names = new Set();
      try {
        const pe = g.parameterEl;
        if (pe && pe.widgetNameMap) Object.keys(pe.widgetNameMap).forEach((k) => names.add(k));
        const ws = pe && pe.getWidgets ? pe.getWidgets() : [];
        for (const w of ws || []) {
          if (w && typeof w.getName === "function") names.add(w.getName());
          if (w && w.options && w.options.name) names.add(w.options.name);
        }
      } catch (_) {}
      return { ok: true, sid: g.currentSessionID, widgetNames: Array.from(names), referer: location.href };
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

    await page.evaluate(async ({ setPayload }) => {
      const g = window._g && window._g();
      if (!g || !g.parameterEl) return;
      const pe = g.parameterEl;
      const setOne = (name, value) => {
        const w = pe.getWidgetByName ? pe.getWidgetByName(name) : null;
        if (!w) return;
        try {
          if (typeof w.setValue === "function") w.setValue(value);
          else if (typeof w.setText === "function") w.setText(value);
        } catch (_) {}
      };
      for (const [k, v] of Object.entries(setPayload || {})) setOne(k, v);
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
    }, { setPayload });

    const sid = meta.sid;
    const headers = {
      "x-requested-with": "XMLHttpRequest",
      referer: meta.referer,
      sessionid: sid,
    };
    await context.request.get(`${opts.baseUrl}/view/form?op=export&cmd=check_register`, {
      headers,
      timeout: 120000,
    });
    await context.request.post(`${opts.baseUrl}/export/check/font`, {
      form: { format: "excel" },
      headers: { referer: meta.referer },
      timeout: 120000,
    });
    const resp = await context.request.post(`${opts.baseUrl}/view/form`, {
      form: {
        op: "export",
        sessionID: sid,
        format: "excel",
        extype: "simple",
      },
      headers: {
        "content-type": "application/x-www-form-urlencoded",
        referer: meta.referer,
        sessionid: sid,
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
          setPayload,
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

