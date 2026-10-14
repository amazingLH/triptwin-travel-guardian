/* Optional browser regression: NODE_PATH must resolve Playwright; requires Edge.
 * Run against a local test server: node scripts/check_loading_ui.cjs URL
 * Uses only public railway examples. No real model/MCP/FlyAI requests.
 */
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const base = process.argv[2] || "http://127.0.0.1:7860";
const mobile = process.argv.includes("--mobile");

(async () => {
  const browser = await chromium.launch({ headless: true, channel: "msedge" });
  let releaseInspection;
  try {
    const context = await browser.newContext({
      viewport: mobile ? { width: 390, height: 844 } : { width: 1280, height: 900 },
    });
    const page = await context.newPage();
    const config = await (await context.request.get(`${base}/config`)).json();
    const posts = [];
    const pageErrors = [];
    let activePosts = 0;
    let lastPost = Date.now();
    page.on("pageerror", (e) => pageErrors.push(e.message));
    page.on("request", (r) => {
      if (r.method() !== "POST" || !r.url().includes("/gradio_api/")) return;
      activePosts++;
      lastPost = Date.now();
      posts.push(r.postDataJSON()?.fn_index);
    });
    function finish(r) {
      if (r.method() === "POST" && r.url().includes("/gradio_api/")) activePosts--;
    }
    page.on("requestfinished", finish);
    page.on("requestfailed", finish);
    async function settled() {
      const end = Date.now() + 15000;
      while (Date.now() < end) {
        if (activePosts === 0 && Date.now() - lastPost > 350) return;
        await page.waitForTimeout(40);
      }
      throw new Error("UI requests did not settle");
    }
    async function contains(text) {
      await page.waitForFunction((value) => document.body.innerText.includes(value), text);
    }
    function click(text) {
      return page.getByRole("button", { name: text, exact: true }).click();
    }
    const inspectButton = config.components.find((c) => c.props?.value === "查看 / 执行实时巡检").id;
    const inspectFn = config.dependencies.find((d) => d.targets.some(([id, e]) => id === inspectButton && e === "click")).id;

    await page.goto(base, { waitUntil: "domcontentloaded" });
    await page.getByText("行程功能示例", { exact: true }).waitFor();
    await settled();
    await click("③ 检查风险");
    await contains("请先构建旅行数字孪生");
    await settled();
    assert.ok((await page.locator("#risk-progress").innerText()).includes("未完成"));
    assert.equal(await page.locator(".generating,.pending").count(), 0);

    await page.getByText("行程功能示例", { exact: true }).click();
    await click("行程冲突异常示例");
    await settled();
    await click("② 解析行程截图");
    await contains("TripGraph 已构建");
    await settled();
    await page.getByText("查看字段识别置信度", { exact: true }).click();
    await page.locator("#field-confidence").waitFor({ state: "visible" });
    await contains("events[0].cost_cny");
    await click("③ 检查风险"); // Validation error must not start success followups.
    await contains("请先核对并确认低置信字段");
    await settled();
    const beforeIdle = posts.length;
    await page.waitForTimeout(650);
    assert.equal(posts.length, beforeIdle, "Unexpected background event loop");

    await page.getByText("我已核对并确认低置信字段", { exact: true }).click();
    await click("③ 检查风险");
    await contains("检出 1 个风险");
    await settled();
    await click("④ 生成 Plan B");
    await page.getByText("选择保留的行程方案", { exact: true }).waitFor();
    await settled();
    await page.locator("#local-plan-choice input").click();
    await page.getByRole("option").nth(1).click();
    await settled();
    const pendingChoice = await page.locator("#local-plan-choice input").inputValue();
    await page.getByText("查看工具证据与实时巡检", { exact: true }).click();
    await click("查看 / 执行实时巡检");
    await contains("行程巡检完成 · 执行耗时");
    await settled();
    assert.equal(await page.getByText("选择保留的行程方案", { exact: true }).count(), 1);
    assert.equal(await page.locator("#local-plan-choice input").inputValue(), pendingChoice);
    assert.ok((await page.locator("body").innerText()).includes("检出 1 个风险"));
    await click("③ 检查风险");
    await settled();
    assert.equal(await page.locator("#local-plan-choice input").inputValue(), pendingChoice);
    assert.ok((await page.locator("#risk-progress").innerText()).includes("执行耗时"));
    const beforeHeldInspection = posts.filter((id) => id === inspectFn).length;
    await click("应用到当前行程 · 不执行实际退改");
    await contains("本地风险 1 → 0");
    await settled();
    assert.equal(await page.getByText("选择保留的行程方案", { exact: true }).count(), 0);
    if (!(await page.getByRole("button", { name: "查看 / 执行实时巡检", exact: true }).isVisible())) {
      await page.getByText("查看工具证据与实时巡检", { exact: true }).click();
    }

    // Artificially delay queue admission, without making a paid request.
    // The already loaded confidence/evidence must remain readable meanwhile.
    const gate = new Promise((resolve) => { releaseInspection = resolve; });
    let held = false;
    await page.route("**/queue/join*", async (route) => {
      if (route.request().postDataJSON()?.fn_index === inspectFn) {
        held = true;
        await gate;
      }
      await route.continue();
    });
    await click("查看 / 执行实时巡检");
    const deadline = Date.now() + 5000;
    while (!held && Date.now() < deadline) await page.waitForTimeout(25);
    assert.ok(held, JSON.stringify({ inspectFn, recentRequests: posts.slice(-20) }));
    await page.getByRole("button", { name: "查看 / 执行实时巡检", exact: true }).evaluate((el) => el.click());
    await page.waitForTimeout(700);
    const firstTimer = (await page.locator("#inspect-progress").innerText()).match(/(\d+(?:\.\d+)?)s\b/);
    assert.ok(firstTimer, "The scoped loading strip must show elapsed time");
    await page.waitForTimeout(500);
    const nextTimer = (await page.locator("#inspect-progress").innerText()).match(/(\d+(?:\.\d+)?)s\b/);
    assert.ok(nextTimer && Number(nextTimer[1]) > Number(firstTimer[1]), "Loading time must advance");
    if (process.env.TUZHENGGUARD_PROGRESS_SCREENSHOT) {
      await page.locator("#inspect-progress").screenshot({ path: process.env.TUZHENGGUARD_PROGRESS_SCREENSHOT });
    }
    for (const id of ["field-confidence", "amap-evidence", "inspection-evidence"]) {
      assert.equal(await page.locator(`#${id} .generating,#${id} .pending`).count(), 0);
      assert.ok((await page.locator(`#${id}`).innerText()).trim());
    }
    assert.equal(posts.filter((id) => id === inspectFn).length - beforeHeldInspection, 1, "Repeated click submitted twice");
    releaseInspection();
    await contains("本地确定性规则：0 个风险");
    await settled();
    await page.unroute("**/queue/join*");
    assert.ok((await page.locator("#inspect-progress").innerText()).includes("执行耗时"));

    // A failed queue connection must preserve results and permit explicit retry.
    await page.route("**/queue/join*", (route) => route.abort("failed"));
    await click("查看 / 执行实时巡检");
    await settled();
    assert.ok((await page.locator("#field-confidence").innerText()).includes("events[0].cost_cny"));
    assert.equal(await page.locator(".generating,.pending").count(), 0);
    await page.unroute("**/queue/join*");
    await click("查看 / 执行实时巡检");
    await settled();
    await page.reload({ waitUntil: "domcontentloaded" });
    await contains("本地风险 1 → 0");
    await settled();
    assert.ok((await page.locator("body").innerText()).includes("检出 0 个风险"));
    assert.equal(await page.locator(".generating,.pending").count(), 0);
    assert.deepEqual(pageErrors, []);
    console.log(JSON.stringify({ passed: true, viewport: mobile ? "390px" : "desktop", scenarios: ["validation-error", "pending-plan-survives-inspection", "selected-option-preserved", "parse-risk-plan-apply", "live-elapsed-timer", "slow-request-readable-panels", "duplicate-click", "network-failure-retry", "history-reload"], paid_cloud_calls: 0 }));
  } finally {
    releaseInspection?.();
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
