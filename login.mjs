import { chromium } from 'playwright';
import fs from 'node:fs';

const PROFILE = '.auth/profile';
const STATE = '.auth/state.json';
const TARGET = 'https://cortex.scaler.com/dashboard';
const DEADLINE_MS = 8 * 60 * 1000;

const ctx = await chromium.launchPersistentContext(PROFILE, {
  headless: false,
  channel: 'chrome',
  viewport: null,
  args: ['--start-maximized'],
});

const page = ctx.pages()[0] ?? await ctx.newPage();
await page.goto(TARGET, { waitUntil: 'domcontentloaded' }).catch(() => {});

console.log('[login] browser open. complete Google sign-in in the window.');

const started = process.hrtime.bigint();
const elapsed = () => Number(process.hrtime.bigint() - started) / 1e6;

let ok = false;
while (elapsed() < DEADLINE_MS) {
  await page.waitForTimeout(2000);
  const url = page.url();
  let text = '';
  try { text = (await page.locator('body').innerText({ timeout: 3000 })).toLowerCase(); } catch {}
  const onDash = url.includes('cortex.scaler.com');
  const hasTracks = /interview prep|data structures|algorithms|dashboard/.test(text);
  const looksLoggedOut = /sign in|log in|continue with google/.test(text) && text.length < 4000;
  if (onDash && hasTracks && !looksLoggedOut) { ok = true; break; }
  console.log(`[login] waiting… url=${url} len=${text.length}`);
}

if (!ok) {
  console.log('[login] TIMEOUT or not detected. leaving browser open state unsaved.');
} else {
  const state = await ctx.storageState();
  fs.writeFileSync(STATE, JSON.stringify(state, null, 2));
  console.log(`[login] SAVED ${STATE} — cookies=${state.cookies.length} origins=${state.origins.length}`);
  fs.mkdirSync('data/raw', { recursive: true });
  fs.writeFileSync('data/raw/dashboard.html', await page.content());
  const txt = await page.locator('body').innerText();
  fs.writeFileSync('data/raw/dashboard.txt', txt);
  console.log('[login] recon dumped: data/raw/dashboard.{html,txt}');
  console.log('----- DASHBOARD TEXT -----');
  console.log(txt.slice(0, 4000));
}
await ctx.close();
