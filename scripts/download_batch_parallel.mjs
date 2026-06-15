/**
 * 批量并行下载 OPM 报表 (Sliding Window Concurrency)
 *
 * 用法:
 *   node scripts/download_batch_parallel.mjs --folder "航空板块经营报表" --concurrency 4
 *   node scripts/download_batch_parallel.mjs --manifest fr_mirror/manifest.json --concurrency 3 --resume
 *
 * 通过 CDP 连接已登录的 Edge 浏览器，并行打开多个 Tab 同步下载报表，
 * 采用滑动窗口调度算法，避免 FineReport 限流。
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);

// ── 默认值 ──
const CDP_URL = process.env.FR_CDP_URL || "http://127.0.0.1:9222";
const BASE_URL = (process.env.FR_BASE_URL || "https://opm.hnair.net/webroot/decision").replace(/\/$/, "");
const DEFAULT_CONCURRENCY = 4;
const DEFAULT_MAX_WAIT_MS = 60000;
const DEFAULT_RETRY = 2;
const RENDER_WAIT = { cpt: 8000, frm: 15000 };

// ── Playwright 加载 ──
function loadPlaywright() {
  for (const p of [
    "playwright",
    path.resolve("fr_batch", "node_modules", "playwright"),
    path.resolve(process.cwd(), "fr_batch", "node_modules", "playwright"),
  ]) {
    try { return require(p); } catch (_) { /* continue */ }
  }
  throw new Error("Playwright not found. Install: npm install playwright --prefix fr_batch && npx playwright install chromium");
}

