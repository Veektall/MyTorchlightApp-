const { chromium } = require('playwright');
const sharp = require('sharp');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const OUT = process.argv[2] || '/tmp/subway-stage56-controlled';
fs.mkdirSync(OUT,{recursive:true});
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const KEYS = {left:'ArrowLeft',right:'ArrowRight',jump:'ArrowUp',roll:'ArrowDown'};

async function decode(png,w=64,h=36){
  const {data}=await sharp(png).resize(w,h,{fit:'fill'}).removeAlpha().raw().toBuffer({resolveWithObject:true});
  const gray=new Float32Array(w*h),rgb=new Float32Array(w*h*3);
  for(let i=0,p=0;i<gray.length;i++,p+=3){const r=data[p]/255,g=data[p+1]/255,b=data[p+2]/255;rgb[p]=r;rgb[p+1]=g;rgb[p+2]=b;gray[i]=.299*r+.587*g+.114*b;}
  return {gray,rgb,w,h};
}
function meanAbs(a,b){let s=0;for(let i=0;i<a.length;i++)s+=Math.abs(a[i]-b[i]);return s/a.length;}
function isDeath(img){
  const {rgb,w,h}=img; let green=0,lower=0,orange=0,total=w*h;
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){const p=(y*w+x)*3,r=rgb[p],g=rgb[p+1],b=rgb[p+2];if(y>=h*.5){lower++;if(g>r*1.12&&g>b*1.25&&g>.38)green++;}if(r>.68&&g>.20&&g<.78&&b<.28)orange++;}
  return green/Math.max(1,lower)>.48 && orange/total>.10;
}
function laneDanger(gray,w,h,prev){
  const lanes=[[.12,.40],[.34,.66],[.60,.88]],y0=Math.floor(h*.38),y1=Math.floor(h*.90);
  return lanes.map(([xa,xb])=>{const x0=Math.floor(w*xa),x1=Math.floor(w*xb);let edge=0,temp=0,m=0,m2=0,c=0;
    for(let y=y0;y<y1-1;y++)for(let x=x0;x<x1-1;x++){const i=y*w+x,v=gray[i];edge+=Math.abs(v-gray[i+1])+Math.abs(v-gray[i+w]);if(prev)temp+=Math.abs(v-prev[i]);m+=v;m2+=v*v;c++;}
    edge/=2*c;temp/=c;m/=c;m2/=c;const sd=Math.sqrt(Math.max(0,m2-m*m));return edge*1.15+temp*.75+sd*.12;});
}
function chooseAction(d,lane,step,lastMove){
  const valid=[]; if(lane>0)valid.push({a:'left',lane:lane-1,d:d[lane-1]}); if(lane<2)valid.push({a:'right',lane:lane+1,d:d[lane+1]}); valid.sort((a,b)=>a.d-b.d);
  const here=d[lane],best=valid[0];
  if(here>.108 && d.every(x=>x>.082)) return 'jump';
  if(best && step-lastMove>=2 && here>.063 && best.d+.008<here) return best.a;
  if(here>.098) return 'jump';
  // Safe calibration coverage. These actions are exact labels; the policy is only a data collector.
  if(step%43===21 && here<.078) return 'roll';
  if(step%37===17 && here<.082) return 'jump';
  if(step%29===13 && best && step-lastMove>=3 && best.d<.085) return best.a;
  return 'stay';
}
async function press(canvas,key){ await canvas.press(key,{delay:28}); }
async function openGame(context){
  const page=await context.newPage();
  await page.goto('https://poki.com/en/g/subway-surfers',{waitUntil:'domcontentloaded',timeout:120000});
  let game=null,canvas=null,deadline=Date.now()+100000;
  while(Date.now()<deadline){game=page.frames().filter(f=>f.url().includes('.gdn.poki.com')).pop()||null;if(game){const c=game.locator('#pixi-canvas');if(await c.count().catch(()=>0)){canvas=c;break;}}await sleep(650);}
  if(!canvas) throw new Error('official Pixi canvas not found');
  const exact=await game.evaluate(()=>{const c=document.createElement('canvas'),gl=c.getContext('webgl',{stencil:true,failIfMajorPerformanceCaveat:true});if(!gl)return{ok:false};const e=gl.getExtension('WEBGL_debug_renderer_info');return{ok:true,stencil:gl.getParameter(gl.STENCIL_BITS),renderer:e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)}});
  if(!exact.ok) throw new Error('strict WebGL gate failed');
  const box=await canvas.boundingBox();if(box)await canvas.click({position:{x:box.width/2,y:box.height/2},force:true});
  return {page,game,canvas,exact};
}
async function robustBootstrap(canvas){
  for(let r=0;r<7;r++){
    for(const k of ['Space','Enter','ArrowLeft','ArrowRight','ArrowUp','ArrowDown']){await press(canvas,k);await sleep(310);}
  }
  await press(canvas,'Space');await sleep(900);
}
async function ensureMoving(canvas){
  for(let tries=0;tries<12;tries++){
    const a=await decode(await canvas.screenshot());await sleep(500);const b=await decode(await canvas.screenshot());
    const motion=meanAbs(a.gray,b.gray);
    if(motion>.012 && !isDeath(b)) return {ok:true,motion};
    for(const k of ['Space','ArrowUp','ArrowLeft','ArrowRight','ArrowDown']){await press(canvas,k);await sleep(250);}
  }
  return {ok:false,motion:0};
}
function startRecorder(file){
  const display=process.env.DISPLAY;if(!display)throw new Error('DISPLAY missing');
  const args=['-y','-loglevel','warning','-f','x11grab','-draw_mouse','0','-framerate','30','-video_size','1280x720','-i',`${display}+0,0`,'-an','-c:v','libx264','-preset','ultrafast','-crf','22','-pix_fmt','yuv420p',file];
  const p=spawn('ffmpeg',args,{stdio:['pipe','inherit','inherit']}); return p;
}
async function stopRecorder(p){
  if(!p||p.exitCode!==null)return; p.stdin.write('q\n');
  await Promise.race([new Promise(r=>p.once('exit',r)),sleep(5000)]); if(p.exitCode===null)p.kill('SIGINT');
}
async function runEpisode(canvas,attempt,maxSec=50){
  const file=path.join(OUT,`episode-${String(attempt).padStart(2,'0')}.mp4`);const logFile=path.join(OUT,`episode-${String(attempt).padStart(2,'0')}-actions.json`);
  const recorder=startRecorder(file);await sleep(700);const t0=Date.now();
  let prev=null,lane=1,lastMove=-99,step=0,dead=false;const decisions=[];
  while((Date.now()-t0)/1000<maxSec){
    const png=await canvas.screenshot();const img=await decode(png);
    if(isDeath(img)){dead=true;break;}
    const d=laneDanger(img.gray,img.w,img.h,prev);const action=chooseAction(d,lane,step,lastMove);const t=(Date.now()-t0)/1000;
    decisions.push({step,t_sec:+t.toFixed(4),action,lane_estimate:lane,pixel_danger:d.map(x=>+x.toFixed(5)),label_origin:'exact_browser_input'});
    if(action!=='stay')await press(canvas,KEYS[action]);
    if(action==='left'){lane=Math.max(0,lane-1);lastMove=step;}else if(action==='right'){lane=Math.min(2,lane+1);lastMove=step;}
    prev=img.gray;step++;await sleep(235);
  }
  const duration=(Date.now()-t0)/1000;await stopRecorder(recorder);
  fs.writeFileSync(logFile,JSON.stringify({attempt,duration_sec:duration,death_detected:dead,decisions},null,2));
  return {attempt,file,logFile,duration,dead,decisions};
}
(async()=>{
  const browser=await chromium.launch({headless:false,args:['--autoplay-policy=no-user-gesture-required','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=gl','--disable-dev-shm-usage','--no-sandbox','--window-size=1280,720']});
  const context=await browser.newContext({viewport:{width:1280,height:720},locale:'en-US'});const g=await openGame(context);fs.writeFileSync(path.join(OUT,'runtime.json'),JSON.stringify({url:g.game.url(),webgl:g.exact},null,2));
  await robustBootstrap(g.canvas);let movement=await ensureMoving(g.canvas);if(!movement.ok)throw new Error('could not establish moving gameplay after tutorial bootstrap');
  const episodes=[];
  for(let attempt=1;attempt<=4;attempt++){
    movement=await ensureMoving(g.canvas);if(!movement.ok){await robustBootstrap(g.canvas);movement=await ensureMoving(g.canvas);}
    const ep=await runEpisode(g.canvas,attempt,50);episodes.push(ep);if(ep.duration>=38 && !ep.dead)break;
    await press(g.canvas,'Space');await sleep(900);await ensureMoving(g.canvas);
  }
  const best=episodes.slice().sort((a,b)=>b.duration-a.duration)[0];
  if(!best || best.duration<30) throw new Error(`no continuous >=30s episode; best=${best?.duration}`);
  const finalVideo=path.join(OUT,'official_live_controlled_2026.mp4');fs.copyFileSync(best.file,finalVideo);
  const finalActions=path.join(OUT,'exact_actions.json');fs.copyFileSync(best.logFile,finalActions);
  const summary={stage:'5-controlled-official-game-source-v1',source_id:'official_live_controlled_2026',dataset_role:'exact_action_calibration',not_expert_imitation:true,selected_attempt:best.attempt,duration_sec:+best.duration.toFixed(3),death_detected:best.dead,decision_count:best.decisions.length,action_counts:Object.fromEntries(['stay','left','right','jump','roll'].map(a=>[a,best.decisions.filter(x=>x.action===a).length])),webgl:g.exact};
  fs.writeFileSync(path.join(OUT,'collector_summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify(summary,null,2));
  await context.close();await browser.close();
})().catch(async e=>{fs.writeFileSync(path.join(OUT,'fatal.txt'),String(e.stack||e));console.error(e);process.exit(1);});
