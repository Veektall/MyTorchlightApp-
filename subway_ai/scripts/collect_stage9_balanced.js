const { chromium } = require('playwright');
const sharp = require('sharp');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const OUT = process.argv[2] || '/tmp/subway-stage9-balanced';
const TARGET_EPISODES = Number(process.env.STAGE9_EPISODES || 8);
const EPISODE_SECONDS = Number(process.env.STAGE9_EPISODE_SECONDS || 42);
const ACTIONS = ['stay', 'left', 'right', 'jump', 'roll'];
const KEYS = { left: 'ArrowLeft', right: 'ArrowRight', jump: 'ArrowUp', roll: 'ArrowDown' };
const QUOTA = { stay: 12, left: 8, right: 8, jump: 12, roll: 8 };
fs.mkdirSync(OUT, { recursive: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function decode(png, w = 64, h = 36) {
  const { data } = await sharp(png).resize(w, h, { fit: 'fill' }).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  const gray = new Float32Array(w * h), rgb = new Float32Array(w * h * 3);
  for (let i = 0, p = 0; i < gray.length; i++, p += 3) {
    const r = data[p] / 255, g = data[p + 1] / 255, b = data[p + 2] / 255;
    rgb[p] = r; rgb[p + 1] = g; rgb[p + 2] = b;
    gray[i] = .299 * r + .587 * g + .114 * b;
  }
  return { gray, rgb, w, h };
}
function meanAbs(a, b) { let s = 0; for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]); return s / a.length; }
function median(xs) { if (!xs.length) return 0; const s = xs.slice().sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; }
function argmin(xs) { let j = 0; for (let i = 1; i < xs.length; i++) if (xs[i] < xs[j]) j = i; return j; }
function isDeath(img) {
  const { rgb, w, h } = img; let green = 0, lower = 0, orange = 0, total = w * h;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const p = (y * w + x) * 3, r = rgb[p], g = rgb[p + 1], b = rgb[p + 2];
    if (y >= h * .5) { lower++; if (g > r * 1.12 && g > b * 1.25 && g > .38) green++; }
    if (r > .68 && g > .20 && g < .78 && b < .28) orange++;
  }
  return green / Math.max(1, lower) > .48 && orange / total > .10;
}
function laneDanger(gray, w, h, prev) {
  const lanes = [[.12, .40], [.34, .66], [.60, .88]], y0 = Math.floor(h * .38), y1 = Math.floor(h * .90);
  return lanes.map(([xa, xb]) => {
    const x0 = Math.floor(w * xa), x1 = Math.floor(w * xb); let edge = 0, temp = 0, m = 0, m2 = 0, c = 0;
    for (let y = y0; y < y1 - 1; y++) for (let x = x0; x < x1 - 1; x++) {
      const i = y * w + x, v = gray[i]; edge += Math.abs(v - gray[i + 1]) + Math.abs(v - gray[i + w]);
      if (prev) temp += Math.abs(v - prev[i]); m += v; m2 += v * v; c++;
    }
    edge /= 2 * c; temp /= c; m /= c; m2 /= c;
    return edge * 1.15 + temp * .75 + Math.sqrt(Math.max(0, m2 - m * m)) * .12;
  });
}

function deficit(counts, action) { return Math.max(0, QUOTA[action] - counts[action]); }
function chooseAction(d, lane, t, counts, lastAt, step) {
  const bestLane = argmin(d), base = Math.min(...d), spread = Math.max(...d) - base;
  const safeDestination = dest => dest >= 0 && dest <= 2 && d[dest] <= d[lane] + Math.max(.010, spread * .55);
  const canLeft = lane > 0 && safeDestination(lane - 1) && t - (lastAt.left || -99) > .70;
  const canRight = lane < 2 && safeDestination(lane + 1) && t - (lastAt.right || -99) > .70;
  const rollSafe = d[lane] <= base + Math.max(.007, spread * .40) && t - (lastAt.roll || -99) > 1.05;

  const candidates = [];
  if (deficit(counts, 'roll') && rollSafe) candidates.push(['roll', deficit(counts, 'roll') * 1.35]);
  if (deficit(counts, 'left') && canLeft) candidates.push(['left', deficit(counts, 'left') * 1.20 + (bestLane < lane ? 2 : 0)]);
  if (deficit(counts, 'right') && canRight) candidates.push(['right', deficit(counts, 'right') * 1.20 + (bestLane > lane ? 2 : 0)]);
  if (deficit(counts, 'jump') && t - (lastAt.jump || -99) > .75) candidates.push(['jump', deficit(counts, 'jump')]);
  if (deficit(counts, 'stay')) candidates.push(['stay', deficit(counts, 'stay') * .70]);
  if (candidates.length) {
    candidates.sort((a, b) => b[1] - a[1] || ACTIONS.indexOf(a[0]) - ACTIONS.indexOf(b[0]));
    return candidates[0][0];
  }

  // After quotas are met, favor survival while continuing to add sparse diverse labels.
  if (bestLane < lane && canLeft && d[lane] - d[bestLane] > .006) return 'left';
  if (bestLane > lane && canRight && d[lane] - d[bestLane] > .006) return 'right';
  if (rollSafe && step % 17 === 5) return 'roll';
  if (t - (lastAt.jump || -99) > 1.10 && step % 5 === 0) return 'jump';
  return 'stay';
}

