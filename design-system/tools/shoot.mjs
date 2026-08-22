import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
const OUT = process.argv[2] || './shots';
mkdirSync(OUT, { recursive: true });
const BASE = process.env.BASE || 'http://127.0.0.1:8899';
const screens = ['01-session-setup','02-topic-visit','03-visit-result','04-session-summary','05-credits','06-code-visit','07-voice-visit','08-operator'];
const b = await chromium.launch();
const errs = [];
for (const [name, vp, full] of [['desktop',{width:1440,height:940},true],['mobile',{width:390,height:844},true]]) {
  const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: 2 });
  const p = await ctx.newPage();
  p.on('console', m => { if (m.type()==='error') errs.push(`${name}:${m.text()}`); });
  p.on('pageerror', e => errs.push(`${name}:PAGEERROR:${e.message}`));
  for (const s of screens) {
    await p.goto(`${BASE}/screens/${s}.html`, { waitUntil:'networkidle' });
    await p.waitForTimeout(400);
    await p.screenshot({ path:`${OUT}/${s}.${name}.png`, fullPage: full });
  }
  // overlays
  await p.goto(`${BASE}/screens/06-code-visit.html`, { waitUntil:'networkidle' });
  await p.evaluate(()=>{const o=document.getElementById('editor'); if(o) o.dataset.open='true';});
  await p.waitForTimeout(300);
  await p.screenshot({ path:`${OUT}/06-editor-open.${name}.png` });
  await p.goto(`${BASE}/screens/02-topic-visit.html`, { waitUntil:'networkidle' });
  await p.evaluate(()=>{const o=document.getElementById('sheet-state'); if(o) o.dataset.open='true';});
  await p.waitForTimeout(300);
  await p.screenshot({ path:`${OUT}/02-sheet-open.${name}.png` });
  await ctx.close();
}
// index
const ctx = await b.newContext({ viewport:{width:1440,height:940}, deviceScaleFactor:1.5 });
const p = await ctx.newPage();
p.on('pageerror', e => errs.push(`index:PAGEERROR:${e.message}`));
await p.goto(`${BASE}/index.html`, { waitUntil:'networkidle' });
await p.waitForTimeout(1500);
await p.screenshot({ path:`${OUT}/index.png` });
await b.close();
console.log(errs.length ? 'CONSOLE ERRORS:\n'+errs.join('\n') : 'no console errors');
