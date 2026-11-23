#!/usr/bin/env node
/**
 * CutsceneCity external Shorts CLI (talks only to your own server on 127.0.0.1).
 *   npm run cutscenecity:shorts -- ingest /abs/path/packages/short_01-xxxx/agent-import.json
 *   npm run cutscenecity:shorts -- list
 *   npm run cutscenecity:shorts -- approve <itemId>     (the per-upload human approval click; uploads PRIVATE)
 * Sends API_KEY from your .env; never prints it.
 */
require('dotenv').config({ quiet: true });
const fs = require('fs');
const readline = require('readline/promises');

const BASE = process.env.CUTSCENECITY_BASE_URL || `http://127.0.0.1:${process.env.PORT || 3456}`;

async function call(method, url, body) {
  const res = await fetch(BASE + url, {
    method,
    headers: { 'Content-Type': 'application/json', 'x-api-key': process.env.API_KEY || '' },
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    console.error(`${res.status}: ${data.error || res.statusText}`);
    (data.problems || []).forEach(p => console.error(`  - ${p}`));
    process.exit(1);
  }
  return data.result;
}

(async () => {
  const [cmd, arg] = process.argv.slice(2);
  if (cmd === 'ingest') {
    const item = await call('POST', '/api/gta6/external-shorts', JSON.parse(fs.readFileSync(arg, 'utf8')));
    console.log(`Pending approval: ${item.id}\n  "${item.title}" (synthetic media: ${item.containsSyntheticMedia ? 'YES' : 'no'})\n  confirm code = first 12 characters of ${item.packageSha256}`);
  } else if (cmd === 'list') {
    for (const i of await call('GET', '/api/gta6/external-shorts')) console.log(`${i.id}  ${i.status.padEnd(26)} ${i.title}${i.videoId ? `  -> ${i.videoId}` : ''}`);
  } else if (cmd === 'approve') {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const items = await call('GET', '/api/gta6/external-shorts');
    const item = items.find(i => i.id === arg);
    if (!item) throw new Error('no such item');
    console.log(`About to upload as PRIVATE (no publish date): "${item.title}"\n  Synthetic media disclosure: ${item.containsSyntheticMedia ? 'YES' : 'no'}\n  File: ${item.videoPath}`);
    const reviewer = (await rl.question('Your name (recorded in the audit log): ')).trim();
    const confirm = (await rl.question('Type the 12-character confirm code to upload: ')).trim();
    rl.close();
    const r = await call('POST', `/api/gta6/external-shorts/${arg}/approve-upload`, { reviewer, confirm });
    console.log(`Uploaded PRIVATE: ${r.videoId}\nCheck it in Studio: ${r.studioUrl}`);
  } else {
    console.log('usage: cutscenecity-shorts ingest <agent-import.json> | list | approve <itemId>');
  }
})().catch(e => { console.error(e.message); process.exit(1); });
