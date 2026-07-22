import { chromium } from 'playwright';

const [, , url, outputPath] = process.argv;

if (!url) {
  console.error('Usage: node render_feishu_page.mjs <url> [outputPath]');
  process.exit(1);
}

let browser;
try {
  browser = await chromium.launch({ headless: true });
} catch (err) {
  console.error('[Feishu render] 启动 Chromium 失败：' + (err && err.message ? err.message : err));
  console.error('[Feishu render] 若提示找不到浏览器，请在该 skill 目录运行：npx playwright install chromium');
  process.exit(1);
}
const context = await browser.newContext({
  viewport: { width: 1440, height: 2200 },
  locale: 'zh-CN',
});
const page = await context.newPage();

async function autoScroll() {
  await page.evaluate(async () => {
    await new Promise((resolve) => {
      let totalHeight = 0;
      const distance = 1000;
      const timer = setInterval(() => {
        const scrollHeight = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
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
  await page.waitForTimeout(2500);
  await autoScroll();
  await page.waitForTimeout(1500);
  await page.emulateMedia({ media: 'screen' });

  const payload = await page.evaluate(() => {
    const titleSelectors = ['h1', '[class*="title"]', '[data-testid*="title"]', '.wiki-title'];
    const contentSelectors = ['article', 'main', '.wiki-content', '[class*="doc-content"]', '[class*="wiki-content"]'];

    const getText = (selectors) => {
      for (const selector of selectors) {
        const node = document.querySelector(selector);
        const text = node?.innerText?.trim();
        if (text) return text;
      }
      return '';
    };

    let title = getText(titleSelectors) || document.title || '飞书文档';
    title = title.replace(/\s*-\s*飞书.*/, '').trim();
    const bodyText = getText(contentSelectors) || document.body.innerText || '';
    return {
      title,
      body_text: bodyText,
      source_url: location.href,
    };
  });

  if (outputPath) {
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
  }

  console.log(JSON.stringify(payload));
} finally {
  await browser.close();
}
