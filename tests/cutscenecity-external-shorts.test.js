// node --test tests/cutscenecity-external-shorts.test.js
// Builds real signed packages with the Python review CLI, then drives the Express routes with a MOCKED YouTube client.
const test = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync } = require('child_process');
const express = require('express');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {
  ExternalShortsService, registerExternalShortsRoutes, canonicalJson, validateImport, checkClipGates, isMixedTrack, loadPolicy, ownerMatch, checkScript, effectiveDailyCap, REQUIRED_HUMAN_CHECKS,
  captionFlags, renderEditProblems, STYLE_EFFECTS, FLASH_MAX_PER_CLIP, FLASH_MAX_INTENSITY, mixedTrackAllowed, HARD_DAILY_CAP
} = require('../utils/cutscenecity/external-shorts');

const PY = process.env.CUTSCENECITY_PYTHON || 'python3';
const FIXTURE = path.join(__dirname, 'fixtures', 'make_cutscenecity_package.py');
const REVIEW_KEY = 'k'.repeat(40);
const API_KEY = 'test-api-key-0123456789';

const OWNER = { CUTSCENECITY_OWNER_TWITCH_LOGIN: 'cutscenecity' };

function makePackage(work, args = [], stateDir = path.join(work, 'state')) {
  const out = execFileSync(PY, [FIXTURE, work, ...args], {
    env: { ...process.env, CUTSCENECITY_REVIEW_KEY: REVIEW_KEY, ...OWNER, CUTSCENECITY_STATE_DIR: stateDir }, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']
  });
  const dir = out.trim().split('\n').pop().replace('PACKAGE_DIR=', '');
  return { dir, body: JSON.parse(fs.readFileSync(path.join(dir, 'agent-import.json'), 'utf8')) };
}

function fakeYouTube({ privacy = 'private', fail = false } = {}) {
  const calls = [];
  return {
    calls,
    videos: {
      insert: async args => {
        calls.push(args);
        if (!args.media) throw new Error('no media');
        args.media.body.destroy();
        if (fail) throw new Error('socket hang up');
        return { data: { id: 'VID123', status: { privacyStatus: privacy } } };
      }
    }
  };
}

