#!/usr/bin/env node

const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("playwright");

async function main() {
  const [, , htmlPath, pdfPath] = process.argv;

  if (!htmlPath || !pdfPath) {
    console.error("Usage: render_pdf_playwright.js <input.html> <output.pdf>");
    process.exit(1);
  }

  const browser = await chromium.launch({
    headless: true,
  });

  try {
    const page = await browser.newPage();
    await page.goto(pathToFileURL(path.resolve(htmlPath)).href, {
      waitUntil: "networkidle",
    });
    await page.emulateMedia({ media: "print" });
    await page.pdf({
      path: path.resolve(pdfPath),
      printBackground: true,
      preferCSSPageSize: true,
    });
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
