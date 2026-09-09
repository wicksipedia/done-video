import { readFileSync, mkdirSync, renameSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// This script lives outside the repo, so Playwright is resolved from the app
// being recorded rather than from here. That keeps the recorder on whatever
// Playwright version the app already tests against.
const APP_DIR = process.env.APP_DIR;
if (!APP_DIR) throw new Error('APP_DIR must point at the app that depends on @playwright/test');
const { chromium } = createRequire(join(APP_DIR, 'noop.js'))('@playwright/test');

const here = dirname(fileURLToPath(import.meta.url));
const timings = JSON.parse(readFileSync(join(here, 'timings.json'), 'utf8'));
const beat = (id) => {
  const found = timings.find((t) => t.id === id);
  if (!found) throw new Error(`No timing for beat ${id}`);
  return found;
};

const SEGMENT = process.env.SEGMENT;
if (!['intro', 'before', 'after'].includes(SEGMENT)) {
  throw new Error('SEGMENT must be intro, before or after');
}
const ADMIN = process.env.ADMIN_URL ?? 'http://localhost:3001/admin/index.html';
// The page the intro and the sign-off rest on. Any URL works; a pull request
// reads well because it names the change without narration having to.
const PR_URL = process.env.PR_URL;
if (!PR_URL) throw new Error('PR_URL must point at the page the intro and outro show');

const outDir = join(here, 'clips');
mkdirSync(outDir, { recursive: true });

/** Slate's selection model lags raw CDP input, so every key press is paced. */
const KEY_DELAY = 72;
const SETTLE = 150;
/** Breathing room after each narration line so cuts do not clip speech. */
const BEAT_PAD = 250;
/** A held still frame reads as a stall past roughly this long. */
const MAX_STILL = 3500;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Beat and click timings, measured against the start of the recording.
 *
 * The audio track is built from these rather than from the narration lengths
 * alone. An action that outruns its line — typing, waiting for a crash — makes
 * the video beat longer than the audio beat, and concatenating the lines
 * back-to-back would let the narration run ahead a little more on every beat.
 */
const timeline = { beats: [], clicks: [], stingers: [] };

/** Shows the outcome badge and logs when its stinger should play. */
const badge = async (kind) => {
  await page.evaluate((k) => window.__badge(k), kind);
  timeline.stingers.push({ kind, at: elapsed() });
};
let recordingT0 = 0;
const elapsed = () => (Date.now() - recordingT0) / 1000;

const browser = await chromium.launch();
// Playwright letterboxes the viewport into the video frame rather than scaling
// it, so both must match. 1536x864 is 1080p divided by 1.25, which is the 125%
// browser zoom the SSW rule asks for once ffmpeg upscales the result.
const context = await browser.newContext({
  viewport: { width: 1536, height: 864 },
  deviceScaleFactor: 1,
  recordVideo: { dir: outDir, size: { width: 1536, height: 864 } },
});

/**
 * Installed on every document. The overlay is appended to <body> rather than
 * into the app, because the crash we are filming unmounts React's own root and
 * would take an overlay inside it down at the exact moment it matters.
 */
await context.addInitScript(() => {
  // Playwright's synthetic input never draws a pointer, so clicks look like
  // things happening by themselves. This draws one and moves it under the same
  // rule as the caption: attached to <body>, so it outlives React unmounting.
  window.__cursor = (x, y, clicking) => {
    let el = document.getElementById('__cursor');
    if (!el) {
      el = document.createElement('div');
      el.id = '__cursor';
      el.style.cssText = [
        'position:fixed',
        'z-index:2147483646',
        'width:22px',
        'height:22px',
        'margin:-3px 0 0 -3px',
        'border-radius:50%',
        'background:rgba(17,17,17,.28)',
        'border:2px solid rgba(255,255,255,.95)',
        'box-shadow:0 2px 8px rgba(0,0,0,.45)',
        'pointer-events:none',
        'transition:transform 90ms ease-out,background 120ms ease-out',
      ].join(';');
      document.body.appendChild(el);
    }
    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
    el.style.transform = clicking ? 'scale(.6)' : 'scale(1)';
    el.style.background = clicking
      ? 'rgba(236,72,21,.85)'
      : 'rgba(17,17,17,.28)';
  };

  // Same rule as the caption: attached to <body>, because the failure this
  // marks is the one that unmounts React's own root.
  window.__badge = (kind) => {
    const existing = document.getElementById('__badge');
    if (existing) existing.remove();
    if (!kind) return;
    const el = document.createElement('div');
    el.id = '__badge';
    el.textContent = kind === 'fail' ? '❌' : '✅';
    el.style.cssText = [
      'position:fixed',
      'top:26px',
      'right:32px',
      'z-index:2147483647',
      'font-size:86px',
      'line-height:1',
      'pointer-events:none',
      'filter:drop-shadow(0 4px 14px rgba(0,0,0,.45))',
      'transform:scale(.4)',
      'opacity:0',
      'transition:transform 220ms cubic-bezier(.2,1.6,.4,1),opacity 160ms ease-out',
    ].join(';');
    document.body.appendChild(el);
    requestAnimationFrame(() => {
      el.style.transform = 'scale(1)';
      el.style.opacity = '1';
    });
  };

  // Formatting applied by shortcut changes a few pixels of text and is over
  // before a viewer can see what caused it. Show the key that did it.
  window.__keycap = (label) => {
    const old = document.getElementById('__keycap');
    if (old) old.remove();
    if (!label) return;
    const el = document.createElement('div');
    el.id = '__keycap';
    el.textContent = label;
    el.style.cssText = [
      'position:fixed',
      'left:50%',
      'bottom:56px',
      'transform:translateX(-50%) scale(.7)',
      'z-index:2147483646',
      'padding:14px 26px',
      'border-radius:14px',
      'background:rgba(20,20,22,.92)',
      'border:1px solid rgba(255,255,255,.22)',
      'box-shadow:0 8px 26px rgba(0,0,0,.45)',
      'color:#fff',
      'font:600 40px/1 ui-sans-serif,system-ui,-apple-system,sans-serif',
      'letter-spacing:2px',
      'opacity:0',
      'pointer-events:none',
      'transition:transform 160ms cubic-bezier(.2,1.5,.4,1),opacity 130ms ease-out',
    ].join(';');
    document.body.appendChild(el);
    requestAnimationFrame(() => {
      el.style.transform = 'translateX(-50%) scale(1)';
      el.style.opacity = '1';
    });
  };

  window.__caption = (text) => {
    let el = document.getElementById('__caption');
    if (!el) {
      el = document.createElement('div');
      el.id = '__caption';
      el.style.cssText = [
        'position:fixed',
        'left:0',
        'right:0',
        'bottom:0',
        'z-index:2147483647',
        'padding:18px 28px',
        'background:linear-gradient(transparent,rgba(0,0,0,.82) 38%)',
        'color:#fff',
        'font:500 26px/1.35 ui-sans-serif,system-ui,-apple-system,sans-serif',
        'text-align:center',
        'pointer-events:none',
        'text-shadow:0 1px 3px rgba(0,0,0,.6)',
      ].join(';');
      document.body.appendChild(el);
    }
    el.textContent = text;
  };
});

const page = await context.newPage();
// Node's clock and the video's timeline do not share an origin: capture starts
// some hundreds of milliseconds after newPage() returns, which put every sound
// late by that much. Flash a marker the calibration pass can find, and measure
// the difference instead of assuming it is zero.
recordingT0 = Date.now();
await page.goto('about:blank');
// Wait before flashing it. A marker drawn immediately lands in frame 0 whatever
// the offset is, which bounds the answer instead of measuring it.
await sleep(1200);
await page.evaluate(() => {
  const el = document.createElement('div');
  el.id = '__sync';
  el.style.cssText =
    'position:fixed;left:0;bottom:0;width:12px;height:12px;' +
    'background:#ff00ff;z-index:2147483647;pointer-events:none';
  document.body.appendChild(el);
});
timeline.sync = elapsed();
await sleep(200);
await page.evaluate(() => document.getElementById('__sync')?.remove());
await sleep(150);

// Captions are redundant once there is narration, and two channels saying the
// same thing at once is worse than either alone.
const CAPTIONS = process.env.CAPTIONS !== 'off';

const say = async (id, action) => {
  const { seconds, caption, pauseAfter = 0 } = beat(id);
  const started = Date.now();
  const startedAt = elapsed();
  if (CAPTIONS) {
    await page.evaluate((t) => window.__caption(t), caption);
  }
  if (action) await action();
  const remaining = seconds * 1000 + BEAT_PAD - (Date.now() - started);
  if (remaining > 0) await sleep(remaining);
  // Silence the next line has to wait for. The synthesiser runs sentences
  // together, so a beat that needs to land gets its gap declared here.
  if (pauseAfter) await sleep(pauseAfter);
  timeline.beats.push({ id, start: startedAt, end: elapsed() });
};

/** Eases the drawn cursor to a point so the eye can follow it. */
let cursorAt = { x: 40, y: 40 };
const moveCursorTo = async (x, y, steps = 18) => {
  const from = cursorAt;
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    // easeInOutQuad keeps the start and stop soft rather than robotic.
    const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
    const px = from.x + (x - from.x) * e;
    const py = from.y + (y - from.y) * e;
    await page.evaluate(([a, b]) => window.__cursor(a, b, false), [px, py]);
    await sleep(16);
  }
  cursorAt = { x, y };
  await page.mouse.move(x, y);
};