async function setup(t, { env: extraEnv = {}, youtube = fakeYouTube(), packages = 1, pkgArgs = [] } = {}) {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-node-'));
  const pkgs = [];
  for (let i = 0; i < packages; i++) {
    const args = typeof pkgArgs === 'function' ? pkgArgs(i) : pkgArgs;
    pkgs.push(makePackage(path.join(work, `w${i}`), args, path.join(work, 'state')));
  }
  const env = {
    API_KEY, CUTSCENECITY_REVIEW_KEY: REVIEW_KEY, ...OWNER,
    CUTSCENECITY_PACKAGES_DIR: work, CUTSCENECITY_STATE_DIR: path.join(work, 'state'), ...extraEnv
  };
  const service = new ExternalShortsService({ env, storePath: path.join(work, 'store.json'), youtubeProvider: () => youtube });
  const app = express();
  app.use(express.json());
  registerExternalShortsRoutes(app, () => service, { env });
  const server = await new Promise(r => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
  t.after(() => { server.close(); fs.rmSync(work, { recursive: true, force: true }); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const call = async (method, url, body, key = API_KEY) => {
    const res = await fetch(base + url, {
      method, headers: { 'Content-Type': 'application/json', ...(key ? { 'x-api-key': key } : {}) },
      body: body ? JSON.stringify(body) : undefined
    });
    return { status: res.status, json: await res.json() };
  };
  return { work, pkgs, service, call, youtube, env };
}

test('canonical JSON matches Python json.dumps(sort_keys, compact, ensure_ascii)', () => {
  const py = execFileSync(PY, ['-c', 'import json,sys;print(json.dumps(json.loads(sys.argv[1]),sort_keys=True,separators=(",",":")))',
    JSON.stringify({ b: [1, 'é😀\u007f', null, true], a: 'x\n"\t' })], { encoding: 'utf8' }).trim();
  assert.equal(canonicalJson({ b: [1, 'é😀\u007f', null, true], a: 'x\n"\t' }), py);
  assert.throws(() => canonicalJson({ a: 1.5 }));
});

test('schema validation rejects publishAt, public, MFK and unknown fields', () => {
  const problems = validateImport({ type: 'external_short', privacyStatus: 'public', selfDeclaredMadeForKids: true, nested: { publishAt: 'x' } });
  const text = problems.join(' | ');
  for (const s of ['publishAt', 'privacyStatus must be private', 'selfDeclaredMadeForKids', 'unknown fields']) assert.match(text, new RegExp(s));
});

test('auth: 503 without API_KEY configured, 401 with wrong key', async t => {
  const { call } = await setup(t, { env: { API_KEY: '' } });
  assert.equal((await call('GET', '/api/gta6/external-shorts')).status, 503);
  const ctx = await setup(t);
  assert.equal((await ctx.call('GET', '/api/gta6/external-shorts', null, 'wrong')).status, 401);
  assert.equal((await ctx.call('GET', '/api/gta6/external-shorts', null, null)).status, 401);
});

test('ingest stores a pending item and never uploads; approval click uploads PRIVATE once', async t => {
  const { pkgs, call, youtube, env } = await setup(t);
  const { body } = pkgs[0];
  const ing = await call('POST', '/api/gta6/external-shorts', body);
  assert.equal(ing.status, 201, JSON.stringify(ing.json));
  assert.equal(ing.json.result.status, 'pending_approval');
  assert.equal(ing.json.result.autoUpload, false);
  assert.equal(youtube.calls.length, 0, 'ingest must not upload');
  const id = ing.json.result.id;
  assert.equal((await call('POST', `/api/gta6/external-shorts/${id}/approve-upload`, { reviewer: 'Shebin', confirm: 'wrong' })).status, 400);
  assert.equal((await call('POST', `/api/gta6/external-shorts/${id}/approve-upload`, { confirm: body.packageSha256.slice(0, 12) })).status, 400);
  const ok = await call('POST', `/api/gta6/external-shorts/${id}/approve-upload`, { reviewer: 'Shebin', confirm: body.packageSha256.slice(0, 12) });
  assert.equal(ok.status, 200, JSON.stringify(ok.json));
  assert.equal(youtube.calls.length, 1);
  const status = youtube.calls[0].requestBody.status;
  assert.equal(status.privacyStatus, 'private');
  assert.equal(status.selfDeclaredMadeForKids, false);
  assert.equal(status.containsSyntheticMedia, false);
  assert.ok(!('publishAt' in status));
  assert.deepEqual(youtube.calls[0].requestBody.paidProductPlacementDetails, { hasPaidProductPlacement: false });
  assert.equal(youtube.calls[0].part, 'snippet,status,paidProductPlacementDetails');
  const ledger = fs.readFileSync(path.join(env.CUTSCENECITY_STATE_DIR, 'upload-audit.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  assert.deepEqual(ledger.map(e => e.status), ['ATTEMPT', 'UPLOADED']);
  assert.equal(ledger[0].approved_by, 'Shebin');
  const again = await call('POST', `/api/gta6/external-shorts/${id}/approve-upload`, { reviewer: 'Shebin', confirm: body.packageSha256.slice(0, 12) });
  assert.equal(again.status, 409);
  const dup = await call('POST', '/api/gta6/external-shorts', body);
  assert.equal(dup.status, 422);
  assert.match(dup.json.problems.join(' '), /duplicate/);
});

test('TTS counts toward commentary but forces containsSyntheticMedia=true', async t => {
  const { pkgs, call, youtube, env } = await setup(t, { pkgArgs: ['--tts', '--synthetic'] });
  const { body } = pkgs[0];
  assert.equal(body.containsSyntheticMedia, true);
  const ing = await call('POST', '/api/gta6/external-shorts', body);
  assert.equal(ing.status, 201, JSON.stringify(ing.json));
  await call('POST', `/api/gta6/external-shorts/${ing.json.result.id}/approve-upload`, { reviewer: 'Shebin', confirm: body.packageSha256.slice(0, 12) });
  assert.equal(youtube.calls[0].requestBody.status.containsSyntheticMedia, true);
  const ledger = fs.readFileSync(path.join(env.CUTSCENECITY_STATE_DIR, 'upload-audit.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(ledger[0].voice_preset, 'charon-relaxed');
});

test('TTS without the AI flag cannot even be exported by Python', async t => {
  const ctx = await setup(t);
  assert.throws(() => makePackage(path.join(ctx.work, 'x'), ['--tts', '--script-variant', '3'], ctx.env.CUTSCENECITY_STATE_DIR), /Command failed/);
});

test('tampering: edited import, edited clip metadata, replaced video, wrong review key, outside root', async t => {
  const { pkgs, call, work } = await setup(t);
  const { body, dir } = pkgs[0];
  let r = await call('POST', '/api/gta6/external-shorts', { ...body, title: 'Different title' });
  assert.equal(r.status, 422);
  r = await call('POST', '/api/gta6/external-shorts', { ...body, privacyStatus: 'public' });
  assert.equal(r.status, 400);
  r = await call('POST', '/api/gta6/external-shorts', { ...body, publishAt: '2026-12-01T00:00:00Z' });
  assert.equal(r.status, 400);
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-out-'));
  fs.writeFileSync(path.join(outside, 'video.mp4'), 'x');
  r = await call('POST', '/api/gta6/external-shorts', { ...body, videoPath: path.join(outside, 'video.mp4') });
  assert.equal(r.status, 403);
  fs.rmSync(outside, { recursive: true, force: true });
  const clipPath = path.join(dir, 'clip.json');
  const clip = JSON.parse(fs.readFileSync(clipPath, 'utf8'));
  fs.writeFileSync(clipPath, JSON.stringify({ ...clip, metadata: { ...clip.metadata, tags: ['changed'] } }));
  r = await call('POST', '/api/gta6/external-shorts', body);
  assert.equal(r.status, 422);
  assert.match(r.json.problems.join(' '), /metadata changed after signed approval/);
  fs.writeFileSync(clipPath, JSON.stringify(clip));
  fs.appendFileSync(path.join(dir, 'video.mp4'), 'extra');
  r = await call('POST', '/api/gta6/external-shorts', body);
  assert.match(r.json.problems.join(' '), /not the approved file/);
  assert.ok(work);
});

test('wrong review key is blocked', async t => {
  const ctx = await setup(t, { env: { CUTSCENECITY_REVIEW_KEY: 'z'.repeat(40) } });
  const r = await ctx.call('POST', '/api/gta6/external-shorts', ctx.pkgs[0].body);
  assert.equal(r.status, 422);
  assert.match(r.json.problems.join(' '), /review log/);
});

test('creator-owned gate: owner unset or different blocks ingest (fail closed)', async t => {
  let ctx = await setup(t, { env: { CUTSCENECITY_OWNER_TWITCH_LOGIN: '' } });
  let r = await ctx.call('POST', '/api/gta6/external-shorts', ctx.pkgs[0].body);
  assert.equal(r.status, 201, 'env unset: policy default owner_twitch_login=cutscenecity applies');
  const clip = JSON.parse(fs.readFileSync(path.join(ctx.pkgs[0].dir, 'clip.json'), 'utf8'));
  const { policy, spoilerTerms } = loadPolicy(path.join(__dirname, '..', 'tools', 'twitch-shorts'));
  assert.equal(policy.owner_twitch_login, 'cutscenecity');
  const noOwner = checkClipGates(clip, { env: {}, policy: { ...policy, owner_twitch_login: '' }, spoilerTerms, history: [] });
  assert.match(noOwner.join(' '), /owner not configured/);
  ctx = await setup(t, { env: { CUTSCENECITY_OWNER_TWITCH_LOGIN: 'someone-else' } });
  r = await ctx.call('POST', '/api/gta6/external-shorts', ctx.pkgs[0].body);
  assert.match(r.json.problems.join(' '), /is not the owner/);
  assert.throws(() => makePackage(path.join(ctx.work, 'foreign'), ['--uploader-id', 'otherstreamer'], ctx.env.CUTSCENECITY_STATE_DIR), /Command failed/);
});

test('ownerMatch unit cases', () => {
  const env = OWNER;
  assert.equal(ownerMatch({ uploader_id: 'CutsceneCity' }, env)[0], true);
  assert.equal(ownerMatch({ channel: 'cutscenecity' }, env)[0], true);
  assert.equal(ownerMatch({ uploader_id: 'other' }, env)[0], false);
  assert.equal(ownerMatch({ uploader: 'CutsceneCity' }, env)[0], false, 'display name alone is not proof');
  assert.equal(ownerMatch({}, env)[0], false);
  assert.equal(ownerMatch({ uploader_id: 'cutscenecity' }, {})[0], false, 'no env and no policy default: fail closed');
  assert.equal(ownerMatch({ uploader_id: 'cutscenecity' }, {}, 'cutscenecity')[0], true, 'policy default');
  for (const other of ['ishowspeed', 'cutscenecity_fan', 'xqc']) assert.equal(ownerMatch({ uploader_id: other }, {}, 'cutscenecity')[0], false, other);
  assert.equal(ownerMatch({ uploader_id: 'cutscenecity' }, { CUTSCENECITY_OWNER_TWITCH_LOGIN: 'other' }, 'cutscenecity')[0], false, 'env overrides policy');
  assert.equal(ownerMatch({ channel_id: '42' }, { CUTSCENECITY_OWNER_TWITCH_ID: '42' })[0], true);
  assert.equal(ownerMatch({ uploader_id: 'cutscenecity' }, { CUTSCENECITY_OWNER_TWITCH_ID: '42' })[0], false, 'id-only owner needs channel_id');
});

test('script similarity matches Python script_checks', () => {
  const hist = [{ clip_key: 'a', script: 'Okay so here we go again. The cops are everywhere tonight and I panic on the bridge. Smash like if you laughed.' },
    { clip_key: 'b', script: 'Café chase, naïve plan! Ünïcode wörds stay wörds. Ending line here.' }];
  const cases = ['Okay so here we go again. Totally new middle about a boat and a pier at sunset. Different closing words entirely.',
    'Brand new opener about the harbour. The cops are everywhere tonight and I panic on the bridge. Fresh closing line for this one.',
    'Café chase, naïve plan! Ünïcode wörds stay wörds. Another ending.',
    'Nothing in common with anything at all here today friends.'];
  const py = JSON.parse(execFileSync(PY, ['-c', `import json,sys
sys.path.insert(0, sys.argv[1])
import script_checks as s
h = json.loads(sys.argv[2]); out = []
for t in json.loads(sys.argv[3]):
    st, _, w = s.check_script(t, h, "own")
    out.append([st, round(w, 6)])
print(json.dumps(out))`, path.join(__dirname, '..', 'tools', 'twitch-shorts'), JSON.stringify(hist), JSON.stringify(cases)], { encoding: 'utf8' }));
  const js = cases.map(c => { const [st, , w] = checkScript(c, hist, 'own'); return [st, Math.round(w * 1e6) / 1e6]; });
  assert.deepEqual(js, py);
  assert.equal(js[0][0], 'FAIL', 'reused opener');
});

test('Node re-checks gates independently: spoilers, TTS, script, live reaction, commentary < 60%, rotation', async t => {
  const ctx = await setup(t, { pkgArgs: ['--tts', '--synthetic'] });
  const clip = JSON.parse(fs.readFileSync(path.join(ctx.pkgs[0].dir, 'clip.json'), 'utf8'));
  const { policy, spoilerTerms } = loadPolicy(path.join(__dirname, '..', 'tools', 'twitch-shorts'));
  const history = ctx.service.readHistory();
  assert.equal(history.length, 1);
  const opts = { env: ctx.env, policy, spoilerTerms, history };
  assert.deepEqual(checkClipGates(clip, opts), [], 'own clip is excluded from its own history');
  const spoiler = { ...clip, metadata: { ...clip.metadata, title: 'The GTA 6 ending explained' } };
  assert.match(checkClipGates(spoiler, opts).join(' '), /spoiler keywords in metadata: ending/);
  const noFlag = { ...clip, metadata: { ...clip.metadata, containsSyntheticMedia: false } };
  assert.match(checkClipGates(noFlag, opts).join(' '), /containsSyntheticMedia must be true/);
  const noScript = { ...clip };
  delete noScript.commentary_script;
  assert.match(checkClipGates(noScript, opts).join(' '), /approved script is required/);
  const edited = { ...clip, commentary_script: { ...clip.commentary_script, text: clip.commentary_script.text + ' extra' } };
  assert.match(checkClipGates(edited, opts).join(' '), /script changed after approval/);
  const reused = { ...clip, start: 300, end: 320 };
  assert.match(checkClipGates(reused, opts).join(' '), /script reuse/);
  const thin = { ...clip, commentary: { ...clip.commentary, speech_seconds_combined: 11 } };
  assert.match(checkClipGates(thin, opts).join(' '), /60%/);
  const liveOnly = checkClipGates(clip, { ...opts, env: { ...ctx.env, CUTSCENECITY_TTS_COUNTS_AS_COMMENTARY: 'false' } });
  assert.equal(liveOnly.filter(x => /60%/.test(x)).length, 1, 'live 8s/20s fails when TTS does not count');
  for (const render of [{ ...clip.render, audio_mode: 'mute' }, { ...clip.render, mic_gain: 0.3 }, { ...clip.render, mic_source: null }]) {
    assert.match(checkClipGates({ ...clip, render }, opts).join(' '), /live reaction/);
  }
  assert.match(checkClipGates(clip, { ...opts, previous: { voice_preset: 'charon-relaxed' } }).join(' '), /repeats the previous upload/);
  const burned = { ...clip, render: { ...clip.render, captions: 'BURNED (test)', caption_style: 'bold-white' } };
  assert.match(checkClipGates(burned, { ...opts, previous: { caption_style: 'bold-white' } }).join(' '), /caption style bold-white repeats/);
  const words = { ...clip, render: { ...clip.render, captions: 'BURNED_WORD_BY_WORD_NEEDS_HUMAN_CHECK', caption_style: 'word-pop-yellow', edit_style: 'hype' } };
  assert.doesNotMatch(checkClipGates(words, opts).join(' '), /caption style/);
  assert.match(checkClipGates(words, { ...opts, previous: { caption_style: 'word-pop-yellow' } }).join(' '), /caption style word-pop-yellow repeats/);
  assert.match(checkClipGates({ ...words, render: { ...words.render, caption_style: 'word-pop-rainbow' } }, opts).join(' '), /not in policy/);
  assert.match(checkClipGates({ ...clip, commentary: { ...clip.commentary, voice_preset: 'robot' } }, opts).join(' '), /not in policy/);
  const noCredit = { ...clip, metadata: { ...clip.metadata, description: 'no credit here' } };
  assert.match(checkClipGates(noCredit, opts).join(' '), /attribution/);
  assert.throws(() => makePackage(path.join(ctx.work, 'spoil'), ['--title', 'The GTA 6 ending explained'], ctx.env.CUTSCENECITY_STATE_DIR), /Command failed/);
  const scriptFile = path.join(ctx.work, 'reuse.txt');
  fs.writeFileSync(scriptFile, clip.commentary_script.text);
  assert.throws(() => makePackage(path.join(ctx.work, 'reuse'), ['--tts', '--synthetic', '--start', '300', '--script-file', scriptFile], ctx.env.CUTSCENECITY_STATE_DIR), /script rejected/);
});

test('rotation: the next upload may not reuse the previous voice preset', async t => {
  const ctx = await setup(t, {
    env: { CUTSCENECITY_DAILY_CAP: '5' },
    packages: 3,
    pkgArgs: i => ['--tts', '--synthetic', '--start', String(i * 100), '--script-variant', String(i), '--voice', i === 2 ? 'puck-hyped' : 'charon-relaxed']
  });
  const [a, b, c] = ctx.pkgs.map(p => p.body);
  const ia = await ctx.call('POST', '/api/gta6/external-shorts', a);
  assert.equal(ia.status, 201, JSON.stringify(ia.json));
  assert.equal((await ctx.call('POST', `/api/gta6/external-shorts/${ia.json.result.id}/approve-upload`, { reviewer: 'Shebin', confirm: a.packageSha256.slice(0, 12) })).status, 200);
  ctx.service.now = () => new Date(Date.now() + 86400000); // next IST day
  const rb = await ctx.call('POST', '/api/gta6/external-shorts', b);
  assert.equal(rb.status, 422);
  assert.match(rb.json.problems.join(' '), /voice preset charon-relaxed repeats the previous upload/);
  const rc = await ctx.call('POST', '/api/gta6/external-shorts', c);
  assert.equal(rc.status, 201, JSON.stringify(rc.json));
});

test('daily cap is clamped to 1 and 0/invalid blocks (fail closed)', async t => {
  assert.equal(HARD_DAILY_CAP, 1); // phase 2.7: back from 2 to 1
  for (const [env, pol, want] of [['5', 1, 1], ['2', 1, 1], [undefined, 2, 1], [undefined, 10, 1], ['', 3, 1], ['1', 2, 1], ['0', 1, 0], ['-2', 1, 0], ['abc', 1, 0], ['1.5', 1, 0], [undefined, 0, 0], [undefined, true, 0], [undefined, undefined, 1]]) {
    assert.equal(effectiveDailyCap(env, pol), want, `${env}/${pol}`);
  }
  let ctx = await setup(t, { env: { CUTSCENECITY_DAILY_CAP: '5' }, packages: 2, pkgArgs: i => ['--start', String(i * 100)] });
  const [a, b] = ctx.pkgs.map(p => p.body);
  const ia = await ctx.call('POST', '/api/gta6/external-shorts', a);
  const ib = await ctx.call('POST', '/api/gta6/external-shorts', b);
  assert.equal((await ctx.call('POST', `/api/gta6/external-shorts/${ia.json.result.id}/approve-upload`, { reviewer: 'Shebin', confirm: a.packageSha256.slice(0, 12) })).status, 200);
  const capped = await ctx.call('POST', `/api/gta6/external-shorts/${ib.json.result.id}/approve-upload`, { reviewer: 'Shebin', confirm: b.packageSha256.slice(0, 12) });
  assert.equal(capped.status, 422);
  assert.match(capped.json.problems.join(' '), /daily cap reached: 1\/1 upload attempts today \(IST\)/);
  assert.equal(ctx.youtube.calls.length, 1);
  ctx.service.now = () => new Date(Date.now() + 86400000); // next IST day: the 2nd one is allowed
  assert.equal((await ctx.call('POST', `/api/gta6/external-shorts/${ib.json.result.id}/approve-upload`, { reviewer: 'Shebin', confirm: b.packageSha256.slice(0, 12) })).status, 200);
  ctx = await setup(t, { env: { CUTSCENECITY_DAILY_CAP: '0' } });
  const r = await ctx.call('POST', '/api/gta6/external-shorts', ctx.pkgs[0].body);
  assert.equal(r.status, 422);
  assert.match(r.json.problems.join(' '), /uploads are disabled/);
});

test('overlays_third_parties_cleared: required, bound to the scanned file, note when flagged', async t => {
  assert.ok(REQUIRED_HUMAN_CHECKS.includes('overlays_third_parties_cleared'));
  const ctx = await setup(t);
  assert.throws(() => makePackage(path.join(ctx.work, 'flag'), ['--overlay-flagged', 'yes', '--overlay-note', 'ok'], ctx.env.CUTSCENECITY_STATE_DIR), /note of at least 5 words/);
  const flagged = makePackage(path.join(ctx.work, 'flag2'), ['--start', '200', '--overlay-flagged', 'yes', '--overlay-note', 'chat column blurred, alerts off, no guests'], ctx.env.CUTSCENECITY_STATE_DIR);
  assert.equal((await ctx.call('POST', '/api/gta6/external-shorts', flagged.body)).status, 201);
  const { body, dir } = ctx.pkgs[0];
  const clipPath = path.join(dir, 'clip.json');
  const clip = JSON.parse(fs.readFileSync(clipPath, 'utf8'));
  fs.writeFileSync(clipPath, JSON.stringify({ ...clip, overlay_scan: { ...clip.overlay_scan, file_sha256: '0'.repeat(64) } }));
  const r = await ctx.call('POST', '/api/gta6/external-shorts', body);
  assert.equal(r.status, 422);
  assert.match(r.json.problems.join(' '), /overlay scan was not run on this exact file/);
});

test('paid promotion: explicit true for present, missing blocks, tamper blocks', async t => {
  const ctx = await setup(t, { pkgArgs: ['--paid', 'present'] });
  const { body, dir } = ctx.pkgs[0];
  assert.equal(body.paidProductPlacement, true);
  assert.equal((await ctx.call('POST', '/api/gta6/external-shorts', { ...body, paidProductPlacement: false })).status, 422);
  const noField = { ...body };
  delete noField.paidProductPlacement;
  const nf = await ctx.call('POST', '/api/gta6/external-shorts', noField);
  assert.equal(nf.status, 400);
  assert.match(nf.json.problems.join(' '), /paidProductPlacement must be true or false/);
  const clipPath = path.join(dir, 'clip.json');
  const clip = JSON.parse(fs.readFileSync(clipPath, 'utf8'));
  fs.writeFileSync(clipPath, JSON.stringify({ ...clip, paid_promotion: { ...clip.paid_promotion, value: 'none' } }));
  const tampered = await ctx.call('POST', '/api/gta6/external-shorts', body);
  assert.match(tampered.json.problems.join(' '), /paid_promotion/);
  fs.writeFileSync(clipPath, JSON.stringify(clip));
  const ing = await ctx.call('POST', '/api/gta6/external-shorts', body);
  assert.equal(ing.status, 201, JSON.stringify(ing.json));
  await ctx.call('POST', `/api/gta6/external-shorts/${ing.json.result.id}/approve-upload`, { reviewer: 'Shebin', confirm: body.packageSha256.slice(0, 12) });
  assert.deepEqual(ctx.youtube.calls[0].requestBody.paidProductPlacementDetails, { hasPaidProductPlacement: true });
  assert.throws(() => makePackage(path.join(ctx.work, 'nopaid'), ['--paid', 'skip', '--start', '300'], ctx.env.CUTSCENECITY_STATE_DIR), /paid_promotion/);
});

test('mixed-track path (opt-in): creator-owned + signed confirmation passes; unsigned, lowered or foreign is blocked', async t => {
  process.env.CUTSCENECITY_ALLOW_MIXED_TRACK = 'true'; // phase 2.7: off by default; the Python fixture inherits this
  t.after(() => { delete process.env.CUTSCENECITY_ALLOW_MIXED_TRACK; });
  const ctx = await setup(t, { pkgArgs: ['--mixed'], env: { CUTSCENECITY_ALLOW_MIXED_TRACK: 'true' } });
  const { body, dir } = ctx.pkgs[0];
  const clip = JSON.parse(fs.readFileSync(path.join(dir, 'clip.json'), 'utf8'));
  assert.ok(isMixedTrack(clip));
  assert.equal(clip.commentary.commentary_source, 'mixed_track_signed');
  const ing = await ctx.call('POST', '/api/gta6/external-shorts', body);
  assert.equal(ing.status, 201, JSON.stringify(ing.json));
  const { policy, spoilerTerms } = loadPolicy(path.join(__dirname, '..', 'tools', 'twitch-shorts'));
  const opts = { env: ctx.env, policy, spoilerTerms, history: [] };
  assert.deepEqual(checkClipGates(clip, opts), []);
  const unsigned = { ...clip, commentary: { ...clip.commentary, commentary_source: null } };
  assert.match(checkClipGates(unsigned, opts).join(' '), /mixed_track_commentary_confirmed/);
  const lowered = { ...clip, render: { ...clip.render, music_volume: 0.5 } };
  assert.match(checkClipGates(lowered, opts).join(' '), /full level/);
  const foreign = { ...clip, provenance: { ...clip.provenance, source_owner: { ...clip.provenance.source_owner, uploader_id: 'otherstreamer' } } };
  const fp = checkClipGates(foreign, opts).join(' ');
  assert.match(fp, /not the owner/);
  assert.match(fp, /only creator-owned VODs/);
  // the human sign-off needs 5+ words and must exist in the signed log
  assert.throws(() => makePackage(path.join(ctx.work, 'short'), ['--mixed', '--start', '200', '--mixed-note', 'audible'], ctx.env.CUTSCENECITY_STATE_DIR), /Command failed/);
  const lines = fs.readFileSync(path.join(dir, 'review_log.jsonl'), 'utf8').trim().split('\n');
  assert.ok(lines.some(l => JSON.parse(l).check === 'mixed_track_commentary_confirmed'));
});

test('mic-stem packages do not need the mixed-track sign-off (stricter measured path preferred)', async t => {
  const ctx = await setup(t);
  const clip = JSON.parse(fs.readFileSync(path.join(ctx.pkgs[0].dir, 'clip.json'), 'utf8'));
  assert.equal(isMixedTrack(clip), false);
  assert.equal((await ctx.call('POST', '/api/gta6/external-shorts', ctx.pkgs[0].body)).status, 201);
  const { policy, spoilerTerms } = loadPolicy(path.join(__dirname, '..', 'tools', 'twitch-shorts'));
  const thin = { ...clip, commentary: { ...clip.commentary, speech_seconds_combined: 5, speech_seconds_live: 5 } };
  assert.match(checkClipGates(thin, { env: ctx.env, policy, spoilerTerms, history: [] }).join(' '), /60%/);
});

test('upscaled packages (default 2160x3840) are accepted; other sizes are rejected', async t => {
  const ctx = await setup(t, { pkgArgs: ['--upscale', '2160'] });
  const { body, dir } = ctx.pkgs[0];
  const clip = JSON.parse(fs.readFileSync(path.join(dir, 'clip.json'), 'utf8'));
  assert.equal(clip.render.output_resolution, '2160x3840');
  assert.equal((await ctx.call('POST', '/api/gta6/external-shorts', body)).status, 201);
  const { policy, spoilerTerms } = loadPolicy(path.join(__dirname, '..', 'tools', 'twitch-shorts'));
  const opts = { env: ctx.env, policy, spoilerTerms, history: [] };
  for (const [up, res] of [['1440', '1440x2560'], ['off', '1080x1920'], ['skipped (source 2160x3840 already >= 2160x3840)', '2160x3840']]) {
    assert.deepEqual(checkClipGates({ ...clip, render: { ...clip.render, upscale: up, output_resolution: res } }, opts), [], up);
  }
  assert.match(checkClipGates({ ...clip, render: { ...clip.render, upscale: '4320', output_resolution: '4320x7680' } }, opts).join(' '), /not allowed/);
});

test('overlapping range of the same VOD is a duplicate at ingest', async t => {
  const ctx = await setup(t, { packages: 2, pkgArgs: i => ['--start', String(i * 10)] });
  assert.equal((await ctx.call('POST', '/api/gta6/external-shorts', ctx.pkgs[0].body)).status, 201);
  const r = await ctx.call('POST', '/api/gta6/external-shorts', ctx.pkgs[1].body);
  assert.equal(r.status, 422);
  assert.match(r.json.problems.join(' '), /overlaps ingested item/);
});

test('daily cap (default 1 from policy) and overlap duplicate across packages', async t => {
  const ctx = await setup(t, { packages: 2, pkgArgs: i => ['--start', String(i * 100)] });
  const [a, b] = ctx.pkgs.map(p => p.body);
  const ia = await ctx.call('POST', '/api/gta6/external-shorts', a);
  const ib = await ctx.call('POST', '/api/gta6/external-shorts', b);
  assert.equal(ia.status, 201);
  assert.equal(ib.status, 201);
  assert.equal((await ctx.call('POST', `/api/gta6/external-shorts/${ia.json.result.id}/approve-upload`, { reviewer: 'Shebin', confirm: a.packageSha256.slice(0, 12) })).status, 200);
  const capped = await ctx.call('POST', `/api/gta6/external-shorts/${ib.json.result.id}/approve-upload`, { reviewer: 'Shebin', confirm: b.packageSha256.slice(0, 12) });
  assert.equal(capped.status, 422);
  assert.match(capped.json.problems.join(' '), /daily cap reached: 1\/1/);
  assert.equal(ctx.youtube.calls.length, 1);
});

test('ambiguous upload error marks unknown_reconcile; public response is flagged', async t => {
  let ctx = await setup(t, { youtube: fakeYouTube({ fail: true }) });
  let body = ctx.pkgs[0].body;
  let ing = await ctx.call('POST', '/api/gta6/external-shorts', body);
  let r = await ctx.call('POST', `/api/gta6/external-shorts/${ing.json.result.id}/approve-upload`, { reviewer: 'Shebin', confirm: body.packageSha256.slice(0, 12) });
  assert.equal(r.status, 502);
  assert.equal(ctx.service.list()[0].status, 'unknown_reconcile');
  ctx = await setup(t, { youtube: fakeYouTube({ privacy: 'public' }) });
  body = ctx.pkgs[0].body;
  ing = await ctx.call('POST', '/api/gta6/external-shorts', body);
  r = await ctx.call('POST', `/api/gta6/external-shorts/${ing.json.result.id}/approve-upload`, { reviewer: 'Shebin', confirm: body.packageSha256.slice(0, 12) });
  assert.equal(r.status, 502);
  assert.equal(ctx.service.list()[0].status, 'uploaded_privacy_mismatch');
});

test('no YouTube client configured: approval refuses before any audit ATTEMPT', async t => {
  const ctx = await setup(t, { youtube: null });
  const body = ctx.pkgs[0].body;
  const ing = await ctx.call('POST', '/api/gta6/external-shorts', body);
  const r = await ctx.call('POST', `/api/gta6/external-shorts/${ing.json.result.id}/approve-upload`, { reviewer: 'Shebin', confirm: body.packageSha256.slice(0, 12) });
  assert.equal(r.status, 503);
  assert.ok(!fs.existsSync(path.join(ctx.env.CUTSCENECITY_STATE_DIR, 'upload-audit.jsonl')));
});

// ---------- Phase 2.7 compliance fixes (edit stage) ----------
const TOOLS = path.join(__dirname, '..', 'tools', 'twitch-shorts');
const CAPTIONS_NOTE = 'read every caption word against the video, gameplay talk only';

test('2.7 fix 1+7: default per-clip choice is clean (hype opt-in); an edit without a signed per-clip human choice is refused', async t => {
  const { policy } = loadPolicy(TOOLS);
  assert.equal(policy.edit_policy.default_edit_style, 'clean');
  assert.deepEqual(STYLE_EFFECTS.clean, ['captions']);
  const ctx = await setup(t, { pkgArgs: ['--edit', 'hype', '--effects', 'punch_in,end_fade'] });
  const { body, dir } = ctx.pkgs[0];
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'));
  assert.deepEqual(pkg.style.edit_effects, ['punch_in', 'end_fade']);
  const log = fs.readFileSync(path.join(dir, 'review_log.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  const choice = log.find(e => e.action === 'edit_choice');
  assert.deepEqual([choice.edit_style, choice.effects, choice.by], ['hype', ['punch_in', 'end_fade'], 'Tester']);
  assert.equal((await ctx.call('POST', '/api/gta6/external-shorts', body)).status, 201);
  // Python refuses to export an edit applied without a human choice
  assert.throws(() => makePackage(path.join(ctx.work, 'nochoice'), ['--edit', 'hype', '--no-edit-choice'], ctx.env.CUTSCENECITY_STATE_DIR), /Command failed/);
  // Node independently: clip.json edited to another effect list than the signed choice
  const clipPath = path.join(dir, 'clip.json');
  const clip = JSON.parse(fs.readFileSync(clipPath, 'utf8'));
  const swapped = { ...clip, edit_choice: { ...clip.edit_choice, effects: ['punch_in', 'shake'] }, render: { ...clip.render, edit_effects: ['punch_in', 'shake'] } };
  fs.writeFileSync(clipPath, JSON.stringify(swapped));
  ctx.service.save({ items: [] });
  const r = await ctx.call('POST', '/api/gta6/external-shorts', body);
  assert.equal(r.status, 422);
  assert.match(r.json.problems.join(' '), /manifest choice differs from the signed choice/);
  assert.match(renderEditProblems({ ...clip, edit_choice: undefined }).join(' '), /without a recorded human edit choice/);
  assert.match(renderEditProblems({ ...clip, render: { ...clip.render, edit_style: 'clean', edit_effects: ['punch_in'] }, edit_choice: { ...clip.edit_choice, edit_style: 'clean', effects: ['punch_in'] } }).join(' '), /not allowed for edit style clean/);
});

test('2.7 fix 2+3: burned captions need a mic stem and a signed captions_reviewed bound to words.json', async t => {
  const ctx = await setup(t, { pkgArgs: ['--edit', 'clean', '--captions', 'flanking left watch out bro', '--caption-note', CAPTIONS_NOTE] });
  const { body, dir } = ctx.pkgs[0];
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'));
  assert.equal(pkg.captions.file, 'captions.words.json');
  assert.ok(fs.existsSync(path.join(dir, 'captions.words.json')));
  const log = fs.readFileSync(path.join(dir, 'review_log.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  const so = log.find(e => e.action === 'signoff' && e.check === 'captions_reviewed');
  assert.equal(so.words_json_sha256, pkg.captions.words_json_sha256);
  assert.equal((await ctx.call('POST', '/api/gta6/external-shorts', body)).status, 201);
  // edited words.json after export -> blocked
  ctx.service.save({ items: [] });
  const wf = path.join(dir, 'captions.words.json');
  const orig = fs.readFileSync(wf, 'utf8');
  fs.writeFileSync(wf, orig.replace('flanking', 'Lucia'));
  let r = await ctx.call('POST', '/api/gta6/external-shorts', body);
  assert.equal(r.status, 422);
  assert.match(r.json.problems.join(' '), /words\.json changed after render\/export/);
  assert.match(r.json.problems.join(' '), /no signed caption review for this exact words\.json/);
  fs.rmSync(wf);
  r = await ctx.call('POST', '/api/gta6/external-shorts', body);
  assert.match(r.json.problems.join(' '), /words\.json missing from the package/);
  fs.writeFileSync(wf, orig);
  // mixed-track (no mic stem) captions are refused by the Node gate
  const clip = JSON.parse(fs.readFileSync(path.join(dir, 'clip.json'), 'utf8'));
  const mixed = { ...clip, commentary: { ...clip.commentary, mic_source: null }, render: { ...clip.render, mic_source: null, caption_source: 'mixed_track' } };
  assert.match(renderEditProblems(mixed).join(' '), /separate mic stem/);
  // Python refuses to export captions without the human caption review
  assert.throws(() => makePackage(path.join(ctx.work, 'noreview'), ['--edit', 'clean', '--captions', 'nice shot', '--skip-caption-review'], ctx.env.CUTSCENECITY_STATE_DIR), /Command failed/);
});

test('2.7 fix 4+5: profanity masked + first-10s flag; story names/plot keywords flagged; placeholders marked incomplete', async t => {
  const { policy, spoilerTerms } = loadPolicy(TOOLS);
  assert.equal(policy.caption_policy.audio_bleep, false);
  assert.ok(policy.caption_policy.story_names.includes('Lucia') && policy.caption_policy.story_names.includes('Jason'));
  assert.ok(policy.caption_policy.story_names.some(n => n.startsWith('PLACEHOLDER')));
  const words = [
    { word: 'f******', start: 2.0, end: 2.3, masked: true }, { word: 'Lucia', start: 4.0, end: 4.3 },
    { word: 'final', start: 11, end: 11.2 }, { word: 'mission', start: 11.3, end: 11.6 }, { word: 's***', start: 15, end: 15.2, masked: true }
  ];
  const f = captionFlags(words, policy, spoilerTerms);
  assert.deepEqual(f.profanityFirst10s, [2.0]);
  assert.equal(f.profanityMasked, 2);
  assert.deepEqual(f.keywordHits.map(h => h.term).sort(), ['Lucia', 'final mission']);
  assert.equal(f.keywordListIncomplete, true);
  assert.deepEqual(captionFlags([{ word: 'Fucking!', start: 1, end: 2 }], policy, spoilerTerms).unmaskedProfanity, [1]);
  assert.deepEqual(captionFlags([{ word: 'PLACEHOLDER_STORY_NAME_1', start: 1, end: 2 }], policy, spoilerTerms).keywordHits, []);
  // real package: Python masked the word, flags need a 5+ word note (short note -> Python refuses)
  const ctx = await setup(t, { pkgArgs: ['--edit', 'clean', '--captions', 'what the fucking hell', '--caption-start', '3', '--caption-note', CAPTIONS_NOTE] });
  const w = JSON.parse(fs.readFileSync(path.join(ctx.pkgs[0].dir, 'captions.words.json'), 'utf8'));
  assert.deepEqual(w.map(x => x.word), ['what', 'the', 'f******', 'hell']);
  assert.equal((await ctx.call('POST', '/api/gta6/external-shorts', ctx.pkgs[0].body)).status, 201);
  assert.throws(() => makePackage(path.join(ctx.work, 'shortnote'), ['--edit', 'clean', '--captions', 'oh shit', '--caption-note', 'ok'], ctx.env.CUTSCENECITY_STATE_DIR), /Command failed/);
  assert.throws(() => makePackage(path.join(ctx.work, 'raw'), ['--edit', 'clean', '--captions', 'oh shit', '--raw-profanity'], ctx.env.CUTSCENECITY_STATE_DIR), /Command failed/);
});

test('2.7 fix 8: flash cut at most 1 per clip and intensity <= 0.5 (Node gate + Python export)', async t => {
  assert.equal(FLASH_MAX_PER_CLIP, 1);
  assert.equal(FLASH_MAX_INTENSITY, 0.5);
  const base = { edit_choice: { by: 'S', edit_style: 'hype', effects: ['flash_cut'] }, render: { edit_style: 'hype', edit_effects: ['flash_cut'] } };
  assert.deepEqual(renderEditProblems({ ...base, render: { ...base.render, flash_cuts: [10], flash_intensity: 0.5 } }), []);
  assert.match(renderEditProblems({ ...base, render: { ...base.render, flash_cuts: [10, 20], flash_intensity: 0.5 } }).join(' '), /max 1 per clip/);
  assert.match(renderEditProblems({ ...base, render: { ...base.render, flash_cuts: [10], flash_intensity: 0.85 } }).join(' '), /above 0.5/);
  const ctx = await setup(t, { pkgArgs: ['--edit', 'hype', '--effects', 'flash_cut,end_fade', '--flash-cuts', '1'] });
  assert.equal((await ctx.call('POST', '/api/gta6/external-shorts', ctx.pkgs[0].body)).status, 201);
  assert.throws(() => makePackage(path.join(ctx.work, 'two'), ['--edit', 'hype', '--effects', 'flash_cut', '--flash-cuts', '2'], ctx.env.CUTSCENECITY_STATE_DIR), /Command failed/);
});

test('2.7 defaults: separate mic required (mixed track off unless opted in), game audio stripped unless opted in', async t => {
  const { policy, spoilerTerms } = loadPolicy(TOOLS);
  assert.equal(policy.mixed_track_path_enabled, false);
  assert.equal(policy.game_audio_default, 'stripped');
  assert.equal(policy.daily_upload_cap, 1);
  assert.equal(policy.edit_policy.default_edit_style, 'clean');
  assert.equal(mixedTrackAllowed({}, policy), false);
  assert.equal(mixedTrackAllowed({ CUTSCENECITY_ALLOW_MIXED_TRACK: 'true' }, policy), true);
  const ctx = await setup(t);
  const clip = JSON.parse(fs.readFileSync(path.join(ctx.pkgs[0].dir, 'clip.json'), 'utf8'));
  const opts = { env: ctx.env, policy, spoilerTerms, history: [] };
  const mixed = { ...clip, commentary: { path: null, mic_source: null, tts_used: false, commentary_source: 'mixed_track_signed' },
    render: { audio_mode: 'source', mic_source: null, music_volume: 1.0, captions: 'OFF' } };
  assert.match(checkClipGates(mixed, opts).join(' '), /separate mic track required/);
  assert.doesNotMatch(checkClipGates(mixed, { ...opts, env: { ...ctx.env, CUTSCENECITY_ALLOW_MIXED_TRACK: 'true' } }).join(' '), /separate mic track required/);
  const kept = { ...clip, render: { ...clip.render, audio_mode: 'mix', music_volume: 1.0 } };
  assert.match(checkClipGates(kept, opts).join(' '), /--keep-game-audio opt-in/);
  assert.doesNotMatch(checkClipGates({ ...kept, render: { ...kept.render, keep_game_audio_opt_in: true } }, opts).join(' '), /keep-game-audio/);
  // Python refuses to export a mixed-track package without the opt-in
  assert.throws(() => makePackage(path.join(ctx.work, 'mixedoff'), ['--mixed', '--start', '300'], ctx.env.CUTSCENECITY_STATE_DIR), /Command failed/);
});
