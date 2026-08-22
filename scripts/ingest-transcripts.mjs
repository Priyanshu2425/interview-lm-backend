// Fills stub_video Classes from data/pending-transcripts.json into data/markdown/.
// Run after populating each entry's `transcript` field.
import fs from 'node:fs';
import path from 'node:path';

const p = JSON.parse(fs.readFileSync('data/pending-transcripts.json', 'utf8'));
let n = 0;
for (const c of p.classes) {
  if (!c.transcript || !String(c.transcript).trim()) continue;
  const out = path.join('data/markdown', c.markdownPath);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const fm = ['---', `id: ${c.id}`, `title: ${JSON.stringify(c.title)}`,
    `module: ${JSON.stringify(c.module)}`, `topic: ${JSON.stringify(c.topic)}`,
    'kind: lecture_transcript', 'contentType: video', 'source: transcript', '---'].join('\n');
  fs.writeFileSync(out, `${fm}\n\n${String(c.transcript).trim()}\n`);
  n++;
}
console.log(`transcripts ingested: ${n} / ${p.classes.length}`);
