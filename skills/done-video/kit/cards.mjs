import { mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const APP_DIR = process.env.APP_DIR;
if (!APP_DIR) throw new Error('APP_DIR must point at the app that depends on @playwright/test');
const { chromium } = createRequire(join(APP_DIR, 'noop.js'))('@playwright/test');

// This ffmpeg build has no libfreetype, so no drawtext filter. Rendering the
// cards in the browser also keeps their type identical to the captions.
// Subtitles say which ref is on screen, so they stay generic. Naming the
// specific change here is how a card from a previous video ends up in the next
// one; override per video if a name really helps.
const CARDS = [
  {
    file: 'card-before.png',
    title: process.env.CARD_BEFORE ?? 'Before the fix',
    sub: process.env.CARD_BEFORE_SUB ?? 'on main',
  },
  {
    file: 'card-after.png',
    title: process.env.CARD_AFTER ?? 'After the fix',
    sub: process.env.CARD_AFTER_SUB ?? 'on the fix branch',
  },
];

const outDir = join(here, 'cards');
mkdirSync(outDir, { recursive: true });

const html = ({ title, sub }) => `<!doctype html>
<meta charset="utf-8">
<style>
  html,body { margin:0; height:100%; }
  body {
    background:#111214;
    color:#fff;
    display:flex;
    flex-direction:column;
    align-items:center;
    justify-content:center;
    gap:18px;
    font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;
  }
  h1 { margin:0; font-size:82px; font-weight:600; letter-spacing:-.02em; }
  p  { margin:0; font-size:34px; font-weight:400; color:#9aa0a6; }
  .rule { width:120px; height:4px; background:#ec4815; border-radius:2px; }
</style>
<div class="rule"></div>
<h1>${title}</h1>
<p>${sub}</p>`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
for (const card of CARDS) {
  await page.setContent(html(card));
  await page.screenshot({ path: join(outDir, card.file) });
  console.log(`wrote cards/${card.file}`);
}
await browser.close();