async function focusCanvas(canvas) {
  await canvas.evaluate(c => { c.tabIndex = 0; c.focus(); });
  const box = await canvas.boundingBox();
  if (box) await canvas.click({ position: { x: box.width / 2, y: box.height / 2 }, force: true }).catch(() => {});
}
async function trustedPress(canvas, key) { await canvas.press(key, { delay: 180 }); }

async function openGame(context, episodeId) {
  const page = await context.newPage();
  page.on('console', m => fs.appendFileSync(path.join(OUT, `${episodeId}-console.log`), `[${m.type()}] ${m.text()}\n`));
  page.on('pageerror', e => fs.appendFileSync(path.join(OUT, `${episodeId}-pageerror.log`), String(e) + '\n'));
  await page.goto('https://poki.com/en/g/subway-surfers', { waitUntil: 'domcontentloaded', timeout: 120000 });
  let game = null, canvas = null, deadline = Date.now() + 100000;
  while (Date.now() < deadline) {
    game = page.frames().filter(f => f.url().includes('.gdn.poki.com')).pop() || null;
    if (game) {
      const c = game.locator('#pixi-canvas');
      if (await c.count().catch(() => 0)) { canvas = c; break; }
    }
    await sleep(650);
  }
  if (!canvas) throw Error('official Pixi canvas not found');
  const webgl = await game.evaluate(() => {
    const c = document.createElement('canvas'), gl = c.getContext('webgl', { stencil: true, failIfMajorPerformanceCaveat: true });
    if (!gl) return { ok: false };
    const e = gl.getExtension('WEBGL_debug_renderer_info');
    return { ok: true, stencil: gl.getParameter(gl.STENCIL_BITS), renderer: e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER) };
  });
  if (!webgl.ok) throw Error('strict WebGL gate failed');
  await focusCanvas(canvas);
  return { page, game, canvas, webgl };
}

async function sampleActivity(canvas, samples = 8, spacingMs = 220) {
  const frames = [], deathFlags = [];
  for (let i = 0; i < samples; i++) {
    const img = await decode(await canvas.screenshot()); frames.push(img.gray); deathFlags.push(isDeath(img));
    if (i + 1 < samples) await sleep(spacingMs);
  }
  const diffs = []; for (let i = 1; i < frames.length; i++) diffs.push(meanAbs(frames[i - 1], frames[i]));
  const med = median(diffs), activePairs = diffs.filter(x => x > .0045).length, strongPairs = diffs.filter(x => x > .010).length;
  return { ok: !deathFlags[deathFlags.length - 1] && (med > .0030 || activePairs >= 3 || strongPairs >= 2), medianMotion: +med.toFixed(6), activePairs, strongPairs, deathAtEnd: deathFlags[deathFlags.length - 1] };
}
async function hardenStartup(canvas) {
  const seqs = [
    ['Space', 'Enter', 'Space', 'ArrowUp'], ['Enter', 'Space', 'ArrowLeft', 'ArrowRight', 'ArrowUp'],
    ['Space', 'ArrowUp', 'Space', 'ArrowDown'], ['ArrowUp', 'ArrowLeft', 'ArrowRight', 'Space']
  ];
  const diagnostics = [];
  for (let round = 0; round < 10; round++) {
    await focusCanvas(canvas); const before = await sampleActivity(canvas, 6, 180); diagnostics.push({ round, phase: 'before', ...before });
    if (before.ok) return { ok: true, diagnostics };
    for (const k of seqs[round % seqs.length]) { await trustedPress(canvas, k); await sleep(300); }
    await sleep(650); const after = await sampleActivity(canvas, 8, 220); diagnostics.push({ round, phase: 'after', ...after });
    if (after.ok) return { ok: true, diagnostics };
  }
  return { ok: false, diagnostics };
}

