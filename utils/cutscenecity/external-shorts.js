/**
 * CutsceneCity external Shorts ingest: POST /api/gta6/external-shorts
 *
 * Accepts the agent-import.json written by tools/twitch-shorts/review.py export, re-verifies the
 * whole package (hashes, HMAC-signed review log, every compliance gate, daily cap, duplicates) and
 * stores it as a PENDING item. Nothing uploads until a human calls the per-upload approval route
 * with the package confirm code. Uploads are always private, MFK false, no publishAt.
 *
 * Config (env, never committed):
 *   API_KEY                       required; routes refuse to run without it (fail closed)
 *   CUTSCENECITY_PACKAGES_DIR     only packages under this folder are accepted
 *   CUTSCENECITY_REVIEW_KEY       same key the Python review CLI signs with (32+ chars)
 *   CUTSCENECITY_OWNER_TWITCH_LOGIN / CUTSCENECITY_OWNER_TWITCH_ID  owner channel; login falls back to policy owner_twitch_login
 *                                 ("cutscenecity"); if both are empty everything is blocked
 *   CUTSCENECITY_TTS_COUNTS_AS_COMMENTARY  default true (TTS counts toward 60% only with the AI disclosure)
 *   CUTSCENECITY_STATE_DIR        shared upload audit ledger (default ~/.cutscenecity)
 *   CUTSCENECITY_DAILY_CAP        overrides editorial-policy.json daily_upload_cap; clamped to max 2, <=0 or invalid = blocked; counted per IST day
 */
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const TOOLS_DIR = path.join(__dirname, '..', '..', 'tools', 'twitch-shorts');
const SIM = { flagAt: 0.40, rejectAbove: 0.50, nearLine: 0.80, history: 30, shingle: 3 };
const REQUIRED_HUMAN_CHECKS = ['vod_rights_confirmed', 'no_story_cutscene', 'music_risk_cleared', 'overlays_third_parties_cleared'];
const HARD_DAILY_CAP = 2; // raised from 1 in Phase 2.5; day boundary = IST (UTC+05:30)
const ALLOWED_RESOLUTIONS = ['1080x1920', '1440x2560', '2160x3840'];
const PAID_VALUES = ['none', 'present'];
const YT_PART = 'snippet,status,paidProductPlacementDetails';

/** min(env or policy, 2); 0, negative or unparseable = 0 (blocked). Same rule as gatelog.effective_daily_cap. */
function effectiveDailyCap(envValue, policyValue) {
  let raw = envValue !== undefined && envValue !== null && envValue !== '' ? envValue : policyValue;
  if (raw === undefined || raw === null) raw = HARD_DAILY_CAP;
  if (typeof raw === 'boolean' || !/^\s*-?\d+\s*$/.test(String(raw))) return 0;
  return Math.max(0, Math.min(parseInt(String(raw).trim(), 10), HARD_DAILY_CAP));
}
const TWITCH_VOD = /^https:\/\/(?:www\.)?twitch\.tv\/videos\/(\d+)$/;
const HEX64 = /^[0-9a-f]{64}$/;
const IMPORT_KEYS = new Set(['schema', 'type', 'videoPath', 'privacyStatus', 'containsSyntheticMedia', 'selfDeclaredMadeForKids',
  'title', 'description', 'tags', 'captionsPath', 'provenance', 'approvedBy', 'packageSha256', 'fileSha256', 'paidProductPlacement']);

class GateError extends Error {
  constructor(problems, status = 422) {
    super(`Blocked: ${problems.join('; ')}`);
    this.problems = problems;
    this.status = status;
  }
}

