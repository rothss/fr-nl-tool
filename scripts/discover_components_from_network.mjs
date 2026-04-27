import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);

function parseArgs(argv) {
  const opts = {
    cdpUrl: process.env.FR_CDP_URL || process.env.OPM_EDGE_CDP_URL || "http://127.0.0.1:9222",
    baseUrl: process.env.FR_BASE_URL || process.env.OPM_BASE_URL || "http://localhost:8075/webroot/decision",
    batchRoot: process.env.FR_BATCH_ROOT || process.env.OPM_BATCH_ROOT || "./fr_batch",
    reportPath: "",
    waitMs: 25000,
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
    } else if (a === "--batch-root") {
      opts.batchRoot = next(i);
      i += 1;
    } else if (a === "--report-path") {
      opts.reportPath = next(i);
      i += 1;
    } else if (a === "--wait-ms") {
      opts.waitMs = Number(next(i));
      i += 1;
    } else {
      throw new Error(`Unknown argument: ${a}`);
    }
  }
  if (!opts.reportPath) throw new Error("Missing --report-path");
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

function decodeMaybeTwice(v) {
  let x = String(v || "");
  try {
    x = decodeURIComponent(x);
  } catch (_) {}
  try {
    x = decodeURIComponent(x);
  } catch (_) {}
  return x;
}

function parseFromUrl(rawUrl) {
  const out = { raw_url: rawUrl, viewlet: "", op: "", cmd: "", type: "", source: "url" };
  let u;
  try {
    u = new URL(rawUrl);
  } catch (_) {
    return null;
  }
  const viewletRaw = u.searchParams.get("viewlet");
  if (!viewletRaw) return null;
  const viewlet = decodeMaybeTwice(viewletRaw);
  out.viewlet = viewlet;
  out.op = String(u.searchParams.get("op") || "");
  out.cmd = String(u.searchParams.get("cmd") || "");
  if (viewlet.endsWith(".cpt")) out.type = "cpt";
  else if (viewlet.endsWith(".frm")) out.type = "frm";
  else out.type = "other";
  return out;
}

async function run() {
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
  const hitMap = new Map();
  const addHit = (obj) => {
    if (!obj || !obj.viewlet) return;
    const key = `${obj.viewlet}::${obj.op}::${obj.cmd}`;
    if (!hitMap.has(key)) hitMap.set(key, obj);
  };
  page.on("request", (req) => {
    const info = parseFromUrl(req.url());
    if (info) addHit(info);
  });
  try {
    const viewUrl = `${opts.baseUrl}/view/form?viewlet=${encodeURIComponent(opts.reportPath)}&op=view`;
    await page.goto(viewUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
    await page.waitForTimeout(opts.waitMs);
    const clientLinks = await page.evaluate(() => {
      const out = [];
      const html = String(document.documentElement?.innerHTML || "");
      const re = /viewlet=([^&"'\\s>]+)/g;
      let m;
      while ((m = re.exec(html)) !== null) {
        out.push(m[1]);
      }
      return Array.from(new Set(out)).slice(0, 2000);
    });
    for (const v of clientLinks) {
      const fakeUrl = `${opts.baseUrl}/view/report?viewlet=${v}`;
      const info = parseFromUrl(fakeUrl);
      if (info) {
        info.source = "html";
        addHit(info);
      }
    }
    const all = Array.from(hitMap.values());
    const cpt = all.filter((x) => x.type === "cpt").sort((a, b) => a.viewlet.localeCompare(b.viewlet, "zh-CN"));
    const frm = all.filter((x) => x.type === "frm").sort((a, b) => a.viewlet.localeCompare(b.viewlet, "zh-CN"));
    console.log(
      JSON.stringify(
        {
          ok: true,
          report_path: opts.reportPath,
          observed_total: all.length,
          cpt_count: cpt.length,
          frm_count: frm.length,
          cpt_viewlets: cpt.map((x) => x.viewlet),
          frm_viewlets: frm.map((x) => x.viewlet),
          all,
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
