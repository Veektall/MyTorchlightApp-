const { chromium } = require('playwright');
const sharp = require('sharp');
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2] || '/tmp/subway-stage10-semantic';
const EPISODES = Number(process.env.STAGE10_EPISODES || 8);
const EPISODE_SECONDS = Number(process.env.STAGE10_EPISODE_SECONDS || 42);
const W = 96, H = 54;
const ACTIONS = ['stay', 'left', 'right', 'jump', 'roll'];
const KEYS = { left: 'ArrowLeft', right: 'ArrowRight', jump: 'ArrowUp', roll: 'ArrowDown' };
fs.mkdirSync(path.join(OUT, 'examples'), { recursive: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function decode(png) {
  const { data } = await sharp(png).resize(W, H, { fit: 'fill' }).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  const rgb = Buffer.from(data), gray = new Float32Array(W * H);
  for (let i = 0, p = 0; i < gray.length; i++, p += 3) {
    gray[i] = (.299 * rgb[p] + .587 * rgb[p + 1] + .114 * rgb[p + 2]) / 255;
  }
  return { rgb, gray, w: W, h: H };
}
function meanAbs(a, b) { let s = 0; for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]); return s / a.length; }
function argmin(xs) { let k = 0; for (let i = 1; i < xs.length; i++) if (xs[i] < xs[k]) k = i; return k; }
function median(xs) { const a = xs.slice().sort((x, y) => x - y); return a.length ? a[Math.floor(a.length / 2)] : 0; }
function isDeath(img) {
  const { rgb, w, h } = img; let green = 0, lower = 0, orange = 0, total = w * h;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const p = (y * w + x) * 3, r = rgb[p] / 255, g = rgb[p + 1] / 255, b = rgb[p + 2] / 255;
    if (y >= h * .5) { lower++; if (g > r * 1.12 && g > b * 1.25 && g > .38) green++; }
    if (r > .68 && g > .20 && g < .78 && b < .28) orange++;
  }
  return green / Math.max(1, lower) > .48 && orange / total > .10;
}
function zoneRisk(gray, w, h, xa, xb, ya, yb, prev) {
  const x0 = Math.floor(w * xa), x1 = Math.floor(w * xb), y0 = Math.floor(h * ya), y1 = Math.floor(h * yb);
  let edge = 0, temp = 0, m = 0, m2 = 0, c = 0;
  for (let y = y0; y < y1 - 1; y++) for (let x = x0; x < x1 - 1; x++) {
    const i = y * w + x, v = gray[i];
    edge += Math.abs(v - gray[i + 1]) + Math.abs(v - gray[i + w]);
    if (prev) temp += Math.abs(v - prev[i]);
    m += v; m2 += v * v; c++;
  }
  if (!c) return 0;
  edge /= 2 * c; temp /= c; m /= c; m2 /= c;
  return edge * 1.15 + temp * .75 + Math.sqrt(Math.max(0, m2 - m * m)) * .12;
}
function laneDanger(gray, w, h, prev) {
  const lanes = [[.12,.40],[.34,.66],[.60,.88]];
  return lanes.map(([a,b]) => zoneRisk(gray,w,h,a,b,.38,.90,prev));
}
class RunningRisk {
  constructor() { this.n = 0; this.muU = 0; this.muL = 0; this.vU = .0025; this.vL = .0025; }
  z(u,l) {
    if (this.n < 6) return { zu: 0, zl: 0 };
    return { zu: (u-this.muU)/Math.sqrt(Math.max(this.vU,1e-5)), zl: (l-this.muL)/Math.sqrt(Math.max(this.vL,1e-5)) };
  }
  update(u,l) {
    const a = this.n < 12 ? .18 : .06;
    if (this.n === 0) { this.muU=u; this.muL=l; }
    const du=u-this.muU, dl=l-this.muL;
    this.muU += a*du; this.muL += a*dl;
    this.vU = (1-a)*this.vU + a*du*du; this.vL = (1-a)*this.vL + a*dl*dl; this.n++;
  }
}
function chooseSemanticAction(img, prev, lane, t, lastAt, stats) {
  const lanes = [[.12,.40],[.34,.66],[.60,.88]], d = laneDanger(img.gray,img.w,img.h,prev), best = argmin(d), cur=d[lane];
  const [xa,xb]=lanes[lane];
  const upper=zoneRisk(img.gray,img.w,img.h,xa,xb,.20,.55,prev), lower=zoneRisk(img.gray,img.w,img.h,xa,xb,.55,.92,prev);
  const {zu,zl}=stats.z(upper,lower); stats.update(upper,lower);
  const lateralReady = t-(lastAt.left||-99)>.55 && t-(lastAt.right||-99)>.55;
  let action='stay', reason='no_clear_hazard';
  if (lateralReady && best !== lane && cur-d[best] > .014) {
    action = best < lane ? 'left' : 'right'; reason='adjacent_lane_visibly_safer';
  } else if (t-(lastAt.roll||-99)>.90 && zu>.35 && zu>zl+.18) {
    action='roll'; reason='upper_lane_risk_anomaly';
  } else if (t-(lastAt.jump||-99)>.72 && zl>.35 && zl>zu+.10) {
    action='jump'; reason='lower_lane_risk_anomaly';
  } else if (t-(lastAt.jump||-99)>.80 && cur > median(d)+.022) {
    action='jump'; reason='current_lane_risk_spike';
  }
  return {action, d, upper, lower, zu, zl, reason};
}
async function focusCanvas(canvas) {
  await canvas.evaluate(c => { c.tabIndex = 0; c.focus(); });
  const b=await canvas.boundingBox(); if (b) await canvas.click({position:{x:b.width/2,y:b.height/2},force:true}).catch(()=>{});
}
async function press(canvas,key){ await canvas.press(key,{delay:180}); }
async function openGame(context, episodeId) {
  const page=await context.newPage();
  page.on('console',m=>fs.appendFileSync(path.join(OUT,`${episodeId}-console.log`),`[${m.type()}] ${m.text()}\n`));
  await page.goto('https://poki.com/en/g/subway-surfers',{waitUntil:'domcontentloaded',timeout:120000});
  let game=null,canvas=null,deadline=Date.now()+100000;
  while(Date.now()<deadline){
    game=page.frames().filter(f=>f.url().includes('.gdn.poki.com')).pop()||null;
    if(game){const c=game.locator('#pixi-canvas');if(await c.count().catch(()=>0)){canvas=c;break;}}
    await sleep(650);
  }
  if(!canvas)throw Error('official Pixi canvas not found');
  const webgl=await game.evaluate(()=>{const c=document.createElement('canvas'),gl=c.getContext('webgl',{stencil:true,failIfMajorPerformanceCaveat:true});if(!gl)return{ok:false};const e=gl.getExtension('WEBGL_debug_renderer_info');return{ok:true,stencil:gl.getParameter(gl.STENCIL_BITS),renderer:e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)}});
  if(!webgl.ok)throw Error('strict WebGL gate failed'); await focusCanvas(canvas); return{page,game,canvas,webgl};
}
async function sampleActivity(canvas,n=7,spacing=180){
  const frames=[],deaths=[];for(let i=0;i<n;i++){const x=await decode(await canvas.screenshot());frames.push(x.gray);deaths.push(isDeath(x));if(i+1<n)await sleep(spacing);}
  const ds=[];for(let i=1;i<frames.length;i++)ds.push(meanAbs(frames[i-1],frames[i]));
  const med=median(ds),active=ds.filter(x=>x>.0045).length,strong=ds.filter(x=>x>.010).length;return{ok:!deaths.at(-1)&&(med>.003||active>=3||strong>=2),medianMotion:+med.toFixed(6),activePairs:active,strongPairs:strong,deathAtEnd:deaths.at(-1)};
}
async function hardenStartup(canvas){
  const seqs=[['Space','Enter','Space','ArrowUp'],['Enter','Space','ArrowLeft','ArrowRight','ArrowUp'],['Space','ArrowUp','Space','ArrowDown'],['ArrowUp','ArrowLeft','ArrowRight','Space']];
  const diagnostics=[];for(let r=0;r<10;r++){await focusCanvas(canvas);let s=await sampleActivity(canvas);diagnostics.push({round:r,phase:'before',...s});if(s.ok)return{ok:true,diagnostics};for(const k of seqs[r%seqs.length]){await press(canvas,k);await sleep(280);}await sleep(550);s=await sampleActivity(canvas,8,190);diagnostics.push({round:r,phase:'after',...s});if(s.ok)return{ok:true,diagnostics};}return{ok:false,diagnostics};
}
async function collectEpisode(browser,index){
  const episodeId=`official_stage10_ep${String(index).padStart(2,'0')}`;
  const context=await browser.newContext({viewport:{width:1280,height:720},locale:'en-US'});
  try{
    const g=await openGame(context,episodeId),startup=await hardenStartup(g.canvas);
    fs.writeFileSync(path.join(OUT,`${episodeId}-startup.json`),JSON.stringify(startup,null,2));
    if(!startup.ok)return{episode_id:episodeId,accepted:false,reason:'startup_failed'};
    const ring=[],stats=new RunningRisk(),lastAt={};let prev=null,lane=1,dead=false,step=0,lastDecision=-99;const decisions=[],counts=Object.fromEntries(ACTIONS.map(a=>[a,0]));const t0=Date.now();
    while((Date.now()-t0)/1000<EPISODE_SECONDS){
      const img=await decode(await g.canvas.screenshot());const t=(Date.now()-t0)/1000;if(isDeath(img)){dead=true;break;}
      ring.push(Buffer.from(img.rgb));if(ring.length>8)ring.shift();
      if(ring.length===8 && t-lastDecision>=.52){
        const q=chooseSemanticAction(img,prev,lane,t,lastAt,stats),action=q.action;
        const rel=`examples/${episodeId}-${String(step).padStart(4,'0')}-${action}.rgb8`;fs.writeFileSync(path.join(OUT,rel),Buffer.concat(ring));
        decisions.push({episode_id:episodeId,step,t_sec:+t.toFixed(4),action,example_path:rel,label_origin:'exact_browser_input_from_pixel_teacher',teacher_reason:q.reason,lane_estimate_from_prior_inputs:lane,pixel_danger:q.d.map(x=>+x.toFixed(5)),upper_risk:+q.upper.toFixed(5),lower_risk:+q.lower.toFixed(5),upper_z:+q.zu.toFixed(3),lower_z:+q.zl.toFixed(3),input_shape:[8,54,96,3],input_ends_before_keypress:true,policy_input:'pixels_only'});
        counts[action]++;lastAt[action]=t;lastDecision=t;
        if(action!=='stay')await press(g.canvas,KEYS[action]);
        if(action==='left')lane=Math.max(0,lane-1);else if(action==='right')lane=Math.min(2,lane+1);step++;
      }
      prev=img.gray;await sleep(55);
    }
    const duration=(Date.now()-t0)/1000,payload={episode_id:episodeId,duration_sec:+duration.toFixed(3),death_detected:dead,action_counts:counts,decisions};
    fs.writeFileSync(path.join(OUT,`${episodeId}-actions.json`),JSON.stringify(payload,null,2));
    return{episode_id:episodeId,accepted:duration>=20,duration_sec:+duration.toFixed(3),death_detected:dead,action_counts:counts,decisions:decisions.length,webgl:g.webgl,provenance:{source:'official Subway Surfers on Poki',source_url:'https://poki.com/en/g/subway-surfers',reuse_status:'self_generated_for_research'},policy_contract:'pixel-policy-contract-v1.1'};
  }finally{await context.close().catch(()=>{});}
}
(async()=>{
  const browser=await chromium.launch({headless:false,args:['--autoplay-policy=no-user-gesture-required','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=gl','--disable-dev-shm-usage','--no-sandbox','--window-size=1280,720']});
  const episodes=[];for(let i=1;i<=EPISODES;i++){try{episodes.push(await collectEpisode(browser,i));}catch(e){episodes.push({episode_id:`official_stage10_ep${String(i).padStart(2,'0')}`,accepted:false,reason:String(e.stack||e)});}}
  await browser.close();const accepted=episodes.filter(e=>e.accepted),totals=Object.fromEntries(ACTIONS.map(a=>[a,accepted.reduce((s,e)=>s+(e.action_counts?.[a]||0),0)]));
  const manifest=[];for(const ep of accepted){const p=JSON.parse(fs.readFileSync(path.join(OUT,`${ep.episode_id}-actions.json`)));for(const d of p.decisions)manifest.push({...d,source_id:ep.episode_id,confidence:1.0,eligible_for_training:true,dataset_role:'semantic_pixel_teacher_imitation',policy_contract:'pixel-policy-contract-v1.1',privileged_game_state_used:false});}
  fs.writeFileSync(path.join(OUT,'stage10_examples.jsonl'),manifest.map(x=>JSON.stringify(x)).join('\n')+'\n');
  const coverage=Object.fromEntries(ACTIONS.map(a=>[a,accepted.filter(e=>(e.action_counts?.[a]||0)>0).length]));
  const acceptedData=accepted.length>=6&&ACTIONS.every(a=>totals[a]>=25&&coverage[a]>=4);
  const summary={stage:'10-semantic-pixel-teacher-collection-v1',requested_episodes:EPISODES,accepted_episodes:accepted.length,examples_total:manifest.length,action_counts:totals,episode_coverage_by_action:coverage,acceptance_contract:{minimum_episodes:6,minimum_examples_per_class:25,minimum_episode_coverage_per_class:4},accepted:acceptedData,policy_contract:'pixel-policy-contract-v1.1',input_shape:[8,54,96,3],post_action_pixels:false,decisions_use_privileged_game_state:false,exact_key_logs_used_as_labels:true,teacher:'pixel danger + upper/lower risk anomalies + prior-input-derived lane only'};
  fs.writeFileSync(path.join(OUT,'stage10_collection_summary.json'),JSON.stringify(summary,null,2));fs.writeFileSync(path.join(OUT,'stage10_episodes.json'),JSON.stringify({episodes},null,2));console.log(JSON.stringify(summary,null,2));if(!acceptedData)process.exit(12);
})().catch(e=>{fs.writeFileSync(path.join(OUT,'fatal.txt'),String(e.stack||e));console.error(e);process.exit(1);});