/** Byte-identical to Python json.dumps(obj, sort_keys=True, separators=(",", ":")) for str/int/bool/null/list/dict. */
function canonicalJson(value) {
  const enc = v => {
    if (v === null || typeof v === 'boolean') return JSON.stringify(v);
    if (typeof v === 'number') {
      if (!Number.isFinite(v)) throw new Error('non-finite number');
      if (!Number.isInteger(v)) throw new Error('floats are not allowed in signed/hashed records');
      return String(v);
    }
    if (typeof v === 'string') return JSON.stringify(v).replace(/[\u007f-\uffff]/g, c => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
    if (Array.isArray(v)) return `[${v.map(enc).join(',')}]`;
    if (typeof v === 'object') return `{${Object.keys(v).sort().map(k => `${enc(k)}:${enc(v[k])}`).join(',')}}`;
    throw new Error(`unsupported type ${typeof v}`);
  };
  return enc(value);
}

const sha256 = data => crypto.createHash('sha256').update(data).digest('hex');
const sha256Json = obj => sha256(canonicalJson(obj));

function sha256File(file) {
  return new Promise((resolve, reject) => {
    const h = crypto.createHash('sha256');
    fs.createReadStream(file).on('data', d => h.update(d)).on('error', reject).on('end', () => resolve(h.digest('hex')));
  });
}

function signEntry(entry, key) {
  const { sig, ...body } = entry; // eslint-disable-line no-unused-vars
  return crypto.createHmac('sha256', key).update(canonicalJson(body)).digest('hex');
}

function verifyReviewLog(file, key) {
  if (!key || key.length < 32) throw new GateError(['CUTSCENECITY_REVIEW_KEY is not configured on the server'], 503);
  let prev = 'GENESIS';
  const entries = [];
  const lines = fs.readFileSync(file, 'utf8').split('\n').filter(l => l.trim());
  lines.forEach((line, i) => {
    const e = JSON.parse(line);
    const expected = signEntry(e, key);
    const ok = e.seq === i + 1 && e.prev === prev && typeof e.sig === 'string' && e.sig.length === expected.length &&
      crypto.timingSafeEqual(Buffer.from(e.sig), Buffer.from(expected));
    if (!ok) throw new GateError([`review log tampered or signed with another key at line ${i + 1}`]);
    entries.push(e);
    prev = e.sig;
  });
  return entries;
}

const istNow = now => new Date(now.getTime() + 330 * 60000).toISOString().slice(0, 19) + '+05:30';
const hasKeyDeep = (obj, key) => obj && typeof obj === 'object' &&
  (Object.prototype.hasOwnProperty.call(obj, key) || Object.values(obj).some(v => hasKeyDeep(v, key)));

function validateImport(body) {
  const p = [];
  if (!body || typeof body !== 'object' || Array.isArray(body)) return ['body must be a JSON object'];
  if (hasKeyDeep(body, 'publishAt')) p.push('publishAt is never accepted (no scheduled or public uploads from code)');
  const unknown = Object.keys(body).filter(k => !IMPORT_KEYS.has(k));
  if (unknown.length) p.push(`unknown fields: ${unknown.join(', ')}`);
  if (body.schema !== 'cutscenecity.agent-import/1') p.push('schema must be cutscenecity.agent-import/1');
  if (body.type !== 'external_short') p.push('type must be external_short');
  if (body.privacyStatus !== 'private') p.push('privacyStatus must be private');
  if (body.selfDeclaredMadeForKids !== false) p.push('selfDeclaredMadeForKids must be false');
  if (typeof body.containsSyntheticMedia !== 'boolean') p.push('containsSyntheticMedia must be true or false');
  if (typeof body.paidProductPlacement !== 'boolean') p.push('paidProductPlacement must be true or false (reviewer paid_promotion)');
  if (typeof body.videoPath !== 'string' || path.basename(body.videoPath) !== 'video.mp4') p.push('videoPath must point to a package video.mp4');
  if (typeof body.title !== 'string' || !body.title.trim() || body.title.length > 100) p.push('title must be 1-100 characters');
  if (typeof body.description !== 'string' || body.description.length > 5000) p.push('description must be a string up to 5000 characters');
  if (!Array.isArray(body.tags) || body.tags.some(t => typeof t !== 'string')) p.push('tags must be a list of strings');
  if (!HEX64.test(body.packageSha256 || '')) p.push('packageSha256 must be 64 hex characters');
  if (!HEX64.test(body.fileSha256 || '')) p.push('fileSha256 must be 64 hex characters');
  if (typeof body.approvedBy !== 'string' || !body.approvedBy.trim()) p.push('approvedBy is required');
  if (!body.provenance || typeof body.provenance !== 'object') p.push('provenance is required');
  return p;
}

function loadPolicy(toolsDir) {
  const policy = JSON.parse(fs.readFileSync(path.join(toolsDir, 'editorial-policy.json'), 'utf8'));
  let terms = JSON.parse(fs.readFileSync(path.join(toolsDir, 'spoiler-defaults.json'), 'utf8')).terms;
  const extra = policy.spoiler_keywords_file && path.join(toolsDir, policy.spoiler_keywords_file);
  if (extra && fs.existsSync(extra)) {
    terms = terms.concat(fs.readFileSync(extra, 'utf8').split('\n').map(l => l.trim().toLowerCase()).filter(l => l && !l.startsWith('#')));
  }
  return { policy, spoilerTerms: terms };
}

/** Same rule as compliance.owner_match in Python: fail closed unless yt-dlp metadata proves the owner. */
function ownerMatch(meta = {}, env = {}, defaultLogin = '') {
  // env CUTSCENECITY_OWNER_TWITCH_LOGIN wins; else policy owner_twitch_login; both empty -> fail closed
  const login = (String(env.CUTSCENECITY_OWNER_TWITCH_LOGIN || '').trim() || String(defaultLogin || '').trim()).toLowerCase();
  const oid = String(env.CUTSCENECITY_OWNER_TWITCH_ID || '').trim();
  if (!login && !oid) return [false, 'owner not configured: set CUTSCENECITY_OWNER_TWITCH_LOGIN or owner_twitch_login in editorial-policy.json'];
  const low = k => String(meta[k] || '').trim().toLowerCase();
  const cid = String(meta.channel_id || '').trim();
  if (!low('uploader') && !low('uploader_id') && !low('channel') && !cid) return [false, 'VOD channel unknown in yt-dlp metadata'];
  if (login && low('uploader_id') && low('uploader_id') !== login) return [false, `VOD uploader_id '${low('uploader_id')}' is not the owner`];
  if (oid && cid && cid !== oid) return [false, `VOD channel_id '${cid}' is not the owner`];
  if (login && low('channel') && low('channel') !== login) return [false, `VOD channel '${low('channel')}' is not the owner`];
  if (login && (low('uploader_id') === login || low('channel') === login)) return [true, 'owner login matches'];
  if (oid && cid === oid) return [true, 'owner id matches'];
  return [false, 'could not confirm the VOD owner from metadata'];
}

// --- script reuse (parity with tools/twitch-shorts/script_checks.py) ---
const words = t => String(t || '').toLowerCase().replace(/[^\p{L}\p{N}_\s']/gu, ' ').split(/\s+/).filter(Boolean);
function shingles(t, n = SIM.shingle) {
  const w = words(t);
  if (w.length < n) return new Set(w.length ? [w.join(' ')] : []);
  const out = new Set();
  for (let i = 0; i <= w.length - n; i++) out.add(w.slice(i, i + n).join(' '));
  return out;
}
function jaccard(a, b) {
  if (!a.size || !b.size) return 0;
  let inter = 0;
  for (const x of a) if (b.has(x)) inter++;
  return inter / (a.size + b.size - inter);
}
const sentences = t => String(t || '').trim().split(/(?<=[.!?])\s+|\n+/).map(x => x.trim()).filter(Boolean);
const openerCta = t => { const s = sentences(t); return s.length ? [s[0], s[s.length - 1]] : ['', '']; };
function nearLine(a, b) {
  const wa = new Set(words(a)); const wb = new Set(words(b));
  return wa.size > 0 && wb.size > 0 && (words(a).join(' ') === words(b).join(' ') || jaccard(wa, wb) >= SIM.nearLine);
}
function checkScript(text, history, ownKey) {
  const sh = shingles(text); const [op, cta] = openerCta(text);
  let worst = 0; const problems = new Set();
  for (const h of history) {
    if (h.clip_key === ownKey) continue;
    worst = Math.max(worst, jaccard(sh, shingles(h.script)));
    const [hop, hcta] = openerCta(h.script);
    if (nearLine(op, hop)) problems.add(`reused opener: '${op.slice(0, 60)}'`);
    if (nearLine(cta, hcta)) problems.add(`reused CTA/closing line: '${cta.slice(0, 60)}'`);
  }
  if (worst > SIM.rejectAbove) problems.add(`script overlaps a recent script by ${Math.round(worst * 100)}%`);
  if (problems.size) return ['FAIL', [...problems].sort().join('; '), worst];
  if (worst >= SIM.flagAt) return ['WARN', `script overlaps a recent script by ${Math.round(worst * 100)}%`, worst];
  return ['PASS', 'ok', worst];
}
const clipKey = clip => sha256Json({ url: (clip.provenance || {}).source_url || '', start_ms: Math.round(Number(clip.start) * 1000), end_ms: Math.round(Number(clip.end) * 1000) });
const ttsCounts = env => !['false', '0', 'no', 'off'].includes(String(env.CUTSCENECITY_TTS_COUNTS_AS_COMMENTARY ?? 'true').trim().toLowerCase());

/** No separate creator mic stem anywhere: commentary lives only in the single mixed VOD track. */
const isMixedTrack = clip => !((clip.commentary || {}).mic_source) && !((clip.render || {}).mic_source);

/** Independent JS re-check of the gates (does not trust statuses saved by Python). */
function checkClipGates(clip, { env, policy, spoilerTerms, history = [], previous = null }) {
  const p = [];
  const prov = clip.provenance || {};
  const md = clip.metadata || {};
  const vod = TWITCH_VOD.exec(prov.source_url || '');
  if (!vod) p.push('provenance: source_url is not a Twitch VOD URL');
  const owner = prov.source_owner || {};
  if (!vod || String(owner.vod_id || '') !== vod[1]) p.push('creator-owned: yt-dlp metadata missing or for a different VOD');
  const [own, why] = ownerMatch(owner, env, (policy || {}).owner_twitch_login);
  if (!own) p.push(`creator-owned: ${why}`);
  if (md.privacyStatus !== undefined && md.privacyStatus !== 'private') p.push('metadata privacyStatus must be private');
  const desc = String(md.description || '');
  if (!prov.source_channel_name || !desc.toLowerCase().includes(String(prov.source_channel_name).toLowerCase()) || !desc.includes(prov.source_url || '\u0000')) {
    p.push('attribution: description must name the streamer and link the VOD');
  }
  const text = [md.title || '', desc, (md.tags || []).join(' ')].join(' ').toLowerCase();
  const hits = spoilerTerms.filter(t => new RegExp(`\\b${t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`).test(text));
  if (hits.length) p.push(`spoiler keywords in metadata: ${hits.join(', ')}`);
  const c = clip.commentary || {};
  const r = clip.render || {};
  const synthetic = Boolean(c.tts_used || clip.ai_visuals_used);
  if (synthetic && md.containsSyntheticMedia !== true) p.push('TTS/AI used: containsSyntheticMedia must be true');
  if (typeof md.containsSyntheticMedia !== 'boolean') p.push('containsSyntheticMedia must be answered');
  // Upscale (default 2160 in the Python render): only these final resolutions are accepted.
  if (r.upscale !== undefined && !(['off', '1440', '2160'].includes(String(r.upscale)) || String(r.upscale).startsWith('skipped'))) p.push(`render.upscale ${r.upscale} is not allowed (1440, 2160 or off)`);
  if (r.output_resolution !== undefined && !ALLOWED_RESOLUTIONS.includes(r.output_resolution)) p.push(`output resolution ${r.output_resolution} is not an accepted 9:16 size`);
  const mixed = isMixedTrack(clip);
  if (mixed) {
    // Mixed-track path (single Twitch VOD track): creator-owned only, kept at full level, and a signed human confirmation.
    if (!own) p.push('mixed track: only creator-owned VODs may use the mixed-track path');
    if ((r.audio_mode || 'source') !== 'source' || Number(r.music_volume ?? 1) !== 1) p.push('mixed track must be kept unchanged at full level');
    const conf = (clip.compliance || {}).mixed_track_commentary_confirmed || {};
    if (conf.status !== 'PASS' || conf.not_applicable || c.commentary_source !== 'mixed_track_signed') {
      p.push('mixed track: commentary not measurable; needs signed mixed_track_commentary_confirmed (commentary_source=mixed_track_signed)');
    }
  } else {
    if (!['mix', 'mic_stem'].includes(r.audio_mode) || !r.mic_source || r.mic_gain !== 1) p.push('live reaction: creator mic stem must be in the mix at full level (no mute/duck)');
    const runtime = Number(clip.end) - Number(clip.start);
    const min = Math.max(0.6, Number(policy.min_commentary_coverage) || 0.6);
    const speech = Number((ttsCounts(env) ? c.speech_seconds_combined : c.speech_seconds_live) || 0);
    if (!c.mic_source || !(runtime > 0) || speech / runtime < min) p.push('commentary (VAD on mic + TTS bus) must cover at least 60% of runtime');
  }
  const script = clip.commentary_script || {};
  if (c.tts_used && !script.text) p.push('TTS used: a human-edited, approved script is required');
  if (script.text) {
    if (words(script.text).length < 20) p.push('script must be at least 20 words');
    if (script.approved_sha256 !== sha256(script.text)) p.push('script changed after approval');
    const [st, why2] = checkScript(script.text, history.slice(-SIM.history), clipKey(clip));
    if (st === 'FAIL') p.push(`script reuse: ${why2}`);
    if (st === 'WARN' && String(script.similarity_note || '').split(/\s+/).filter(Boolean).length < 5) p.push(`script reuse: ${why2} (needs reviewer note)`);
  }
  const voices = (policy.voice_presets || []).map(v => v.name);
  const styles = [...Object.keys(policy.caption_styles || {}), ...Object.keys(policy.word_caption_styles || {})];
  if (c.tts_used) {
    if (!voices.includes(c.voice_preset)) p.push(`voice preset ${c.voice_preset} not in policy`);
    else if (previous && previous.voice_preset === c.voice_preset) p.push(`voice preset ${c.voice_preset} repeats the previous upload`);
  }
  if (String(r.captions || 'OFF').startsWith('BURNED')) {
    if (!styles.includes(r.caption_style)) p.push(`caption style ${r.caption_style} not in policy`);
    else if (previous && previous.caption_style === r.caption_style) p.push(`caption style ${r.caption_style} repeats the previous upload`);
  }
  if (String(clip.transformation_note || '').split(/\s+/).filter(Boolean).length < 25) p.push('transformation note needs 25+ words');
  if ((clip.technical_qa || {}).status !== 'PASS_TECHNICAL_ONLY') p.push('technical QA has not passed');
  const comp = clip.compliance || {};
  const notPass = Object.entries(comp).filter(([, v]) => v.status !== 'PASS').map(([k]) => k);
  if (!Object.keys(comp).length) p.push('compliance block missing');
  if (notPass.length) p.push(`compliance checks not PASS: ${notPass.join(', ')}`);
  return p;
}

class ExternalShortsService {
  constructor({ env = process.env, toolsDir = TOOLS_DIR, storePath, youtubeProvider, now = () => new Date(), logger = console } = {}) {
    this.env = env;
    this.toolsDir = toolsDir;
    this.storePath = storePath || path.join(__dirname, '..', '..', 'data', 'cutscenecity', 'external-shorts.json');
    this.youtubeProvider = youtubeProvider || (() => null);
    this.now = now;
    this.logger = logger;
  }

  stateDir() {
    const dir = this.env.CUTSCENECITY_STATE_DIR || path.join(os.homedir(), '.cutscenecity');
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }

  ledgerPath() { return path.join(this.stateDir(), 'upload-audit.jsonl'); }

  readLedger() {
    const file = this.ledgerPath();
    return fs.existsSync(file) ? fs.readFileSync(file, 'utf8').split('\n').filter(l => l.trim()).map(l => JSON.parse(l)) : [];
  }

  audit(fields) {
    const entry = { at: istNow(this.now()), source: 'node-agent', ...fields };
    fs.appendFileSync(this.ledgerPath(), JSON.stringify(entry) + '\n');
    return entry;
  }

  readHistory() {
    const file = path.join(this.stateDir(), 'script-history.jsonl');
    const rows = fs.existsSync(file) ? fs.readFileSync(file, 'utf8').split('\n').filter(l => l.trim()).map(l => JSON.parse(l)) : [];
    const latest = new Map();
    rows.forEach(r => { latest.delete(r.clip_key); latest.set(r.clip_key, r); });
    return [...latest.values()].slice(-SIM.history);
  }

  previousUpload(excludePackage) {
    const ledger = this.readLedger();
    for (let i = ledger.length - 1; i >= 0; i--) {
      const e = ledger[i];
      if (['ATTEMPT', 'UPLOADED'].includes(e.status) && e.package_sha256 !== excludePackage) return e;
    }
    return null;
  }

  load() {
    return fs.existsSync(this.storePath) ? JSON.parse(fs.readFileSync(this.storePath, 'utf8')) : { items: [] };
  }

  save(store) {
    fs.mkdirSync(path.dirname(this.storePath), { recursive: true });
    fs.writeFileSync(this.storePath, JSON.stringify(store, null, 2));
  }

  dailyCap(policy) {
    return effectiveDailyCap(this.env.CUTSCENECITY_DAILY_CAP, policy.daily_upload_cap);
  }

  ledgerProblems(pkg, policy, { ignoreItemId } = {}) {
    const p = [];
    const today = istNow(this.now()).slice(0, 10);
    const ledger = this.readLedger();
    const attempts = ledger.filter(e => e.status === 'ATTEMPT' && String(e.at).slice(0, 10) === today).length;
    const cap = this.dailyCap(policy);
    if (cap <= 0) p.push('daily cap is 0 or invalid: uploads are disabled (fail closed)');
    else if (attempts >= cap) p.push(`daily cap reached: ${attempts}/${cap} upload attempts today (IST)`);
    const latest = new Map();
    ledger.forEach(e => latest.set(e.package_sha256, e));
    const sent = [...latest.values()].filter(e => ['ATTEMPT', 'UPLOADED', 'UNKNOWN_RECONCILE'].includes(e.status));
    const src = pkg.source;
    for (const e of sent) {
      if (e.package_sha256 === pkg.package_sha256 || e.file_sha256 === pkg.file_sha256) p.push(`duplicate: already sent (${e.status})`);
      else if (e.vod_id === src.vod_id && e.start_ms < src.end_ms && src.start_ms < e.end_ms) p.push(`duplicate: overlaps VOD ${src.vod_id} range already sent`);
    }
    const pending = this.load().items.filter(i => i.id !== ignoreItemId && !['failed', 'rejected'].includes(i.status));
    for (const i of pending) {
      if (i.packageSha256 === pkg.package_sha256 || i.fileSha256 === pkg.file_sha256) p.push(`duplicate: already ingested as ${i.id} (${i.status})`);
      else if (i.vodId === src.vod_id && i.startMs < src.end_ms && src.start_ms < i.endMs) p.push(`duplicate: overlaps ingested item ${i.id}`);
    }
    return p;
  }

  /** Full verification; returns { pkg, clip, pkgDir } or throws GateError with every problem found. */
  async verify(body, opts = {}) {
    const problems = validateImport(body);
    if (problems.length) throw new GateError(problems, 400);
    const root = this.env.CUTSCENECITY_PACKAGES_DIR;
    if (!root) throw new GateError(['CUTSCENECITY_PACKAGES_DIR is not configured on the server'], 503);
    let rootReal; let videoReal;
    try {
      rootReal = fs.realpathSync(root);
      videoReal = fs.realpathSync(body.videoPath);
    } catch (_e) {
      throw new GateError(['package not found'], 404);
    }
    if (!videoReal.startsWith(rootReal + path.sep)) throw new GateError(['videoPath is outside CUTSCENECITY_PACKAGES_DIR'], 403);
    const pkgDir = path.dirname(videoReal);
    const read = f => JSON.parse(fs.readFileSync(path.join(pkgDir, f), 'utf8'));
    let pkg; let clip;
    try {
      pkg = read('package.json');
      clip = read('clip.json');
    } catch (_e) {
      throw new GateError(['package.json or clip.json missing/invalid'], 422);
    }
    const { policy, spoilerTerms } = loadPolicy(this.toolsDir);
    const p = [];
    if (pkg.schema !== 'cutscenecity.upload-package/4') p.push('package schema must be cutscenecity.upload-package/4');
    const { package_sha256: claimed, ...core } = pkg;
    let recomputed = null;
    try { recomputed = sha256Json(core); } catch (e) { p.push(`package not canonical: ${e.message}`); }
    if (recomputed !== claimed || claimed !== body.packageSha256) p.push('package hash mismatch (edited after export?)');
    const fileSha = await sha256File(videoReal);
    if (fileSha !== pkg.file_sha256 || fileSha !== body.fileSha256) p.push('video.mp4 is not the approved file');
    const up = pkg.upload || {};
    if (up.privacyStatus !== 'private' || up.selfDeclaredMadeForKids !== false) p.push('package upload block must be private + MFK false');
    for (const k of ['title', 'description', 'containsSyntheticMedia', 'paidProductPlacement']) if (up[k] !== body[k]) p.push(`${k} differs between import and package`);
    if (JSON.stringify(up.tags || []) !== JSON.stringify(body.tags)) p.push('tags differ between import and package');
    const md = clip.metadata || {};
    if (md.title !== up.title || md.description !== up.description) p.push('clip metadata differs from package');
    if (md.containsSyntheticMedia !== up.containsSyntheticMedia) p.push('synthetic flag differs between clip and package');
    const entries = verifyReviewLog(path.join(pkgDir, 'review_log.jsonl'), this.env.CUTSCENECITY_REVIEW_KEY);
    const approvals = entries.filter(e => e.action === 'approve' && e.clip === pkg.clip);
    const appr = approvals[approvals.length - 1];
    if (!appr || appr.sig !== (pkg.approval || {}).sig || appr.file_sha256 !== fileSha) p.push('signed approval does not match this file');
    else if (appr.metadata_sha256 !== sha256Json(md)) p.push('metadata changed after signed approval');
    else if (appr.provenance_sha256 !== sha256Json(clip.provenance || {})) p.push('provenance changed after signed approval');
    else if (appr.script_sha256 !== sha256((clip.commentary_script || {}).text || '')) p.push('script changed after signed approval');
    const scriptText = (clip.commentary_script || {}).text;
    if (scriptText && !entries.some(e => e.action === 'script_approve' && e.clip === pkg.clip && e.script_sha256 === sha256(scriptText))) {
      p.push('commentary_script: no signed script approval');
    }
    const paid = (clip.paid_promotion || {}).value;
    if (!PAID_VALUES.includes(paid)) p.push('paid_promotion missing: reviewer must declare none or present');
    else {
      if (up.paidProductPlacement !== (paid === 'present')) p.push('paidProductPlacement in package does not match the signed paid_promotion');
      if (appr && appr.paid_promotion !== paid) p.push('paid_promotion changed after signed approval');
      if (!entries.some(e => e.action === 'paid_promotion' && e.clip === pkg.clip && e.value === paid && e.file_sha256 === fileSha)) {
        p.push('paid_promotion: no signed declaration for this file');
      }
    }
    const scan = clip.overlay_scan || {};
    if (scan.file_sha256 !== fileSha) p.push('overlay scan was not run on this exact file');
    if (scan.flagged !== false) {
      const so = entries.filter(e => e.action === 'signoff' && e.check === 'overlays_third_parties_cleared' && e.clip === pkg.clip && e.file_sha256 === fileSha).pop();
      if (so && String(so.note || '').split(/\s+/).filter(Boolean).length < 5) p.push('overlays_third_parties_cleared: scan flagged or unavailable, sign-off needs a 5+ word note');
    }
    const humanChecks = REQUIRED_HUMAN_CHECKS.concat((policy.extra_human_checks || []).map(c => c.name));
    if (isMixedTrack(clip)) {
      humanChecks.push('mixed_track_commentary_confirmed');
      const so = entries.filter(e => e.action === 'signoff' && e.check === 'mixed_track_commentary_confirmed' && e.clip === pkg.clip && e.file_sha256 === fileSha).pop();
      if (so && String(so.note || '').split(/\s+/).filter(Boolean).length < 5) p.push('mixed_track_commentary_confirmed: signed note must have 5+ words');
    }
    const signed = new Set(entries.filter(e => e.action === 'signoff' && e.clip === pkg.clip && e.file_sha256 === fileSha).map(e => e.check));
    humanChecks.filter(n => !signed.has(n)).forEach(n => p.push(`${n}: no signed human sign-off for this file`));
    p.push(...checkClipGates(clip, { env: this.env, policy, spoilerTerms, history: this.readHistory(), previous: this.previousUpload(pkg.package_sha256) }));
    p.push(...this.ledgerProblems(pkg, policy, opts));
    if (p.length) throw new GateError(p);
    return { pkg, clip, pkgDir, videoPath: videoReal };
  }

  async ingest(body) {
    const { pkg, clip, videoPath } = await this.verify(body);
    const store = this.load();
    const item = {
      id: crypto.randomUUID(), status: 'pending_approval', createdAt: this.now().toISOString(),
      packageSha256: pkg.package_sha256, fileSha256: pkg.file_sha256, confirmHint: 'first 12 characters of packageSha256',
      vodId: pkg.source.vod_id, startMs: pkg.source.start_ms, endMs: pkg.source.end_ms,
      streamer: pkg.source.channel, title: pkg.upload.title, containsSyntheticMedia: pkg.upload.containsSyntheticMedia,
      ttsUsed: Boolean((clip.commentary || {}).tts_used), videoPath, importBody: body,
      privacyStatus: 'private', autoUpload: false
    };
    store.items.push(item);
    this.save(store);
    return item;
  }

  list() { return this.load().items.map(({ importBody, ...rest }) => rest); } // eslint-disable-line no-unused-vars

  /** The per-upload human approval click. The only code path that can call videos.insert. */
  async approveUpload(id, { reviewer, confirm } = {}) {
    const store = this.load();
    const item = store.items.find(i => i.id === id);
    if (!item) throw new GateError(['no such item'], 404);
    if (item.status !== 'pending_approval') throw new GateError([`item is ${item.status}, not pending_approval`], 409);
    if (typeof reviewer !== 'string' || !reviewer.trim()) throw new GateError(['reviewer name is required'], 400);
    if (confirm !== item.packageSha256.slice(0, 12)) throw new GateError(['confirm must equal the first 12 characters of packageSha256'], 400);
    const { pkg, videoPath } = await this.verify(item.importBody, { ignoreItemId: id });
    const youtube = this.youtubeProvider();
    if (!youtube || !youtube.videos || typeof youtube.videos.insert !== 'function') throw new GateError(['YouTube client is not configured'], 503);
    const requestBody = {
      snippet: { title: pkg.upload.title, description: pkg.upload.description, tags: pkg.upload.tags, categoryId: pkg.upload.categoryId || '20' },
      status: { privacyStatus: 'private', selfDeclaredMadeForKids: false, containsSyntheticMedia: pkg.upload.containsSyntheticMedia === true, license: 'youtube', embeddable: true }
    };
    if (item.ttsUsed) requestBody.status.containsSyntheticMedia = true;
    if (typeof pkg.upload.paidProductPlacement !== 'boolean') throw new GateError(['package has no explicit paidProductPlacement'], 422);
    requestBody.paidProductPlacementDetails = { hasPaidProductPlacement: pkg.upload.paidProductPlacement };
    const base = {
      package_sha256: pkg.package_sha256, file_sha256: pkg.file_sha256, clip: pkg.clip, vod_id: pkg.source.vod_id,
      start_ms: pkg.source.start_ms, end_ms: pkg.source.end_ms, approved_by: reviewer.trim(), privacyStatus: 'private', item_id: id,
      voice_preset: (pkg.style || {}).voice_preset || '', caption_style: (pkg.style || {}).caption_style || ''
    };
    this.audit({ status: 'ATTEMPT', ...base });
    item.status = 'uploading';
    item.approvedBy = reviewer.trim();
    item.approvedAt = this.now().toISOString();
    this.save(store);
    let res;
    try {
      res = await youtube.videos.insert({ part: YT_PART, requestBody, media: { body: fs.createReadStream(videoPath) } });
    } catch (error) {
      this.audit({ status: 'UNKNOWN_RECONCILE', error: error.name || 'Error', ...base });
      item.status = 'unknown_reconcile';
      this.save(store);
      throw new GateError(['upload outcome unknown: check YouTube Studio before any retry'], 502);
    }
    const videoId = res && res.data && res.data.id;
    const privacy = res && res.data && res.data.status && res.data.status.privacyStatus;
    this.audit({ status: 'UPLOADED', video_id: videoId, returned_privacy: privacy, ...base });
    item.status = privacy === 'private' ? 'uploaded_private' : 'uploaded_privacy_mismatch';
    item.videoId = videoId;
    this.save(store);
    if (privacy !== 'private') throw new GateError([`YouTube returned privacyStatus=${privacy}; set it to private in Studio now`], 502);
    return { videoId, privacyStatus: privacy, studioUrl: `https://studio.youtube.com/video/${videoId}/edit` };
  }
}

function requireConfiguredApiKey(env = process.env) {
  return (req, res, next) => {
    const key = env.API_KEY;
    if (!key) return res.status(503).json({ success: false, error: 'API_KEY must be set to use external Shorts routes' });
    const given = Buffer.from(String(req.get('x-api-key') || ''));
    const want = Buffer.from(key);
    if (given.length !== want.length || !crypto.timingSafeEqual(given, want)) return res.status(401).json({ success: false, error: 'Unauthorized' });
    return next();
  };
}

function registerExternalShortsRoutes(app, getService, { env = process.env } = {}) {
  const auth = requireConfiguredApiKey(env);
  const send = (res, error) => {
    const status = error instanceof GateError ? error.status : 500;
    res.status(status).json({ success: false, error: error instanceof GateError ? 'Blocked by CutsceneCity gates' : 'Internal error', problems: error.problems || [] });
  };
  app.post('/api/gta6/external-shorts', auth, async (req, res) => {
    try { res.status(201).json({ success: true, result: await getService().ingest(req.body) }); } catch (e) { send(res, e); }
  });
  app.get('/api/gta6/external-shorts', auth, (_req, res) => {
    try { res.json({ success: true, result: getService().list() }); } catch (e) { send(res, e); }
  });
  app.post('/api/gta6/external-shorts/:id/approve-upload', auth, async (req, res) => {
    try { res.json({ success: true, result: await getService().approveUpload(req.params.id, req.body || {}) }); } catch (e) { send(res, e); }
  });
}

module.exports = { ExternalShortsService, isMixedTrack, checkClipGates, loadPolicy, ownerMatch, checkScript, clipKey, effectiveDailyCap, REQUIRED_HUMAN_CHECKS, registerExternalShortsRoutes, canonicalJson, sha256Json, signEntry, verifyReviewLog, validateImport, GateError };
