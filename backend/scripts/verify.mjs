import { request } from 'playwright';
import fs from 'node:fs';
const ctx = await request.newContext({ storageState: '.auth/state.json', baseURL: 'https://cortex.scaler.com' });

const dsa = await (await ctx.get('/api/courses/cmjjnrppn0000sglhhbeomp2a')).json();
fs.writeFileSync('data/raw/api-course-dsa.json', JSON.stringify(dsa, null, 2));
const aiml = JSON.parse(fs.readFileSync('data/raw/api-course-aiml.json','utf8'));

for (const [name, j] of [['AIML', aiml], ['DSA', dsa]]) {
  const c = j.course;
  const classes = c.modules.flatMap(m => m.topics.flatMap(t => t.classes.map(cl => ({...cl, module:m.title, topic:t.title}))));
  const byType = {};
  let chars = 0, withVideo = 0, withContest = 0, withQs = 0, empty = 0;
  for (const cl of classes) {
    byType[cl.contentType] = (byType[cl.contentType]||0)+1;
    const tc = cl.textContent || '';
    chars += tc.length;
    if (!tc.trim()) empty++;
    if (cl.videoUrl) withVideo++;
    if (cl.contestUrl) withContest++;
    if (cl.contestQuestions) withQs++;
  }
  console.log(`\n===== ${name}: modules=${c.modules.length} topics=${c.modules.reduce((a,m)=>a+m.topics.length,0)} classes=${classes.length}`);
  console.log('contentType:', JSON.stringify(byType));
  console.log(`textContent total=${(chars/1024).toFixed(0)}KB  empty=${empty}  video=${withVideo}  contestUrl=${withContest}  contestQuestions=${withQs}`);
  const titles = {};
  for (const cl of classes) titles[cl.title] = (titles[cl.title]||0)+1;
  console.log('top repeated class titles:', Object.entries(titles).sort((a,b)=>b[1]-a[1]).slice(0,8).map(([t,n])=>`${t}(${n})`).join(', '));
  const ak = classes.find(cl => /answer key/i.test(cl.title));
  if (ak) console.log(`ANSWER KEY sample len=${(ak.textContent||'').length}:\n`, (ak.textContent||'').slice(0,500));
  const cq = classes.find(cl => cl.contestQuestions);
  if (cq) console.log('contestQuestions sample:', JSON.stringify(cq.contestQuestions).slice(0,500));
}
// truncation check
const one = aiml.course.modules[0].topics[0].classes[0];
const detail = await (await ctx.get(`/api/classes/${one.id}`)).json();
console.log(`\nTRUNCATION CHECK tree=${(one.textContent||'').length} detail=${(detail.class.textContent||'').length} identical=${(one.textContent===detail.class.textContent)}`);
await ctx.dispose();
