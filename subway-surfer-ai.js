const { chromium } = require('playwright');
const { PNG } = require('pngjs');
const fs = require('fs');

const OUT = '/tmp/subway-ai';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));

function frameFeatures(buf) {
  const p = PNG.sync.read(buf);
  const {width:w,height:h,data} = p;
  const lum = (x,y) => {
    const i=(y*w+x)*4;
    return 0.299*data[i]+0.587*data[i+1]+0.114*data[i+2];
  };
  const lanes=[];
  for (const lane of [-1,0,1]) {
    let dy=0, dx=0, rgbSpread=0, n=0;
    for(let k=0;k<72;k++) {
      const yn=0.32 + (0.40*k/71);
      const y=clamp(Math.round(yn*h),1,h-2);
      const progress=(yn-0.32)/0.40;
      const spacing=w*(0.05+0.18*progress);
      const xc=w/2 + lane*spacing;
      const hw=w*(0.025+0.03*progress);
      const x0=clamp(Math.round(xc-hw),1,w-3);
      const x1=clamp(Math.round(xc+hw),x0+2,w-2);
      let rMean=0,gMean=0,bMean=0, cnt=0;
      for(let x=x0;x<=x1;x+=3) {
        dy += Math.abs(lum(x,y+1)-lum(x,y-1));
        dx += Math.abs(lum(x+1,y)-lum(x-1,y));
        const i=(y*w+x)*4; rMean+=data[i]; gMean+=data[i+1]; bMean+=data[i+2]; cnt++; n++;
      }
      if(cnt){rMean/=cnt;gMean/=cnt;bMean/=cnt; rgbSpread += Math.max(rMean,gMean,bMean)-Math.min(rMean,gMean,bMean);}
    }
    dy/=Math.max(n,1); dx/=Math.max(n,1); rgbSpread/=72;
    const flatPenalty=3.0*Math.max(0,7.0-dx);
    const risk=dy + flatPenalty + 0.035*rgbSpread;
    lanes.push({dy,dx,rgbSpread,risk});
  }
  const sig=[];
  for(let gy=0;gy<12;gy++) for(let gx=0;gx<20;gx++) {
    const x=Math.floor((gx+0.5)*w/20), y=Math.floor((gy+0.5)*h/12);
    sig.push(lum(x,y));
  }
  return {w,h,lanes,sig};
}

function sigDiff(a,b){
  if(!a||!b)return 999;
  let s=0; for(let i=0;i<a.length;i++)s+=Math.abs(a[i]-b[i]); return s/a.length;
}

function chooseAction(features, state) {
  const r=features.lanes.map(x=>x.risk);
  const current=state.lane+1;
  const candidates=[];
  if(state.lane>-1)candidates.push(current-1);
  candidates.push(current);
  if(state.lane<1)candidates.push(current+1);
  let best=candidates[0];
  for(const i of candidates) if(r[i]<r[best]) best=i;
  const minRisk=r[best], curRisk=r[current];

  if(minRisk>15.0 || curRisk>21.0) return {action:'jump', reason:'all_or_current_blocked', r};
  if(best!==current && curRisk-r[best]>3.4 && r[best]<15.0) {
    return {action:best<current?'left':'right', reason:'safer_lane', r};
  }
  if(state.stepsSinceJump>=5 && curRisk>12.8) return {action:'jump',reason:'low_barrier_guard',r};
  return {action:'stay',reason:'corridor_clear',r};
}

