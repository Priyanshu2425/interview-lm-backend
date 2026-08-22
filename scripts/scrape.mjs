import { request } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const TRACKS = [
  { key: 'aiml', id: 'AIML001' },
  { key: 'dsa',  id: 'cmjjnrppn0000sglhhbeomp2a' },
];

const slug = (s, n = 60) => String(s).toLowerCase()
  .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, n) || 'untitled';
const pad = (n) => String(n).padStart(2, '0');

// Classify a Class by its title. Drives how the Interviewer may use it.
function kindOf(title) {
  const t = String(title).trim().toLowerCase();
  if (/^answer key/.test(t))                       return 'answer_key';
  if (/^assignment\b/.test(t))                     return 'assignment';
  if (/key concepts|intuition/.test(t))            return 'concepts';
  if (/interview[- ]specific|focus areas/.test(t)) return 'interview_insights';
  if (/revis/.test(t))                             return 'revision';
  return 'other';
}

const ctx = await request.newContext({
  storageState: '.auth/state.json',
  baseURL: 'https://cortex.scaler.com',
});

const scrapedAt = new Date().toISOString();
const corpus = { scrapedAt, source: 'cortex.scaler.com', tracks: [] };
const classes = [];

for (const t of TRACKS) {
  const res = await ctx.get(`/api/courses/${t.id}`);
  if (!res.ok()) throw new Error(`${t.id} -> HTTP ${res.status()}`);
  const c = (await res.json()).course;
  fs.mkdirSync('data/raw', { recursive: true });
  fs.writeFileSync(`data/raw/api-course-${t.key}.json`, JSON.stringify({ course: c }, null, 2));

  const track = {
    key: t.key, id: c.id, title: c.title, role: c.role,
    description: c.description, modules: [],
  };

  for (const m of [...c.modules].sort((a, b) => a.order - b.order)) {
    const mod = {
      id: m.id, order: m.order, title: m.title,
      description: m.description, learningOutcomes: m.learningOutcomes ?? [],
      topics: [],
    };
    for (const tp of [...m.topics].sort((a, b) => a.order - b.order)) {
      const topic = { id: tp.id, order: tp.order, title: tp.title, classes: [] };
      const ordered = [...tp.classes].sort((a, b) => a.order - b.order);

      for (const cl of ordered) {
        const text = (cl.textContent || '').trim();
        const status = text ? 'complete'
          : cl.contentType === 'video' ? 'stub_video'
          : cl.contentType === 'contest' ? 'stub_contest'
          : 'stub_empty';
        const rel = path.join(
          t.key,
          `${pad(m.order)}-${slug(m.title)}`,
          `${pad(tp.order)}-${slug(tp.title)}`,
          `${pad(cl.order)}-${slug(cl.title)}.md`,
        );
        const rec = {
          id: cl.id, trackKey: t.key, trackTitle: c.title,
          moduleId: m.id, moduleOrder: m.order, moduleTitle: m.title,
          topicId: tp.id, topicOrder: tp.order, topicTitle: tp.title,
          order: cl.order, title: String(cl.title).trim(), description: cl.description || null,
          contentType: cl.contentType, kind: kindOf(cl.title),
          duration: cl.duration ?? null, status,
          chars: text.length,
          markdownPath: rel,
          url: `https://cortex.scaler.com/course/${c.id}/class/${cl.id}`,
          videoUrl: cl.videoUrl ?? null,
          contestUrl: cl.contestUrl ?? null,
          contestQuestions: cl.contestQuestions ?? null,
          contestSyllabus: cl.contestSyllabus ?? [],
          answerKeyId: null, assignmentId: null,
          text,
        };
        topic.classes.push(rec);
        classes.push(rec);
      }

      // Pair each Assignment with the Answer Key that follows it in the Topic.
      for (let i = 0; i < topic.classes.length; i++) {
        if (topic.classes[i].kind !== 'assignment') continue;
        const ak = topic.classes.slice(i + 1).find(x => x.kind === 'answer_key');
        if (ak) { topic.classes[i].answerKeyId = ak.id; ak.assignmentId = topic.classes[i].id; }
      }
      mod.topics.push(topic);
    }
    track.modules.push(mod);
  }
  corpus.tracks.push(track);
}

// ---- emit markdown, one file per Class with content ----
let written = 0;
for (const rec of classes) {
  if (!rec.text) continue;
  const out = path.join('data/markdown', rec.markdownPath);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const fm = [
    '---',
    `id: ${rec.id}`,
    `title: ${JSON.stringify(rec.title)}`,
    `track: ${JSON.stringify(rec.trackTitle)}`,
    `module: ${JSON.stringify(rec.moduleTitle)}`,
    `topic: ${JSON.stringify(rec.topicTitle)}`,
    `kind: ${rec.kind}`,
    `contentType: ${rec.contentType}`,
    rec.description ? `description: ${JSON.stringify(rec.description)}` : null,
    rec.answerKeyId ? `answerKeyId: ${rec.answerKeyId}` : null,
    rec.assignmentId ? `assignmentId: ${rec.assignmentId}` : null,
    `url: ${rec.url}`,
    '---',
  ].filter(Boolean).join('\n');
  fs.writeFileSync(out, `${fm}\n\n${rec.text}\n`);
  written++;
}

// strip inline text from the index; markdown files hold it
const index = JSON.parse(JSON.stringify(corpus));
for (const tr of index.tracks) for (const m of tr.modules) for (const tp of m.topics)
  for (const cl of tp.classes) delete cl.text;
fs.mkdirSync('data', { recursive: true });
fs.writeFileSync('data/corpus.json', JSON.stringify(index, null, 2));

// ---- report ----
const by = (f) => classes.reduce((a, c) => (a[f(c)] = (a[f(c)] || 0) + 1, a), {});
console.log(`markdown files written: ${written}`);
console.log('status:', JSON.stringify(by(c => `${c.trackKey}:${c.status}`)));
console.log('kind:  ', JSON.stringify(by(c => c.kind)));
const pairs = classes.filter(c => c.answerKeyId).length;
console.log(`assignment→answer-key pairs: ${pairs}`);
const kb = classes.reduce((a, c) => a + c.chars, 0) / 1024;
console.log(`total content: ${kb.toFixed(0)} KB across ${classes.length} classes`);
await ctx.dispose();