/** Moves the drawn cursor onto the target, pulses it, then clicks for real. */
const clickWithCursor = async (locator) => {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error('Cannot click a locator with no box');
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await moveCursorTo(x, y);
  await sleep(180);
  await page.evaluate(([a, b]) => window.__cursor(a, b, true), [x, y]);
  // Logged at the visual press, which is where the click sound belongs. Keep
  // the press short so the colour change, the sound and the UI reacting all
  // read as one gesture rather than three events.
  timeline.clicks.push(elapsed());
  await sleep(70);
  await locator.click();
  await sleep(110);
  await page.evaluate(([a, b]) => window.__cursor(a, b, false), [x, y]);
  await sleep(120);
};

const press = async (key, times = 1, delay = KEY_DELAY) => {
  for (let i = 0; i < times; i++) {
    await page.keyboard.press(key);
    await sleep(delay);
  }
};

/**
 * Slate drops consecutive selection keys sent too close together, so word-wise
 * navigation is paced well above the typing rate.
 */
const NAV_DELAY = 180;
const navigate = (key, times = 1) => press(key, times, NAV_DELAY);

/* ---------------------------------------------------------------------------
 * Everything above is reusable. Everything below is one app's DOM and one bug's
 * reproduction steps, and is meant to be rewritten for each video.
 *
 * Two rules the rest of the pipeline depends on:
 *   - every beat id in beats.json is played exactly once, by say()
 *   - clicks go through clickWithCursor(), so the drawn pointer and the click
 *     sound land together
 * ------------------------------------------------------------------------ */