// ── 工具函数 ──
function isZip(buf) { return buf && buf.length > 4 && buf[0] === 0x50 && buf[1] === 0x4b; }
function safeName(n) { return String(n || "report").replace(/[<>:"/\\|?*]/g, "_").slice(0, 200); }
const ts = () => new Date().toISOString().replace("T", " ").slice(0, 19);

// ── 重试判定 ──
function shouldRetry(errorMsg, attempt, maxRetry) {
  if (attempt >= maxRetry) return false;
  const m = (errorMsg || "").toLowerCase();
  const retryPatterns = [
    "err_connection_refused", "timeout", "timed out",
    "report_not_ready_timeout", "net::err_",
  ];
  const noRetryPatterns = [
    "export_not_zip", "parameterel_missing", "query_button_missing",
  ];
  if (noRetryPatterns.some(p => m.includes(p))) return false;
  return retryPatterns.some(p => m.includes(p));
}

// ── 参数解析 ──
function parseArgs(argv) {
  const opts = {
    cdpUrl: CDP_URL,
    baseUrl: BASE_URL,
    manifestPath: "",
    folder: "",
    outputDir: path.resolve("fr_mirror"),
    concurrency: DEFAULT_CONCURRENCY,
    maxWaitMs: DEFAULT_MAX_WAIT_MS,
    retry: DEFAULT_RETRY,
    resume: false,
    outputFormat: "text",
    _rawArgs: argv,
  };
  const next = (i) => { if (i + 1 >= argv.length) throw new Error(`Missing value for ${argv[i]}`); return argv[i + 1]; };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--manifest") { opts.manifestPath = next(i); i++; }
    else if (a === "--folder") { opts.folder = next(i); i++; }
    else if (a === "--output") { opts.outputDir = path.resolve(next(i)); i++; }
    else if (a === "--concurrency") { opts.concurrency = Math.max(1, parseInt(next(i)) || DEFAULT_CONCURRENCY); i++; }
    else if (a === "--max-wait") { opts.maxWaitMs = parseInt(next(i)) || DEFAULT_MAX_WAIT_MS; i++; }
    else if (a === "--retry") { opts.retry = parseInt(next(i)) || DEFAULT_RETRY; i++; }
    else if (a === "--resume") { opts.resume = true; }
    else if (a === "--output-format") { opts.outputFormat = next(i); i++; }
    else if (a === "--cdp-url") { opts.cdpUrl = next(i); i++; }
    else if (a === "--base-url") { opts.baseUrl = next(i); i++; }
  }
  return opts;
}

// ── 报表列表构建 ──
function buildReportList(opts) {
  if (opts.manifestPath) {
    const raw = JSON.parse(fs.readFileSync(path.resolve(opts.manifestPath), "utf8"));
    const entries = raw.entries || [];
    const reports = [];
    for (const entry of entries) {
      if (opts.folder) {
        const names = entry.directoryNames || [];
        if (!names.some(n => n.includes(opts.folder))) continue;
      }
      const dirPath = (entry.directoryNames || []).length > 0
        ? path.join(opts.outputDir, ...entry.directoryNames)
        : opts.outputDir;
      const list = entry.reports || [];
      for (const r of list) {
        const reportPath = r.path || "";
        const type = reportPath.endsWith(".frm") ? "frm" : "cpt";
        reports.push({
          name: r.name || "unknown",
          path: reportPath,
          type,
          outputDir: dirPath,
          outputFile: path.join(dirPath, safeName(r.name || "unknown") + ".xlsx"),
        });
      }
    }
    return reports;
  }
  return [];
}

// ── CPT 报表导出 ──
async function downloadCPT(page, report, opts) {
  const { baseUrl } = opts;
  const { path: reportPath, outputFile } = report;

  // 导航
  const viewUrl = `${baseUrl}/view/report?viewlet=${encodeURIComponent(reportPath)}`;
  await page.goto(viewUrl, { waitUntil: "domcontentloaded", timeout: opts.maxWaitMs });
  await page.waitForTimeout(RENDER_WAIT.cpt);

  // 尝试1: 点击导出按钮
  try {
    const dlPromise = page.waitForEvent("download", { timeout: 30000 });
    const selectors = ["button:has-text('导出')", "a:has-text('导出')", "button:has-text('Excel')", "a:has-text('Excel')", "text=导出", "text=Excel"];
    let clicked = false;
    for (const sel of selectors) {
      try {
        const btn = page.locator(sel).first;
        if (await btn.isVisible({ timeout: 1500 })) { await btn.click(); clicked = true; break; }
      } catch (_) { /* 下一个选择器 */ }
    }
    if (clicked) {
      const dl = await dlPromise;
      await dl.saveAs(outputFile);
      return { ok: true, method: "click", bytes: fs.statSync(outputFile).size };
    }
  } catch (_) { /* 回退到 API */ }

  // 尝试2: API 导出
  const cookies = await page.context().cookies();
  const sid = cookies.find(c => c.name === "JSESSIONID" || c.name === "sessionID")?.value || "";
  if (sid) {
    const buf = await page.evaluate(async ({ url, body }) => {
      const r = await fetch(url, { method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" },
        body, credentials: "include",
      });
      return Array.from(new Uint8Array(await r.arrayBuffer()));
    }, { url: `${baseUrl}/view/report`, body: `op=export&sessionID=${encodeURIComponent(sid)}&format=excel&extype=simple` });

    const data = Buffer.from(buf);
    if (isZip(data)) {
      fs.writeFileSync(outputFile, data);
      return { ok: true, method: "api", bytes: data.length };
    }
    throw new Error(`export_not_zip: ${data.slice(0, 100).toString("utf8")}`);
  }
  throw new Error("no_session_id_for_api_export");
}

// ── FRM 报表导出 ──
async function downloadFRM(page, report, opts) {
  const { baseUrl } = opts;
  const { path: reportPath, outputFile } = report;

  const viewUrl = `${baseUrl}/view/form?viewlet=${encodeURIComponent(reportPath)}&op=view`;
  await page.goto(viewUrl, { waitUntil: "domcontentloaded", timeout: opts.maxWaitMs });
  await page.waitForTimeout(RENDER_WAIT.frm);

  // 等待报表组件就绪
  let ready = false;
  for (let round = 0; round < 10; round++) {
    const state = await page.evaluate(() => {
      const iframes = document.querySelectorAll("iframe");
      const reports = [];
      for (const f of iframes) {
        try {
          const w = f.contentWindow || f.contentDocument?.defaultView;
          if (w && w.FR && w.FR.Report && w.FR.Report.widgetByName) {
            reports.push({ hasExport: typeof w.FR.Report.widgetByName === "function" });
          }
        } catch (_) { /* cross-origin iframe */ }
      }
      return { reports, bodyLen: (document.body?.innerText || "").length };
    });
    if (state.reports.length > 0) { ready = true; break; }
    await page.waitForTimeout(2000);
  }

  if (!ready) throw new Error("report_not_ready_timeout");

  // 尝试1: 导出按钮
  try {
    const dlPromise = page.waitForEvent("download", { timeout: 30000 });
    const selectors = ["button:has-text('导出')", "a:has-text('导出')", "button:has-text('Excel')", "a:has-text('Excel')"];
    let clicked = false;
    for (const sel of selectors) {
      try {
        const btn = page.locator(sel).first;
        if (await btn.isVisible({ timeout: 1500 })) { await btn.click(); clicked = true; break; }
      } catch (_) {}
    }
    if (clicked) {
      const dl = await dlPromise;
      await dl.saveAs(outputFile);
      return { ok: true, method: "click_frm", bytes: fs.statSync(outputFile).size };
    }
  } catch (_) { /* 回退到组件导出 */ }

  // 尝试2: 组件 exportReportToExcel
  const compResult = await page.evaluate(async () => {
    const iframes = document.querySelectorAll("iframe");
    for (const f of iframes) {
      try {
        const w = f.contentWindow || f.contentDocument?.defaultView;
        if (w && Array.isArray(w._reports) && w._reports.length > 0) {
          for (const rep of w._reports) {
            if (rep.exportReportToExcel) {
              await rep.exportReportToExcel();
              return { called: true };
            }
          }
        }
      } catch (_) {}
    }
    return { called: false };
  });
  if (compResult.called) {
    try {
      const dl = await page.waitForEvent("download", { timeout: 60000 });
      await dl.saveAs(outputFile);
      return { ok: true, method: "component", bytes: fs.statSync(outputFile).size };
    } catch (e) { throw new Error(`component_download_timeout: ${e.message}`); }
  }

  // 尝试3: DOM 表格抽取
  const tableData = await page.evaluate(() => {
    const tables = [];
    for (const t of document.querySelectorAll("table")) {
      const rows = [...t.querySelectorAll("tr")].map(r => [...r.querySelectorAll("td,th")].map(c => c.textContent.trim()));
      if (rows.length > 1) tables.push(rows);
    }
    for (const f of document.querySelectorAll("iframe")) {
      try {
        const d = f.contentDocument || f.contentWindow?.document;
        if (!d) continue;
        for (const t of d.querySelectorAll("table")) {
          const rows = [...t.querySelectorAll("tr")].map(r => [...r.querySelectorAll("td,th")].map(c => c.textContent.trim()));
          if (rows.length > 1) tables.push(rows);
        }
      } catch (_) {}
    }
    return tables;
  });

  if (tableData.length > 0) {
    const totalRows = tableData.reduce((s, t) => s + t.length, 0);
    const jsonPath = outputFile.replace(/\.xlsx$/, ".json");
    fs.writeFileSync(jsonPath, JSON.stringify({ tables: tableData, rowCount: totalRows }, null, 2), "utf8");
    return { ok: true, method: "dom_table", bytes: totalRows, jsonPath };
  }

  throw new Error("all_export_methods_failed");
}

// ── 单个报表下载（含重试） ──
async function downloadOneReport(context, report, opts, stats) {
  const page = await context.newPage();
  page.setDefaultTimeout(opts.maxWaitMs);
  let lastError = "";

  try {
    // 检查恢复模式
    if (opts.resume && fs.existsSync(report.outputFile) && fs.statSync(report.outputFile).size > 100) {
      stats.skipped++;
      return { name: report.name, ok: true, bytes: fs.statSync(report.outputFile).size, method: "resume" };
    }

    // 确保输出目录存在
    fs.mkdirSync(path.dirname(report.outputFile), { recursive: true });

    for (let attempt = 0; attempt <= opts.retry; attempt++) {
      try {
        const fn = report.type === "frm" ? downloadFRM : downloadCPT;
        const result = await fn(page, report, opts);
        await page.close();
        return { name: report.name, ...result };
      } catch (e) {
        lastError = e.message || String(e);
        if (!shouldRetry(lastError, attempt, opts.retry)) throw e;
        await page.waitForTimeout(2000 * (attempt + 1)); // 指数退避
      }
    }
  } catch (e) {
    lastError = e.message || String(e);
    throw new Error(lastError);
  } finally {
    try { await page.close().catch(() => {}); } catch (_) { /* 忽略关闭错误 */ }
  }
}

// ── 滑动窗口调度器 ──
function slidingWindow(queue, concurrency, workerFn) {
  return new Promise((resolve, reject) => {
    const results = [];
    let active = 0;
    let idx = 0;
    let done = false;

    function next() {
      if (done) return;
      // 当所有任务都已入队且没有活跃的 worker 时完成
      if (idx >= queue.length && active === 0) {
        resolve(results);
        return;
      }
      // 启动新 worker
      while (active < concurrency && idx < queue.length) {
        const i = idx++;
        active++;
        workerFn(queue[i], i)
          .then(r => { results[i] = r; })
          .catch(e => { results[i] = { name: queue[i].name, ok: false, error: e.message || String(e) }; })
          .finally(() => { active--; next(); });
      }
    }
    next();
  });
}

// ── 主流程 ──
async function main() {
  const opts = parseArgs(process.argv.slice(2));

  if (opts.outputFormat === "text") {
    console.log("=".repeat(70));
    console.log("OPM 批量并行下载");
    console.log("=".repeat(70));
    console.log(`CDP:       ${opts.cdpUrl}`);
    console.log(`Base URL:  ${opts.baseUrl}`);
    console.log(`输出目录:  ${opts.outputDir}`);
    console.log(`并发数:    ${opts.concurrency}`);
    console.log(`重试:      ${opts.retry}`);
    console.log(`超时:      ${(opts.maxWaitMs / 1000).toFixed(0)}s`);
    console.log(`恢复模式:  ${opts.resume ? "是" : "否"}`);
    console.log("");
  }

  // 1. 构建报表列表
  const reports = buildReportList(opts);
  if (reports.length === 0) {
    console.error("没有找到报表。请指定 --manifest 或 --folder");
    process.exit(1);
  }
  if (opts.outputFormat === "text") {
    console.log(`报表数量:  ${reports.length}`);
    console.log(`  CPT: ${reports.filter(r => r.type === "cpt").length}`);
    console.log(`  FRM: ${reports.filter(r => r.type === "frm").length}`);
    console.log("");
  }

  // 2. 连接 CDP
  if (opts.outputFormat === "text") console.log("[1/4] 连接 CDP 浏览器...");
  const pw = loadPlaywright();
  let browser;
  try {
    browser = await pw.chromium.connectOverCDP(opts.cdpUrl);
  } catch (e) {
    console.error(`CDP 连接失败: ${e.message}`);
    process.exit(1);
  }
  const context = browser.contexts()[0];
  if (!context) { console.error("CDP 浏览器无可用 context"); await browser.close(); process.exit(1); }

  // 检查登录态
  const loginPage = context.pages().find(p => p.url().includes("opm") || p.url().includes("hnair"));
  if (loginPage && (loginPage.url().includes("login") || loginPage.url().includes("cas"))) {
    console.error("未登录 OPM！请先在 Edge 浏览器中登录 https://opm.hnair.net");
    await browser.close(); process.exit(1);
  }
  if (opts.outputFormat === "text") console.log("  ✓ CDP 已连接，已登录\n");

  // 3. 并行下载
  if (opts.outputFormat === "text") console.log("[2/4] 并行下载报表...\n");
  const stats = { ok: 0, fail: 0, skipped: 0, total: reports.length, startTime: Date.now() };

  const results = [];
  await slidingWindow(reports, opts.concurrency, async (report, idx) => {
    const num = String(idx + 1).padStart(2);
    const now = ts();

    try {
      const res = await downloadOneReport(context, report, opts, stats);
      if (res.ok) {
        const size = res.bytes ? `${(res.bytes / 1024).toFixed(0)}KB` : "";
        if (res.method === "resume") {
          if (opts.outputFormat === "text") console.log(`  [${num}/${reports.length}] ${res.name} 已存在`);
        } else {
          if (opts.outputFormat === "text") console.log(`  [${num}/${reports.length}] ${res.name} ✓ ${size} (${res.method})`);
        }
        stats.ok++;
      }
      results.push(res);
    } catch (e) {
      if (opts.outputFormat === "text") console.log(`  [${num}/${reports.length}] ${report.name} ✗ ${e.message.split("\n")[0].slice(0, 70)}`);
      stats.fail++;
      results.push({ name: report.name, ok: false, error: e.message.split("\n")[0] });
    }
  });

  // 4. 汇总
  if (opts.outputFormat === "text") console.log("\n[3/4] 汇总结果...");
  const elapsed = ((Date.now() - stats.startTime) / 1000).toFixed(0);

  if (opts.outputFormat === "json") {
    console.log(JSON.stringify({
      ok: stats.fail === 0,
      total: stats.total,
      successful: stats.ok,
      failed: stats.fail,
      skipped: stats.skipped,
      elapsedSeconds: parseInt(elapsed),
      results,
    }, null, 2));
  } else {
    console.log("");
    console.log("=".repeat(70));
    console.log(`结果: ✓ ${stats.ok} 成功 | ✗ ${stats.fail} 失败 | ${stats.skipped} 跳过`);
    console.log(`耗时: ${elapsed}s (${reports.length} 报表, 并发 ${opts.concurrency})`);
    if (stats.ok + stats.fail > 0) {
      console.log(`平均: ${(parseInt(elapsed) / (stats.ok + stats.fail)).toFixed(1)}s/报表`);
    }
    if (stats.fail > 0) {
      console.log("\n失败清单:");
      for (const r of results) {
        if (!r.ok) console.log(`  ${r.name}: ${r.error}`);
      }
    }
    console.log("=".repeat(70));
  }

  // 不关闭浏览器（保持 CDP 连接给后续使用）
  process.exit(stats.fail > 0 && stats.ok === 0 ? 1 : 0);
}

main().catch(e => {
  console.error("FATAL:", e);
  process.exit(1);
});
