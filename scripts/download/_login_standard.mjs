// FineReport standard login via Playwright automation
// Usage: node _login_standard.mjs <base_url> <username> <password>

import { createRequire } from "node:module";
import path from "node:path";
const require = createRequire(import.meta.url);

let playwright;
try { playwright = require("playwright"); }
catch { playwright = require(path.join(process.env.FR_BATCH_ROOT || "C:/Users/ZhuanZ/fr_batch", "node_modules/playwright")); }

const { chromium } = playwright;

const [baseUrl, username, password] = process.argv.slice(2);
if (!baseUrl || !username || !password) {
  console.error("Usage: node _login_standard.mjs <base_url> <username> <password>");
  process.exit(1);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(2000);

    const userInput = page.locator('input[name="username"], input[id*="username"], input[placeholder*="用户名"]').first();
    const passInput = page.locator('input[name="password"], input[id*="password"], input[placeholder*="密码"]').first();
    if (await userInput.count() === 0) {
      throw new Error("Cannot find username input on login page");
    }

    await userInput.fill(username);
    await passInput.fill(password);
    await page.locator('button:has-text("登"), button:has-text("Login"), button[id*="login"], button[type="submit"]').first().click();

    await page.waitForURL(/decision/, { timeout: 30000 });
    await page.waitForTimeout(2000);

    const cookies = await context.cookies(baseUrl);
    const result = {};
    for (const c of cookies) result[c.name] = c.value;
    result.cookieCount = cookies.length;
    console.log(JSON.stringify(result));
  } catch (err) {
    console.error(err.message || String(err));
    process.exit(1);
  } finally {
    await browser.close();
  }
})();
