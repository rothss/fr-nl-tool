/**
 * 批量并行下载 单元测试
 *
 * 测试内容:
 *   1. 滑动窗口调度器 - 并发数控制
 *   2. 单任务失败不阻塞其余
 *   3. 重试逻辑正确性
 *   4. 输出结果完整性
 *   5. 恢复模式（跳过已存在文件）
 *   6. 边界情况（空列表、并发=1、无 CDP）
 *
 * 运行: node tests/test_parallel_download.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { ok, deepEqual, throws } from "node:assert/strict";

const TEST_DIR = path.resolve(import.meta.dirname || __dirname, "..", "test-results", "parallel_test");
fs.mkdirSync(TEST_DIR, { recursive: true });

// ── 计数器（验证并发控制） ──
let activeWorkers = 0;
let maxConcurrent = 0;
let taskStartTimes = [];
let taskEndTimes = [];

function resetCounters() {
  activeWorkers = 0; maxConcurrent = 0; taskStartTimes = []; taskEndTimes = [];
}

// ── 模拟滑动窗口调度器 ──
async function slidingWindow(queue, concurrency, workerFn) {
  const results = [];
  let active = 0;
  let idx = 0;

  return new Promise((resolve) => {
    function next() {
      maxConcurrent = Math.max(maxConcurrent, active);
      if (idx >= queue.length && active === 0) {
        resolve(results);
        return;
      }
      while (active < concurrency && idx < queue.length) {
        const i = idx++;
        active++;
        const startTime = Date.now();
        taskStartTimes[i] = startTime;
        workerFn(queue[i], i)
          .then(r => { results[i] = r; })
          .catch(e => { results[i] = { ok: false, error: e.message }; })
          .finally(() => {
            active--;
            taskEndTimes[i] = Date.now();
            next();
          });
      }
    }
    next();
  });
}

// ── 模拟下载（可控延迟 + 失败注入） ──
function makeWorker(delayMs, failOn = []) {
  return async (task, idx) => {
    if (failOn.includes(idx)) throw new Error(`simulated_failure: task ${idx}`);
    await new Promise(r => setTimeout(r, delayMs));
    return { name: task.name, ok: true, bytes: task.size };
  };
}

// ══════════════════════════════════════════
//  测试1: 并发数控制
// ══════════════════════════════════════════
{
  console.log("测试1: 滑动窗口 - 并发数控制");
  resetCounters();
  const tasks = Array.from({ length: 12 }, (_, i) => ({ name: `task_${i}`, size: 100 }));
  const results = await slidingWindow(tasks, 4, makeWorker(50));

  console.log(`  任务数: ${tasks.length}, 并发: 4, 最大并发: ${maxConcurrent}`);
  ok(results.length === 12, "结果数应等于任务数");
  ok(maxConcurrent <= 4, `最大并发 ${maxConcurrent} 不应超过 4`);
  ok(results.every(r => r.ok), "所有任务应成功");
  console.log("  ✓ 通过\n");
}

// ══════════════════════════════════════════
//  测试2: 单任务失败不阻塞其余
// ══════════════════════════════════════════
{
  console.log("测试2: 单任务失败不阻塞其余");
  resetCounters();
  const tasks = Array.from({ length: 8 }, (_, i) => ({ name: `task_${i}`, size: 100 }));
  const results = await slidingWindow(tasks, 3, makeWorker(30, [2, 5])); // 第 2 和第 5 个失败

  const failures = results.filter(r => !r.ok);
  const successes = results.filter(r => r.ok);

  console.log(`  成功: ${successes.length}, 失败: ${failures.length}`);
  ok(results.length === 8, "结果数应等于任务数");
  ok(successes.length === 6, `应有 6 个成功`);
  ok(failures.length === 2, `应有 2 个失败`);
  ok(failures[0].error.includes("task 2"), "第 2 个任务应失败");
  ok(failures[1].error.includes("task 5"), "第 5 个任务应失败");
  console.log("  ✓ 通过\n");
}

// ══════════════════════════════════════════
//  测试3: 重试逻辑
// ══════════════════════════════════════════
{
  console.log("测试3: 重试逻辑正确性");

  // 模拟 shouldRetry
  const shouldRetry = (errorMsg, attempt, maxRetry) => {
    if (attempt >= maxRetry) return false;
    const m = errorMsg.toLowerCase();
    const retry = ["err_connection_refused", "timeout", "timed out", "report_not_ready_timeout", "net::err_"];
    const noRetry = ["export_not_zip", "parameterel_missing", "query_button_missing"];
    if (noRetry.some(p => m.includes(p))) return false;
    return retry.some(p => m.includes(p));
  };

  // 可重试错误
  ok(shouldRetry("ERR_CONNECTION_REFUSED at line 5", 0, 3), "连接拒绝应重试");
  ok(shouldRetry("Timeout 60000ms exceeded", 1, 3), "超时应重试");
  ok(shouldRetry("report_not_ready_timeout: no data", 0, 2), "报表未就绪应重试");
  ok(shouldRetry("net::ERR_TIMED_OUT", 0, 3), "网络超时应重试");

  // 不可重试错误
  ok(!shouldRetry("export_not_zip: <html>...", 0, 3), "导出非ZIP不应重试");
  ok(!shouldRetry("parameterEl_missing", 0, 3), "参数缺失不应重试");
  ok(!shouldRetry("query_button_missing", 0, 3), "按钮缺失不应重试");

  // 超过最大重试
  ok(!shouldRetry("ERR_CONNECTION_REFUSED", 3, 3), "达到最大重试不再重试");
  ok(!shouldRetry("timeout", 2, 2), "达到最大重试不再重试");

  console.log("  ✓ 通过\n");
}

// ══════════════════════════════════════════
//  测试4: 恢复模式（跳过已存在文件）
// ══════════════════════════════════════════
{
  console.log("测试4: 恢复模式 - 跳过已存在文件");

  const fileA = path.join(TEST_DIR, "existing.xlsx");
  const fileB = path.join(TEST_DIR, "new.xlsx");

  // 创建文件A（模拟之前下载的）
  fs.writeFileSync(fileA, "mock data".repeat(100)); // > 100 bytes

  // 清理文件B
  try { fs.unlinkSync(fileB); } catch (_) {}

  const reports = [
    { name: "exist", path: "doc/a.cpt", type: "cpt", outputFile: fileA },
    { name: "new", path: "doc/b.cpt", type: "cpt", outputFile: fileB },
    { name: "empty", path: "doc/c.cpt", type: "cpt", outputFile: path.join(TEST_DIR, "empty.xlsx") },
  ];

  const skipped = [];
  const toDownload = [];

  for (const r of reports) {
    if (fs.existsSync(r.outputFile) && fs.statSync(r.outputFile).size > 100) {
      skipped.push(r.name);
    } else {
      toDownload.push(r.name);
    }
  }

  console.log(`  跳过: ${skipped} | 需下载: ${toDownload}`);
  ok(skipped.length === 1, "应跳过1个已存在文件");
  ok(skipped[0] === "exist", "应跳过 exist");
  ok(toDownload.includes("new"), "应下载 new");
  ok(toDownload.includes("empty"), "应下载 empty");

  // 清理
  try { fs.unlinkSync(fileA); } catch (_) {}

  console.log("  ✓ 通过\n");
}

// ══════════════════════════════════════════
//  测试5: 边界情况
// ══════════════════════════════════════════
{
  console.log("测试5: 边界情况");

  // 空列表
  {
    resetCounters();
    const results = await slidingWindow([], 4, makeWorker(10));
    ok(results.length === 0, "空列表应返回空结果");
    console.log("  空列表: ✓");
  }

  // 并发=1（串行执行）
  {
    resetCounters();
    const tasks = Array.from({ length: 5 }, (_, i) => ({ name: `t${i}`, size: 100 }));
    const results = await slidingWindow(tasks, 1, makeWorker(10));
    ok(results.length === 5, "串行应完成所有任务");
    ok(maxConcurrent <= 1, "最大并发应为1");
    console.log("  串行(concurrency=1): ✓");
  }

  // 并发 > 任务数
  {
    resetCounters();
    const tasks = Array.from({ length: 2 }, (_, i) => ({ name: `t${i}`, size: 100 }));
    const results = await slidingWindow(tasks, 10, makeWorker(10));
    ok(results.length === 2, "大并发不应影响结果");
    ok(maxConcurrent <= 2, "最大并发不超过任务数");
    console.log(`  并发>任务数(10 > 2): ✓ (max=${maxConcurrent})\n`);
  }

  console.log("  ✓ 全部通过\n");
}

// ══════════════════════════════════════════
//  测试6: 时间重叠验证（并行证明）
// ══════════════════════════════════════════
{
  console.log("测试6: 并行性证明 - 时间重叠检查");
  resetCounters();

  // 4个任务，每个 200ms
  const tasks = Array.from({ length: 4 }, (_, i) => ({ name: `t${i}`, size: 100 }));
  await slidingWindow(tasks, 4, makeWorker(200));

  // 检查至少有两个任务是重叠执行的
  let overlap = false;
  for (let i = 0; i < taskStartTimes.length; i++) {
    for (let j = i + 1; j < taskStartTimes.length; j++) {
      const si = taskStartTimes[i], ei = taskEndTimes[i];
      const sj = taskStartTimes[j], ej = taskEndTimes[j];
      if (si < ej && sj < ei) { overlap = true; break; }
    }
    if (overlap) break;
  }

  ok(overlap, "至少两个任务应并行执行（时间重叠）");
  console.log(`  ✓ 通过\n`);
}

// ══════════════════════════════════════════
console.log("=".repeat(50));
console.log("全部测试通过 ✅");
console.log("=".repeat(50));
