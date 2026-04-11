import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);

function parseArgs(argv) {
  const opts = {
    cdpUrl: process.env.FR_CDP_URL || process.env.OPM_EDGE_CDP_URL || "http://127.0.0.1:9222",
    batchRoot: process.env.FR_BATCH_ROOT || process.env.OPM_BATCH_ROOT || "./fr_batch",
    componentUrl: "",
    waitMs: 5000,
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
    } else if (a === "--batch-root") {
      opts.batchRoot = next(i);
      i += 1;
    } else if (a === "--component-url") {
      opts.componentUrl = next(i);
      i += 1;
    } else if (a === "--wait-ms") {
      opts.waitMs = Number(next(i));
      i += 1;
    } else {
      throw new Error(`Unknown argument: ${a}`);
    }
  }
  if (!opts.componentUrl) throw new Error("Missing --component-url");
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

function toRowsWithHeader(rawRows) {
  const rows = (rawRows || []).filter((r) => Array.isArray(r) && r.some((x) => String(x || "").trim()));
  if (!rows.length) return { headers: [], rows: [] };
  let headerIdx = -1;
  for (let i = 0; i < rows.length; i += 1) {
    const r = rows[i].map((x) => String(x || "").trim());
    const t = r.join("|");
    if (t.includes("同比") && (t.includes("排名") || t.includes("航司"))) {
      headerIdx = i;
      break;
    }
  }
  if (headerIdx < 0) {
    headerIdx = rows.findIndex((r) => r.length >= 4);
  }
  if (headerIdx < 0) return { headers: [], rows: [] };
  const headers = rows[headerIdx].map((x) => String(x || "").trim()).filter(Boolean);
  const data = [];
  for (let i = headerIdx + 1; i < rows.length; i += 1) {
    const r = rows[i].map((x) => String(x || "").trim()).filter(Boolean);
    if (!r.length) continue;
    if (r.join("").includes("合计")) continue;
    data.push(r);
  }
  const out = [];
  for (const r of data) {
    const obj = {};
    if (r.length === headers.length + 1) {
      obj["代码"] = r[0];
      for (let i = 0; i < headers.length; i += 1) obj[headers[i] || `col_${i + 1}`] = r[i + 1] || "";
    } else {
      for (let i = 0; i < Math.max(headers.length, r.length); i += 1) {
        obj[headers[i] || `col_${i + 1}`] = r[i] || "";
      }
    }
    out.push(obj);
  }
  return { headers, rows: out };
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
  try {
    await page.goto(opts.componentUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
    await page.waitForTimeout(opts.waitMs);
    const raw = await page.evaluate(() => {
      const tables = [...document.querySelectorAll("table")];
      let picked = null;
      for (const t of tables) {
        const rows = [...t.querySelectorAll("tr")].map((tr) =>
          [...tr.querySelectorAll("th,td")]
            .map((td) => String(td.innerText || "").trim())
            .filter((x) => x)
        );
        if (!picked || rows.length > picked.length) picked = rows;
      }
      const text = String((document.body && document.body.innerText) || "");
      return { tableRows: picked || [], bodyTextHead: text.slice(0, 600) };
    });
    const parsed = toRowsWithHeader(raw.tableRows || []);
    console.log(
      JSON.stringify(
        {
          ok: true,
          component_url: opts.componentUrl,
          header_count: parsed.headers.length,
          row_count: parsed.rows.length,
          headers: parsed.headers,
          rows: parsed.rows,
          body_text_head: raw.bodyTextHead,
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
