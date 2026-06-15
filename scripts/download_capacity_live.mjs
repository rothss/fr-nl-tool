/**
 * 从 opm.hnair.net 下载运力数据 (v2 - 使用已有 Edge Profile)
 *
 * 用法：node scripts/download_capacity_live.mjs --no-headless
 *
 * 利用 Edge 已有 login profile 中的 Cookie 绕过 CAS 登录。
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

function parseArgs(argv) {
  const opts = {
    baseUrl: process.env.FR_BASE_URL || "https://opm.hnair.net/webroot/decision",
    reportPath: "doc/Fdjt/运力数据.cpt",
    outputFile: "./fr_mirror/live_download/运力数据_live_export.xlsx",
    waitMs: 10000,
    headless: !argv.includes("--no-headless"),
    cdpUrl: process.env.FR_CDP_URL || "http://127.0.0.1:9222",
  };
  const next = (i) => { if (i + 1 >= argv.length) throw new Error("Missing value for " + argv[i]); return argv[i + 1]; };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === "--output" || a === "--output-file") { opts.outputFile = next(i); i += 1; }
    else if (a === "--report-path") { opts.reportPath = next(i); i += 1; }
    else if (a === "--wait-ms") { opts.waitMs = Number(next(i)); i += 1; }
    else if (a === "--cdp-url") { opts.cdpUrl = next(i); i += 1; }
  }
  return opts;
}

function loadPlaywright() {
  try { return require("playwright"); } catch (_) {
    return require(path.join(process.cwd(), "fr_batch", "node_modules", "playwright"));
  }
}

function isZip(buf) { return buf && buf.length > 4 && buf[0] === 0x50 && buf[1] === 0x4b; }

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const pw = loadPlaywright();
  const base = opts.baseUrl.replace(/\/$/, "");

  console.log("=".repeat(60));
  console.log("OPM 运力数据实时下载 v2 (Persistent Profile)");
  console.log("=".repeat(60));
  console.log("Base URL:", base);
  console.log("Report:  ", opts.reportPath);
  console.log("Output:  ", opts.outputFile);
  console.log("Headless:", opts.headless);
  console.log("");

  const outDir = path.dirname(path.resolve(opts.outputFile));
  fs.mkdirSync(outDir, { recursive: true });

  // ---- 策略 1: CDP 连接 ----
  let browser, context, page;
  console.log("[1/5] 获取浏览器会话...");

  // 先尝试 CDP 连接
  let cdpOk = false;
  try {
    const httpGet = (url) => new Promise((resolve, reject) => {
      const lib = url.startsWith("https") ? require("https") : require("http");
      lib.get(url, (res) => { let d = ""; res.on("data", (c) => d += c); res.on("end", () => resolve(d)); })
         .on("error", reject);
    });
    const cdpJson = await httpGet(opts.cdpUrl + "/json/version");
    if (cdpJson && cdpJson.includes("Browser")) {
      console.log("  ✓ CDP 浏览器已运行，尝试连接...");
      browser = await pw.chromium.connectOverCDP(opts.cdpUrl);
      const pages = browser.contexts()[0]?.pages() || [];
      if (pages.length > 0) {
        page = pages[0];
        context = browser.contexts()[0];
        console.log(`  ✓ CDP 连接成功，当前页面: ${await page.title()}`);
        cdpOk = true;
      }
    }
  } catch (_) {
    console.log("  CDP 浏览器未运行");
  }

  // ---- 策略 2: 使用 Persistent Context ----
  if (!cdpOk) {
    const edgeProfileDir = process.env.FR_EDGE_PROFILE_DIR && path.isAbsolute(process.env.FR_EDGE_PROFILE_DIR)
      ? process.env.FR_EDGE_PROFILE_DIR
      : path.resolve(process.cwd(), process.env.FR_EDGE_PROFILE_DIR || "fr_batch/edge_profile_nlquery");

    console.log(`  尝试使用 Edge Profile: ${edgeProfileDir}`);
    if (fs.existsSync(edgeProfileDir)) {
      console.log("  Profile 目录存在");
    } else {
      console.log("  ⚠ Profile 目录不存在");
    }

    try {
      context = await pw.chromium.launchPersistentContext(edgeProfileDir, {
        channel: "msedge",
        headless: opts.headless,
        viewport: { width: 1920, height: 1080 },
        acceptDownloads: true,
        args: ["--disable-blink-features=AutomationControlled"],
      });
      page = context.pages()[0] || await context.newPage();
      console.log("  ✓ 使用 Persistent Profile 启动 Edge");
    } catch (e) {
      console.log(`  Persistent Profile 失败: ${e.message.split("\n")[0]}`);
      // 回退到普通 launch
      browser = await pw.chromium.launch({
        channel: "msedge",
        headless: opts.headless,
        args: ["--disable-blink-features=AutomationControlled"],
      });
      context = await browser.newContext({
        viewport: { width: 1920, height: 1080 },
        acceptDownloads: true,
      });
      page = await context.newPage();
      console.log("  ✓ 使用普通模式启动 Edge");
    }
  }

  page.setDefaultTimeout(60000);

  // ---- 导航到 OPM ----
  console.log("[2/5] 导航到 OPM...");
  await page.goto(base, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(3000);

  const currentUrl = page.url();
  console.log("  当前 URL:", currentUrl);

  if (currentUrl.includes("cas") || currentUrl.includes("login")) {
    console.log("  ⚠ 需要登录！");

    // 截图
    await page.screenshot({ path: path.join(outDir, "login_page.png"), fullPage: true });
    console.log("  截图:", path.join(outDir, "login_page.png"));

    // 非 headless 模式下提示用户手动登录
    if (!opts.headless) {
      console.log("");
      console.log("  >>> 请在浏览器窗口中手动完成登录 <<<");
      console.log("  登录完成后，按 Enter 继续...");

      // 等待用户输入
      await new Promise((resolve) => {
        process.stdin.once("data", () => resolve());
      });

      // 重新导航
      await page.goto(base, { waitUntil: "networkidle", timeout: 30000 });
      await page.waitForTimeout(2000);
      const newUrl = page.url();
      if (newUrl.includes("cas") || newUrl.includes("login")) {
        console.log("  ✗ 登录未成功，退出");
        if (browser) await browser.close(); else await context.close();
        process.exit(1);
      }
      console.log("  ✓ 登录成功！");
    } else {
      console.log("");
      console.log("  headless 模式下无法交互登录。");
      console.log("  请添加 --no-headless 参数并在弹出的浏览器中手动登录。");
      if (browser) await browser.close(); else await context.close();
      process.exit(2);
    }
  } else {
    console.log("  ✓ 已登录！");
  }

  // ---- 打开报表 ----
  console.log("[3/5] 打开运力数据报表...");
  const reportUrl = `${base}/view/report?viewlet=${encodeURIComponent(opts.reportPath)}`;
  console.log("  URL:", reportUrl);
  await page.goto(reportUrl, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(opts.waitMs);

  const pageTitle = await page.title();
  console.log("  页面标题:", pageTitle);

  await page.screenshot({ path: path.join(outDir, "report_page.png"), fullPage: true });
  console.log("  截图:", path.join(outDir, "report_page.png"));

  // ---- 导出 ----
  console.log("[4/5] 尝试导出 Excel...");
  let downloaded = false;
  let downloadPath = "";

  // 方式 1: 点击导出按钮
  const btnSelectors = [
    "button:has-text('导出')", "a:has-text('导出')",
    "button:has-text('Excel')", "a:has-text('Excel')",
    "button:has-text('下载')", "a:has-text('下载')",
    '[title="导出"]', '[title="Excel"]',
  ];

  for (const sel of btnSelectors) {
    try {
      const btn = page.locator(sel).first;
      if (await btn.isVisible({ timeout: 2000 })) {
        console.log("  点击导出按钮:", sel);
        const dlPromise = page.waitForEvent("download", { timeout: 30000 });
        await btn.click();
        const dl = await dlPromise;
        downloadPath = path.resolve(opts.outputFile);
        await dl.saveAs(downloadPath);
        downloaded = true;
        console.log("  ✓ 导出成功:", downloadPath);
        break;
      }
    } catch (_) {}
  }

  // 方式 2: API 导出
  if (!downloaded) {
    console.log("  尝试 API 导出...");
    try {
      const cookies = await context.cookies();
      const sid = cookies.find(c => c.name === "JSESSIONID" || c.name === "sessionID")?.value || "";

      if (sid) {
        const resp = await page.evaluate(async ({ url, body }) => {
          const r = await fetch(url, { method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" },
            body,
          });
          return Array.from(new Uint8Array(await r.arrayBuffer()));
        }, { url: `${base}/view/report`, body: `op=export&sessionID=${encodeURIComponent(sid)}&format=excel&extype=simple` });

        const buf = Buffer.from(resp);
        if (isZip(buf)) {
          downloadPath = path.resolve(opts.outputFile);
          fs.writeFileSync(downloadPath, buf);
          downloaded = true;
          console.log("  ✓ API 导出成功:", downloadPath, `(${buf.length} bytes)`);
        } else {
          console.log("  ✗ API 返回非 Excel:", buf.slice(0, 200).toString("utf8"));
        }
      }
    } catch (e) {
      console.log("  ✗ API 导出失败:", e.message);
    }
  }

  if (!downloaded) {
    console.log("  Excel 导出未成功");
  }

  // 方式 3: 抓取页面 DOM 表格数据
  console.log("  抓取页面 DOM 表格数据作为备份...");
  try {
    const tableData = await page.evaluate(() => {
      const tables = document.querySelectorAll("table");
      const iframes = document.querySelectorAll("iframe");

      // Try iframe first
      for (const iframe of iframes) {
        try {
          const doc = iframe.contentDocument || iframe.contentWindow?.document;
          if (!doc) continue;
          const t = doc.querySelector("table");
          if (!t) continue;
          const headers = [...t.querySelectorAll("thead th, thead td, tr:first-child th, tr:first-child td")]
            .map(c => c.textContent.trim()).filter(Boolean);
          const rows = [...t.querySelectorAll("tbody tr, tr")]
            .slice(headers.length > 0 ? 1 : 0)
            .map(r => [...r.querySelectorAll("td, th")].map(c => c.textContent.trim()));
          return { source: "iframe", headers, rows };
        } catch (_) {}
      }

      // Main page table
      for (const t of tables) {
        const headers = [...t.querySelectorAll("thead th, thead td, tr:first-child th, tr:first-child td")]
          .map(c => c.textContent.trim()).filter(Boolean);
        if (headers.length === 0) continue;
        const rows = [...t.querySelectorAll("tbody tr, tr")]
          .slice(1)
          .map(r => [...r.querySelectorAll("td, th")].map(c => c.textContent.trim()));
        return { source: "dom", headers, rows };
      }
      return null;
    });

    if (tableData) {
      console.log(`  DOM 表格: ${tableData.headers.length} 列, ${tableData.rows.length} 行 (来源: ${tableData.source})`);
      const domPath = path.join(outDir, "page_table_data.json");
      fs.writeFileSync(domPath, JSON.stringify(tableData, null, 2), "utf8");
      console.log("  表格数据已保存:", domPath);

      // 也保存为 xlsx
      try {
        const XLSX = require("xlsx") || (() => {
          try { return require(path.join(process.cwd(), "fr_batch", "node_modules", "xlsx")); } catch (_) { return null; }
        })();
        if (XLSX) {
          const ws = XLSX.utils.aoa_to_sheet([tableData.headers, ...tableData.rows]);
          const wb = XLSX.utils.book_new();
          XLSX.utils.book_append_sheet(wb, ws, "运力数据");
          const xlsxPath = path.join(outDir, "page_table_data.xlsx");
          XLSX.writeFile(wb, xlsxPath);
          console.log("  表格 xlsx 已保存:", xlsxPath);
          if (!downloaded) {
            downloadPath = xlsxPath;
            downloaded = true;
          }
        }
      } catch (_) {}

      // 打印前几行数据预览
      console.log("");
      console.log("  数据预览 (前5行):");
      console.log("  " + tableData.headers.join(" | "));
      for (let i = 0; i < Math.min(5, tableData.rows.length); i++) {
        console.log("  " + tableData.rows[i].join(" | "));
      }
    } else {
      console.log("  ⚠ 未找到表格数据");
    }
  } catch (e) {
    console.log("  DOM 抓取失败:", e.message);
  }

  // ---- 清理 ----
  console.log("");
  console.log("[5/5] 关闭浏览器...");
  if (browser) await browser.close(); else await context.close();

  console.log("");
  console.log("=".repeat(60));
  if (downloaded) {
    console.log("✓ 下载完成！");
    console.log("  文件:", downloadPath);
    try {
      const stat = fs.statSync(downloadPath);
      console.log("  大小:", (stat.size / 1024).toFixed(1), "KB");
    } catch (_) {}
  } else {
    console.log("⚠ 未能自动下载 Excel");
  }
  console.log("=".repeat(60));

  process.exit(downloaded ? 0 : 1);
}

main().catch((err) => {
  console.error("FATAL:", err);
  process.exit(1);
});