/** Puts the app in the state the demo starts from. Identical on both refs. */
const openTheThing = async () => {
  await page.goto(ADMIN);

  // A first-run dialog shows once per browser context, and every run gets a
  // fresh one — but it is still optional, so race it against the content
  // rather than waiting a fixed time for it.
  const dismiss = page.locator('button[data-test="dismiss-first-run"]');
  const content = page.locator('main');
  await Promise.race([
    dismiss.waitFor({ state: 'visible', timeout: 30000 }),
    content.waitFor({ state: 'visible', timeout: 30000 }),
  ]);
  if (await dismiss.isVisible().catch(() => false)) {
    await clickWithCursor(dismiss);
  }

  await content.waitFor({ timeout: 30000 });
  await sleep(SETTLE);
};

/** The ordinary-looking setup the viewer has to believe they would have done. */
const setUpTheScenario = async () => {
  // Replace with the real steps. pressSequentially types visibly; a bare fill()
  // snaps the whole string in and reads as a jump cut.
  await page.locator('input').first().pressSequentially('example', {
    delay: KEY_DELAY,
  });
  await sleep(SETTLE);
};

/** The single action that breaks on BEFORE_REF and behaves on AFTER_REF. */
const triggerTheBug = async () => {
  await clickWithCursor(page.locator('button', { hasText: 'Save' }));
  await sleep(900);
};

if (SEGMENT === 'intro') {
  await page.goto(PR_URL, { waitUntil: 'domcontentloaded' });
  await sleep(1200);
  await say('b0a', () => sleep(400));
  // A held screenshot of a page reads as a stall. Drift down it instead, which
  // also shows more of the description than the fold would.
  await say('b0', async () => {
    await page.evaluate(async () => {
      const distance = 520;
      const steps = 90;
      for (let i = 1; i <= steps; i++) {
        const t = i / steps;
        const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
        window.scrollTo(0, eased * distance);
        await new Promise((r) => setTimeout(r, 55));
      }
    });
  });
}

if (SEGMENT === 'before') {
  await openTheThing();
  await say('b1', setUpTheScenario);
  await say('b2', triggerTheBug);
  await say('b3', async () => {
    // Hold on the failure long enough to register, not long enough to stall.
    await sleep(Math.min(900, MAX_STILL));
    await badge('fail');
  });
}

if (SEGMENT === 'after') {
  await openTheThing();
  await say('b4', async () => {
    await setUpTheScenario();
    await triggerTheBug();
  });
  await say('b5', async () => {
    await sleep(600);
    await badge('pass');
  });
  // The close was landing too fast. Give the last two lines room either side so
  // the video settles instead of stopping.
  await say('b6', async () => {
    await sleep(2200);
    // The badge belongs to the demo, not to the sign-off.
    await page.evaluate(() => window.__badge(null));
    await page.goto(PR_URL, { waitUntil: 'domcontentloaded' });
    await sleep(1400);
  });
  await say('b7', () => sleep(600));
  await sleep(1200);
}

await page.evaluate(() => {
  document.getElementById('__caption')?.remove();
  document.getElementById('__cursor')?.remove();
  document.getElementById('__keycap')?.remove();
  document.getElementById('__badge')?.remove();
});
const video = page.video();
await context.close();
await browser.close();

const raw = await video.path();
const final = join(outDir, `${SEGMENT}.webm`);
renameSync(raw, final);

writeFileSync(
  join(outDir, `${SEGMENT}.timeline.json`),
  `${JSON.stringify(timeline, null, 2)}\n`
);

const held = timeline.beats
  .map((b) => `${b.id} ${(b.end - b.start).toFixed(1)}s`)
  .join('  ');
console.log(`wrote ${final}`);
console.log(`beats: ${held}`);
console.log(`clicks: ${timeline.clicks.map((c) => c.toFixed(1)).join(', ')}`);
