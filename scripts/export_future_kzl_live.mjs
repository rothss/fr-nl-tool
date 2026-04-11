import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

function parseArgs(argv) {
  const opts = {
    cdpUrl: process.env.OPM_EDGE_CDP_URL || "http://127.0.0.1:9333",
    baseUrl: process.env.OPM_BASE_URL || "https://opm.hnair.net/webroot/decision",
    reportPath: "doc/Fdjt/市场监督/客座率监控/未来航班客座率票价分析-PG库.cpt",
    outputFile: "C:/Users/ZhuanZ/opm_mirror/包干航线/未来航班客座率票价分析.xlsx",
    batchRoot: process.env.OPM_BATCH_ROOT || "C:/Users/ZhuanZ/opm_batch",
    waitMs: 6000,
    dateStart: "",
    dateEnd: "",
    flightNo: "",
    segmentFrom: "",
    segmentTo: "",
    segmentText: "",
    compCode: "",
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
    } else if (a === "--date-start") {
      opts.dateStart = next(i);
      i += 1;
    } else if (a === "--date-end") {
      opts.dateEnd = next(i);
      i += 1;
    } else if (a === "--flight-no") {
      opts.flightNo = next(i);
      i += 1;
    } else if (a === "--segment-from") {
      opts.segmentFrom = next(i);
      i += 1;
    } else if (a === "--segment-to") {
      opts.segmentTo = next(i);
      i += 1;
    } else if (a === "--segment-text") {
      opts.segmentText = next(i);
      i += 1;
    } else if (a === "--comp-code") {
      opts.compCode = next(i);
      i += 1;
    } else {
      throw new Error(`Unknown argument: ${a}`);
    }
  }
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
    .trim();
}

function pickSegmentOption(options, segmentFrom, segmentTo, segmentText) {
  const from = normalizeText(segmentFrom);
  const to = normalizeText(segmentTo);
  const seg = normalizeText(segmentText);
  if (!Array.isArray(options) || options.length === 0) return null;

  if (seg) {
    const hit = options.find((o) => normalizeText(o.text).includes(seg));
    if (hit) return hit;
  }
  if (from && to) {
    const hit = options.find((o) => {
      const t = normalizeText(o.text);
      const i = t.indexOf(from);
      const j = t.indexOf(to);
      return i >= 0 && j > i;
    });
    if (hit) return hit;
  }
  return null;
}

function looksLikeLoginPage(url, title, bodyText) {
  const u = String(url || "");
  const t = String(title || "");
  const body = String(bodyText || "");
  return (
    u.includes("login.hnagroup.com") ||
    t.includes("统一登录平台") ||
    body.includes("扫码登录") ||
    body.includes("账号登录")
  );
}