async function main(){
  fs.rmSync(OUT,{recursive:true,force:true});
  fs.mkdirSync(`${OUT}/frames`,{recursive:true});
  const browser=await chromium.launch({headless:false,args:[
    '--autoplay-policy=no-user-gesture-required','--enable-webgl','--ignore-gpu-blocklist',
    '--use-gl=angle','--use-angle=gl','--disable-dev-shm-usage','--no-sandbox'
  ]});
  const context=await browser.newContext({viewport:{width:1280,height:720},locale:'en-US',recordVideo:{dir:`${OUT}/video`,size:{width:1280,height:720}}});
  const page=await context.newPage();
  page.on('console',m=>fs.appendFileSync(`${OUT}/console.log`,`[${m.type()}] ${m.text()}\n`));
  page.on('pageerror',e=>fs.appendFileSync(`${OUT}/pageerror.log`,String(e)+'\n'));
  await page.goto('https://poki.com/en/g/subway-surfers',{waitUntil:'domcontentloaded',timeout:120000});

  let game=null,canvas=null;
  const deadline=Date.now()+90000;
  while(Date.now()<deadline){
    game=page.frames().filter(f=>f.url().includes('.gdn.poki.com')).pop()||null;
    if(game){const c=game.locator('#pixi-canvas'); if(await c.count().catch(()=>0)){canvas=c;break;}}
    await sleep(1000);
  }
  if(!canvas) throw new Error('official Subway Surfers canvas not found');
  const exact=await game.evaluate(()=>{const c=document.createElement('canvas');const gl=c.getContext('webgl',{stencil:true,failIfMajorPerformanceCaveat:true});return {ok:!!gl,attrs:gl?gl.getContextAttributes():null};});
  if(!exact.ok)throw new Error('native exact WebGL gate failed '+JSON.stringify(exact));
  fs.writeFileSync(`${OUT}/runtime.json`,JSON.stringify({url:game.url(),exact,inputRouting:'nested-frame-body'},null,2));

  const gameBody=game.locator('body');
  const sendKey=async key=>{
    await gameBody.focus();
    await gameBody.press(key,{delay:120});
  };

  const box=await canvas.boundingBox();
  if(box) await canvas.click({position:{x:box.width/2,y:box.height/2},force:true});
  await gameBody.focus();
  await sendKey('Space');
  await sleep(3500);
  fs.writeFileSync(`${OUT}/frames/tutorial-before.png`,await canvas.screenshot());

  // One-time tutorial bootstrap. Controls are sent directly to the nested SYBO frame;
  // cycling is safe because only the currently requested tutorial action advances it.
  const tutorial=['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'];
  for(let cycle=0;cycle<4;cycle++) {
    for(const key of tutorial){await sendKey(key);await sleep(2200);}
  }
  await sleep(3000);
  fs.writeFileSync(`${OUT}/frames/tutorial-after.png`,await canvas.screenshot());

  const log=[];
  const state={lane:0,stepsSinceJump:99,prevSig:null,stagnant:0};
  for(let step=0;step<36;step++){
    const buf=await canvas.screenshot();
    if(step%4===0)fs.writeFileSync(`${OUT}/frames/${String(step).padStart(2,'0')}.png`,buf);
    const f=frameFeatures(buf);
    const motion=sigDiff(f.sig,state.prevSig); state.prevSig=f.sig;
    state.stagnant=motion<0.9?state.stagnant+1:0;

    let decision;
    if(state.stagnant>=2){
      decision={action:'restart',reason:'pixel_stagnation',r:f.lanes.map(x=>x.risk)};
      await sendKey('Space'); await sleep(1000); await sendKey('ArrowUp');
      state.lane=0; state.stagnant=0;
    } else {
      decision=chooseAction(f,state);
      const map={left:'ArrowLeft',right:'ArrowRight',jump:'ArrowUp'};
      if(map[decision.action]){
        await sendKey(map[decision.action]);
        if(decision.action==='left')state.lane=Math.max(-1,state.lane-1);
        if(decision.action==='right')state.lane=Math.min(1,state.lane+1);
        if(decision.action==='jump')state.stepsSinceJump=0;
      }
    }
    log.push({step,t:Date.now(),motion,lane:state.lane,lanes:f.lanes,decision});
    state.stepsSinceJump++;
    await sleep(1250);
  }
  const final=await canvas.screenshot(); fs.writeFileSync(`${OUT}/frames/99-final.png`,final);
  fs.writeFileSync(`${OUT}/decisions.json`,JSON.stringify(log,null,2));
  const video=page.video(); await page.close(); await context.close();
  if(video){const p=await video.path();fs.copyFileSync(p,`${OUT}/vision-agent.webm`);}
  await browser.close();
}

main().catch(e=>{fs.mkdirSync(OUT,{recursive:true});fs.writeFileSync(`${OUT}/fatal.txt`,String(e.stack||e));console.error(e);process.exit(1)});
