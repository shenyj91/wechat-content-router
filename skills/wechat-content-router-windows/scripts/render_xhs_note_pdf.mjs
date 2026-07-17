import { chromium } from 'playwright';

const [, , url, outputPath] = process.argv;
const cookieHeader = process.env.XHS_COOKIE_HEADER || '';

if (!url || !outputPath) {
  console.error('Usage: node render_xhs_note_pdf.mjs <url> <outputPath>');
  process.exit(1);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 2200 },
  locale: 'zh-CN',
  userAgent:
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0 Safari/537.36',
  ...(cookieHeader ? { extraHTTPHeaders: { Cookie: cookieHeader } } : {}),
});
const page = await context.newPage();

async function autoScroll() {
  await page.evaluate(async () => {
    await new Promise((resolve) => {
      let totalHeight = 0;
      const distance = 900;
      const timer = setInterval(() => {
        const scrollHeight = document.body.scrollHeight;
        window.scrollBy(0, distance);
        totalHeight += distance;
        if (totalHeight >= scrollHeight + 1200) {
          clearInterval(timer);
          resolve();
        }
      }, 180);
    });
  });
}

try {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2200);
  await autoScroll();
  await page.waitForTimeout(1200);
  await page.emulateMedia({ media: 'screen' });
  await page.pdf({
    path: outputPath,
    format: 'A4',
    printBackground: true,
    margin: {
      top: '10mm',
      right: '8mm',
      bottom: '10mm',
      left: '8mm',
    },
  });
  console.log(outputPath);
} finally {
  await browser.close();
}