async function run() {
  // Ensure local CDP access is not routed by proxy.
  process.env.NO_PROXY = "127.0.0.1,localhost";
  process.env.no_proxy = "127.0.0.1,localhost";
  process.env.ALL_PROXY = "";
  process.env.all_proxy = "";

  const opts = parseArgs(process.argv.slice(2));
  const { chromium } = loadPlaywright(opts.batchRoot);
  const browser = await chromium.connectOverCDP(opts.cdpUrl);
  const context = browser.contexts()[0];
  if (!context) throw new Error(`No browser context from CDP: ${opts.cdpUrl}`);

  const page = await context.newPage();
  try {
    const viewUrl = `${opts.baseUrl}/view/form?viewlet=${encodeURIComponent(opts.reportPath)}&op=view`;
    await page.goto(viewUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
    await page.waitForTimeout(opts.waitMs);

    const pageState = await page.evaluate(() => ({
      url: location.href,
      title: document.title,
      bodyText: document.body ? document.body.innerText.slice(0, 400) : "",
      hasG: !!(window._g && window._g()),
      hasParameterEl: !!(window._g && window._g() && window._g().parameterEl),
    }));
    if (looksLikeLoginPage(pageState.url, pageState.title, pageState.bodyText)) {
      throw new Error(`login_required url=${pageState.url} title=${pageState.title}`);
    }

    const sidMeta = await page.evaluate(() => {
      const g = window._g && window._g();
      if (!g || !g.parameterEl) return { ok: false, reason: "parameterEl_missing" };
      return { ok: true, sid: g.currentSessionID, referer: location.href };
    });
    if (!sidMeta.ok) throw new Error(sidMeta.reason || "missing_sid");

    // Query SEGMENT widget options remotely so we can map "海口到上海" to SEGMENT value code.
    let selectedSegment = null;
    if (opts.segmentFrom || opts.segmentTo || opts.segmentText) {
      const segResp = await context.request.post(`${opts.baseUrl}/view/form?op=widget&widgetname=SEGMENT`, {
        headers: {
          referer: sidMeta.referer,
          sessionid: sidMeta.sid,
        },
        form: { reload: "true" },
        timeout: 60000,
      });
      const segText = await segResp.text();
      let segOptions = [];
      try {
        segOptions = JSON.parse(segText);
      } catch (_) {
        segOptions = [];
      }
      selectedSegment = pickSegmentOption(segOptions, opts.segmentFrom, opts.segmentTo, opts.segmentText);
    }

    const meta = await page.evaluate(
      async ({ dateStart, dateEnd, flightNo, compCode, segmentValue, segmentText }) => {
      const g = window._g && window._g();
      if (!g || !g.parameterEl) return { ok: false, reason: "parameterEl_missing" };
      const pe = g.parameterEl;

      const setWidget = (name, value) => {
        if (!value) return false;
        const w = pe.getWidgetByName ? pe.getWidgetByName(name) : null;
        if (!w) return false;
        if (typeof w.setValue === "function") {
          w.setValue(value);
          return true;
        }
        if (typeof w.setText === "function") {
          w.setText(value);
          return true;
        }
        return false;
      };

      const setResult = {};
      setResult.DATE_S = setWidget("DATE_S", dateStart);
      setResult.DATE_E = setWidget("DATE_E", dateEnd);
      setResult.FLT_NO = setWidget("FLT_NO", flightNo);
      setResult.COMP_CODE = setWidget("COMP_CODE", compCode);
      if (segmentValue) {
        setResult.SEGMENT = setWidget("SEGMENT", segmentValue);
      } else if (segmentText) {
        setResult.SEGMENT = setWidget("SEGMENT", segmentText);
      } else {
        setResult.SEGMENT = false;
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
        servletURL: g.servletURL || (window.FR && window.FR.servletURL),
        referer: location.href,
        setResult,
      };
    },
      {
        dateStart: opts.dateStart,
        dateEnd: opts.dateEnd,
        flightNo: opts.flightNo,
        compCode: opts.compCode,
        segmentValue: selectedSegment ? selectedSegment.value : "",
        segmentText: selectedSegment ? selectedSegment.text : opts.segmentText,
      }
    );

    if (!meta.ok) throw new Error(meta.reason || "failed_to_prepare_report");
    if (!meta.servletURL) throw new Error("servlet_url_missing");
    const baseOrigin = new URL(opts.baseUrl).origin;
    let servletUrl = meta.servletURL;
    if (!servletUrl.startsWith("http")) {
      if (servletUrl.startsWith("/")) {
        servletUrl = `${baseOrigin}${servletUrl}`;
      } else {
        servletUrl = `${opts.baseUrl.replace(/\/+$/, "")}/${servletUrl}`;
      }
    }

    const resp = await context.request.post(servletUrl, {
      headers: {
        referer: meta.referer,
        sessionid: meta.sid,
      },
      form: {
        op: "export",
        sessionID: meta.sid,
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
          segmentMatched: selectedSegment || null,
          setResult: meta.setResult || {},
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
