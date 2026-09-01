import { request } from 'playwright';
import fs from 'node:fs';

const ctx = await request.newContext({
  storageState: '.auth/state.json',
  baseURL: 'https://cortex.scaler.com',
});

const get = async (p) => {
  const r = await ctx.get(p);
  return { status: r.status(), body: r.ok() ? await r.json().catch(() => null) : null };
};

const course = await get('/api/courses/AIML001');
fs.writeFileSync('data/raw/api-course-aiml.json', JSON.stringify(course.body, null, 2));
console.log('course status', course.status);

const walk = (o, d = 0, path = '') => {
  if (d > 3 || o == null) return;
  if (Array.isArray(o)) {
    console.log(`${'  '.repeat(d)}${path}[] len=${o.length}`);
    if (o[0]) walk(o[0], d + 1, path + '[0]');
    return;
  }
  if (typeof o === 'object') {
    for (const [k, v] of Object.entries(o)) {
      const t = Array.isArray(v) ? `array(${v.length})` : typeof v;
      const prev = (typeof v === 'string') ? ` = ${JSON.stringify(v.slice(0, 70))}` : (t === 'number' || t === 'boolean' ? ` = ${v}` : '');
      console.log(`${'  '.repeat(d)}${k}: ${t}${prev}`);
      if (v && typeof v === 'object') walk(v, d + 1, k);
    }
  }
};
console.log('===== /api/courses/AIML001 SHAPE =====');
walk(course.body);

// find a class id and probe class endpoints
const s = JSON.stringify(course.body);
const ids = [...new Set([...s.matchAll(/"id":"(c[a-z0-9]{20,})"/g)].map(m => m[1]))];
console.log('\ndistinct cuid-ish ids found:', ids.length);
const cid = 'cmrlq84kp1vl1qj0fit7ixx1p';
for (const p of [`/api/classes/${cid}`, `/api/class/${cid}`, `/api/courses/AIML001/class/${cid}`, `/api/classes/${cid}/content`]) {
  const r = await ctx.get(p);
  console.log(`${r.status()} ${p}`);
  if (r.ok()) fs.writeFileSync('data/raw/api-class-sample.json', await r.text());
}
await ctx.dispose();