function recorder(file) {
  const d = process.env.DISPLAY; if (!d) throw Error('DISPLAY missing');
  return spawn('ffmpeg', ['-y', '-loglevel', 'warning', '-f', 'x11grab', '-draw_mouse', '0', '-framerate', '30', '-video_size', '1280x720', '-i', `${d}+0,0`, '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '22', '-pix_fmt', 'yuv420p', file], { stdio: ['pipe', 'inherit', 'inherit'] });
}
async function stopRecorder(p) {
  if (!p || p.exitCode !== null) return; p.stdin.write('q\n');
  await Promise.race([new Promise(r => p.once('exit', r)), sleep(5000)]); if (p.exitCode === null) p.kill('SIGINT');
}

async function collectEpisode(browser, index) {
  const episodeId = `official_stage9_ep${String(index).padStart(2, '0')}`;
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, locale: 'en-US' });
  let g;
  try {
    g = await openGame(context, episodeId);
    const startup = await hardenStartup(g.canvas);
    fs.writeFileSync(path.join(OUT, `${episodeId}-startup.json`), JSON.stringify(startup, null, 2));
    if (!startup.ok) return { episode_id: episodeId, accepted: false, reason: 'startup_failed' };

    const video = path.join(OUT, `${episodeId}.mp4`), actionsPath = path.join(OUT, `${episodeId}-actions.json`);
    const rec = recorder(video); await sleep(700); const t0 = Date.now();
    let prev = null, lane = 1, step = 0, dead = false;
    const counts = Object.fromEntries(ACTIONS.map(a => [a, 0])), lastAt = {}, decisions = [];
    while ((Date.now() - t0) / 1000 < EPISODE_SECONDS) {
      const img = await decode(await g.canvas.screenshot());
      if (isDeath(img)) { dead = true; break; }
      const d = laneDanger(img.gray, img.w, img.h, prev), t = (Date.now() - t0) / 1000;
      const action = chooseAction(d, lane, t, counts, lastAt, step);
      decisions.push({ episode_id: episodeId, step, t_sec: +t.toFixed(4), action, lane_estimate: lane, pixel_danger: d.map(x => +x.toFixed(5)), label_origin: 'exact_browser_input', policy_input: 'pixels_only' });
      counts[action]++; lastAt[action] = t;
      if (action !== 'stay') await trustedPress(g.canvas, KEYS[action]);
      if (action === 'left') lane = Math.max(0, lane - 1); else if (action === 'right') lane = Math.min(2, lane + 1);
      prev = img.gray; step++; await sleep(165);
    }
    const duration = (Date.now() - t0) / 1000; await stopRecorder(rec);
    const payload = { episode_id: episodeId, duration_sec: +duration.toFixed(3), death_detected: dead, action_counts: counts, decisions };
    fs.writeFileSync(actionsPath, JSON.stringify(payload, null, 2));
    const quotasMet = ACTIONS.every(a => counts[a] >= Math.min(QUOTA[a], 4));
    return {
      episode_id: episodeId, accepted: duration >= 24 && quotasMet, duration_sec: +duration.toFixed(3), death_detected: dead,
      video_path: video, actions_path: actionsPath, action_counts: counts, startup_detector: startup.diagnostics[startup.diagnostics.length - 1], webgl: g.webgl,
      provenance: { source: 'official Subway Surfers on Poki', source_url: 'https://poki.com/en/g/subway-surfers', capture: 'self-generated official-game run', reuse_status: 'self_generated_for_research', exact_input_labels: true },
      policy_contract: 'pixel-policy-contract-v1.1', trusted_input: 'Playwright canvas.press(key,{delay:180})'
    };
  } finally {
    await context.close().catch(() => {});
  }
}

(async () => {
  const browser = await chromium.launch({ headless: false, args: ['--autoplay-policy=no-user-gesture-required', '--enable-webgl', '--ignore-gpu-blocklist', '--use-gl=angle', '--use-angle=gl', '--disable-dev-shm-usage', '--no-sandbox', '--window-size=1280,720'] });
  const episodes = [];
  for (let i = 1; i <= TARGET_EPISODES; i++) {
    try { episodes.push(await collectEpisode(browser, i)); }
    catch (e) { episodes.push({ episode_id: `official_stage9_ep${String(i).padStart(2, '0')}`, accepted: false, reason: String(e.stack || e) }); }
  }
  await browser.close();
  const accepted = episodes.filter(e => e.accepted), totals = Object.fromEntries(ACTIONS.map(a => [a, accepted.reduce((s, e) => s + (e.action_counts?.[a] || 0), 0)]));
  const summary = {
    stage: '9-targeted-balanced-exact-collection-v1', policy_contract: 'pixel-policy-contract-v1.1', requested_episodes: TARGET_EPISODES,
    accepted_episodes: accepted.length, target_episode_seconds: EPISODE_SECONDS, per_episode_soft_quota: QUOTA, total_action_counts: totals,
    independence: 'Each episode is collected in a fresh browser context and official-game session.',
    decisions_use_privileged_game_state: false, exact_key_logs_used_only_as_labels: true,
    acceptance_contract: 'Downstream Stage 9 dataset requires >=6 accepted episodes, >=30 examples/class after temporal deduplication, and every action represented in >=4 episodes.'
  };
  fs.writeFileSync(path.join(OUT, 'stage9_episodes.json'), JSON.stringify({ summary, episodes }, null, 2));
  fs.writeFileSync(path.join(OUT, 'stage9_collector_summary.json'), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary, null, 2));
  if (accepted.length < 6) process.exitCode = 11;
})().catch(e => { fs.writeFileSync(path.join(OUT, 'fatal.txt'), String(e.stack || e)); console.error(e); process.exit(1); });
