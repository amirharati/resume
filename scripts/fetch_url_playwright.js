#!/usr/bin/env node

const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("playwright");

async function main() {
  const [, , url, outDir, name, timeoutMsRaw] = process.argv;
  if (!url || !outDir || !name) {
    console.error("Usage: fetch_url_playwright.js <url> <out_dir> <name> [timeout_ms]");
    process.exit(1);
  }

  const timeoutMs = Number(timeoutMsRaw || "30000");
  await fs.mkdir(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.setDefaultTimeout(timeoutMs);

  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: timeoutMs });

    const title = await page.title();
    const finalUrl = page.url();
    const html = await page.content();
    const text = await page.evaluate(() => document.body?.innerText || "");

    const htmlPath = path.join(outDir, `${name}.rendered.html`);
    const textPath = path.join(outDir, `${name}.rendered.txt`);
    const metaPath = path.join(outDir, `${name}.rendered.meta.json`);

    await fs.writeFile(htmlPath, html, "utf8");
    await fs.writeFile(textPath, text, "utf8");
    await fs.writeFile(
      metaPath,
      JSON.stringify(
        {
          mode: "rendered",
          source_url: url,
          final_url: finalUrl,
          title,
          timeout_ms: timeoutMs,
        },
        null,
        2,
      ),
      "utf8",
    );

    console.log(htmlPath);
    console.log(textPath);
    console.log(metaPath);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
