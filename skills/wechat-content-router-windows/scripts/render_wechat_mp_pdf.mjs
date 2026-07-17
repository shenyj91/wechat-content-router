import { chromium } from 'playwright';

const [, , url, outputPath] = process.argv;

if (!url || !outputPath) {
  console.error('Usage: node render_wechat_mp_pdf.mjs <url> <outputPath>');
  process.exit(1);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1280, height: 1600 },
  locale: 'zh-CN',
});
const page = await context.newPage();

try {
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
  await page.emulateMedia({ media: 'screen' });
  await page.waitForTimeout(1500);
  await page.pdf({
    path: outputPath,
    format: 'A4',
    printBackground: true,
    margin: {
      top: '12mm',
      right: '10mm',
      bottom: '12mm',
      left: '10mm',
    },
  });
  console.log(outputPath);
} finally {
  await browser.close();
}
