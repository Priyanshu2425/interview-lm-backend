import { chromium } from 'playwright';
import fs from 'node:fs';

const ctx = await (await chromium.launch({ headless: true }))
  .newContext({ storageState: '.auth/state.json' });
const page = await ctx.newPage();

const api = [];
page.on('response', async (r) => {
  const u = r.url();
  if (u.includes('/_next/static')) return;
  const ct = (r.headers()['content-type'] || '');
  if (ct.includes('json') || u.includes('/api/')) {
    let body = '';
    try { body = (await r.text()).slice(0, 600); } catch {}
    api.push({ status: r.status(), url: u, ct, body });
  }
});

for (const [name, url] of [
  ['aiml', 'https://cortex.scaler.com/course/AIML001'],
  ['dsa',  'https://cortex.scaler.com/course/cmjjnrppn0000sglhhbeomp2a'],
]) {
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 }).catch(e => console.log('nav err', e.message));
  await page.waitForTimeout(3000);
  fs.writeFileSync(`data/raw/${name}.html`, await page.content());
  const txt = await page.locator('body').innerText().catch(() => '');
  fs.writeFileSync(`data/raw/${name}.txt`, txt);
  const hrefs = await page.$$eval('a[href]', as => [...new Set(as.map(a => a.getAttribute('href')))]);
  fs.writeFileSync(`data/raw/${name}.links.json`, JSON.stringify(hrefs, null, 2));
  console.log(`\n##### ${name} url=${page.url()} textlen=${txt.length} links=${hrefs.length}`);
  console.log(txt.slice(0, 2500));
}

fs.writeFileSync('data/raw/api-calls.json', JSON.stringify(api, null, 2));
console.log('\n##### API/JSON RESPONSES');
for (const a of api) console.log(`${a.status} ${a.url}`);
await ctx.close();
process.exit(0);
