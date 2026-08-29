const { chromium } = require('playwright');
const sharp = require('sharp');
const fs = require('fs');
const path = require('path');

const OUT = '/tmp/subway-agent-v0';
fs.mkdirSync(OUT, {recursive:true});
fs.mkdirSync(path.join(OUT,'teacher-frames'), {recursive:true});
fs.mkdirSync(path.join(OUT,'eval-frames'), {recursive:true});
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ACTIONS = ['stay','left','right','jump','roll'];
const KEYS = {left:'ArrowLeft',right:'ArrowRight',jump:'ArrowUp',roll:'ArrowDown'};

function randn() {
  let u=0,v=0;
  while(!u) u=Math.random(); while(!v) v=Math.random();
  return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);
}
function softmax(z){
  const m=Math.max(...z), e=z.map(x=>Math.exp(x-m)), s=e.reduce((a,b)=>a+b,0)||1;
  return e.map(x=>x/s);
}
function shuffle(a){ for(let i=a.length-1;i>0;i--){const j=(Math.random()*(i+1))|0; [a[i],a[j]]=[a[j],a[i]];} }

async function pixelsFromPng(buf, w=64, h=36) {
  const {data,info}=await sharp(buf).resize(w,h,{fit:'fill'}).removeAlpha().raw().toBuffer({resolveWithObject:true});
  const gray=new Float32Array(w*h);
  for(let i=0,p=0;i<gray.length;i++,p+=3) gray[i]=(0.299*data[p]+0.587*data[p+1]+0.114*data[p+2])/255;
  return {gray,w:info.width,h:info.height};
}
function compactObservation(gray,w,h,prevGray){
  // 32x18 nearest-cell pooling from the already-small 64x36 image.
  const ow=32,oh=18,n=ow*oh;
  const cur=new Float32Array(n), dif=new Float32Array(n);
  for(let y=0;y<oh;y++) for(let x=0;x<ow;x++){
    let s=0,sp=0;
    for(let yy=0;yy<2;yy++) for(let xx=0;xx<2;xx++){
      const idx=(y*2+yy)*w+(x*2+xx); s+=gray[idx]; sp+=prevGray?prevGray[idx]:gray[idx];
    }
    const k=y*ow+x; cur[k]=s/4-0.5; dif[k]=(s-sp)/4;
  }
  const out=new Float32Array(n*2); out.set(cur,0); out.set(dif,n); return out;
}
function laneDanger(gray,w,h,prevGray){
  const lanes=[[0.12,0.40],[0.34,0.66],[0.60,0.88]];
  const ys=[0.38,0.90];
  return lanes.map(([xa,xb])=>{
    const x0=Math.floor(w*xa),x1=Math.floor(w*xb),y0=Math.floor(h*ys[0]),y1=Math.floor(h*ys[1]);
    let edge=0,temp=0,mean=0,mean2=0,c=0;
    for(let y=y0;y<y1-1;y++) for(let x=x0;x<x1-1;x++){
      const i=y*w+x, v=gray[i];
      edge += Math.abs(v-gray[i+1])+Math.abs(v-gray[i+w]);
      if(prevGray) temp += Math.abs(v-prevGray[i]);
      mean+=v; mean2+=v*v; c++;
    }
    if(!c) return 0;
    edge/=2*c; temp/=c; mean/=c; mean2/=c;
    const sd=Math.sqrt(Math.max(0,mean2-mean*mean));
    return edge*1.15 + temp*0.75 + sd*0.12;
  });
}
function teacherAction(danger,lane,step,lastMoveStep){
  const here=danger[lane], valid=[];
  if(lane>0) valid.push({a:'left',lane:lane-1,d:danger[lane-1]});
  if(lane<2) valid.push({a:'right',lane:lane+1,d:danger[lane+1]});
  valid.sort((a,b)=>a.d-b.d);
  const best=valid[0];
  const moveCool=(step-lastMoveStep)>=2;
  // All lanes visually busy near-field: prefer a jump over a blind lane swap.
  if(here>0.105 && danger.every(d=>d>0.085)) return 'jump';
  if(moveCool && best && here>0.075 && best.d+0.012<here) return best.a;
  // Sparse low-risk exploration prevents the learner collapsing to "stay" only.
  const r=Math.random();
  if(here<0.075 && r<0.025) return 'jump';
  if(here<0.070 && r>=0.025 && r<0.040) return 'roll';
  if(moveCool && best && here<0.070 && r>=0.040 && r<0.060) return best.a;
  return 'stay';
}
async function act(page,a){ if(a!=='stay') await page.keyboard.press(KEYS[a]); }

async function openGame(context, tag){
  const page=await context.newPage();
  page.on('console',m=>fs.appendFileSync(path.join(OUT,`${tag}-console.log`),`[${m.type()}] ${m.text()}\n`));
  page.on('pageerror',e=>fs.appendFileSync(path.join(OUT,`${tag}-pageerror.log`),String(e)+'\n'));
  await page.goto('https://poki.com/en/g/subway-surfers',{waitUntil:'domcontentloaded',timeout:120000});
  const deadline=Date.now()+100000; let game=null,canvas=null;
  while(Date.now()<deadline){
    game=page.frames().filter(f=>f.url().includes('.gdn.poki.com')).pop()||null;
    if(game){ const c=game.locator('#pixi-canvas'); if(await c.count().catch(()=>0)){canvas=c;break;} }
    await sleep(750);
  }
  if(!canvas) throw new Error(`${tag}: real pixi canvas never appeared`);
  const exact=await game.evaluate(()=>{
    const c=document.createElement('canvas');
    const gl=c.getContext('webgl',{stencil:true,failIfMajorPerformanceCaveat:true});
    if(!gl) return {ok:false};
    const ext=gl.getExtension('WEBGL_debug_renderer_info');
    return {ok:true,stencil:gl.getParameter(gl.STENCIL_BITS),renderer:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)};
  });
  if(!exact.ok) throw new Error(`${tag}: exact unmodified WebGL gate failed`);
  const box=await canvas.boundingBox(); if(box) await canvas.click({position:{x:box.width/2,y:box.height/2},force:true});
  await sleep(900);
  for(const k of ['ArrowUp','Space']) { await page.keyboard.press(k); await sleep(900); }
  return {page,game,canvas,exact};
}

class TinyMLP {
  constructor(input,hidden=24,out=5){
    this.input=input;this.hidden=hidden;this.out=out;
    this.w1=new Float32Array(input*hidden); this.b1=new Float32Array(hidden);
    this.w2=new Float32Array(hidden*out); this.b2=new Float32Array(out);
    for(let i=0;i<this.w1.length;i++)this.w1[i]=randn()*Math.sqrt(2/input);
    for(let i=0;i<this.w2.length;i++)this.w2[i]=randn()*Math.sqrt(2/hidden);
  }
  forward(x){
    const h=new Float32Array(this.hidden);
    for(let j=0;j<this.hidden;j++){let s=this.b1[j],off=j*this.input;for(let i=0;i<this.input;i++)s+=this.w1[off+i]*x[i];h[j]=s>0?s:0;}
    const z=new Array(this.out);
    for(let k=0;k<this.out;k++){let s=this.b2[k],off=k*this.hidden;for(let j=0;j<this.hidden;j++)s+=this.w2[off+j]*h[j];z[k]=s;}
    return {h,p:softmax(z)};
  }
  train(samples,epochs=7,lr=0.012){
    const counts=Array(this.out).fill(0); samples.forEach(s=>counts[s.y]++);
    const total=samples.length; const cw=counts.map(c=>c?Math.min(4,total/(this.out*c)):1);
    const order=[...Array(total).keys()];
    const hist=[];
    for(let ep=0;ep<epochs;ep++){
      shuffle(order); let loss=0,correct=0;
      for(const idx of order){
        const {x,y}=samples[idx], {h,p}=this.forward(x); if(p.indexOf(Math.max(...p))===y)correct++;
        const wt=cw[y]; loss+=-Math.log(Math.max(1e-8,p[y]))*wt;
        const dz=new Float32Array(this.out); for(let k=0;k<this.out;k++)dz[k]=(p[k]-(k===y?1:0))*wt;
        const dh=new Float32Array(this.hidden);
        for(let k=0;k<this.out;k++){
          const off=k*this.hidden;
          for(let j=0;j<this.hidden;j++){dh[j]+=this.w2[off+j]*dz[k]; this.w2[off+j]-=lr*dz[k]*h[j];}
          this.b2[k]-=lr*dz[k];
        }
        for(let j=0;j<this.hidden;j++) if(h[j]>0){
          const g=dh[j],off=j*this.input; for(let i=0;i<this.input;i++)this.w1[off+i]-=lr*g*x[i]; this.b1[j]-=lr*g;
        }
      }
      hist.push({epoch:ep+1,loss:loss/total,accuracy:correct/total});
      lr*=0.86;
    }
    return {counts,classWeights:cw,history:hist};
  }
  predict(x){const p=this.forward(x).p;let y=0;for(let i=1;i<p.length;i++)if(p[i]>p[y])y=i;return {y,p,confidence:p[y]};}
  json(){return {input:this.input,hidden:this.hidden,out:this.out,w1:Array.from(this.w1),b1:Array.from(this.b1),w2:Array.from(this.w2),b2:Array.from(this.b2)};}
}

(async()=>{
  const browser=await chromium.launch({headless:false,args:[
    '--autoplay-policy=no-user-gesture-required','--enable-webgl','--ignore-gpu-blocklist',
    '--use-gl=angle','--use-angle=gl','--disable-dev-shm-usage','--no-sandbox'
  ]});
  const context=await browser.newContext({viewport:{width:1280,height:720},locale:'en-US',recordVideo:{dir:path.join(OUT,'video'),size:{width:1280,height:720}}});

  // -------- Teacher collection: pixels in, ordinary arrow keys out --------
  const teacher=await openGame(context,'teacher');
  fs.writeFileSync(path.join(OUT,'native-webgl.json'),JSON.stringify(teacher.exact,null,2));
  let prevGray=null,lane=1,lastMove=-99; const samples=[], teacherLog=[];
  const COLLECT_STEPS=170;
  for(let step=0;step<COLLECT_STEPS;step++){
    const png=await teacher.canvas.screenshot();
    if(step%20===0)fs.writeFileSync(path.join(OUT,'teacher-frames',`${String(step).padStart(3,'0')}.png`),png);
    const {gray,w,h}=await pixelsFromPng(png); const danger=laneDanger(gray,w,h,prevGray);
    const a=teacherAction(danger,lane,step,lastMove), y=ACTIONS.indexOf(a), x=compactObservation(gray,w,h,prevGray);
    samples.push({x,y}); teacherLog.push({step,a,laneBefore:lane,danger:danger.map(v=>+v.toFixed(4))});
    await act(teacher.page,a);
    if(a==='left'){lane=Math.max(0,lane-1);lastMove=step;} if(a==='right'){lane=Math.min(2,lane+1);lastMove=step;}
    prevGray=gray; await sleep(260);
  }
  fs.writeFileSync(path.join(OUT,'teacher-log.json'),JSON.stringify(teacherLog,null,2));
  const tv=teacher.page.video(); await teacher.page.close(); if(tv){const p=await tv.path();fs.copyFileSync(p,path.join(OUT,'teacher.webm'));}

  // -------- Learn an actual policy from the pixel observations --------
  const model=new TinyMLP(samples[0].x.length,24,ACTIONS.length);
  const training=model.train(samples,8,0.011);
  fs.writeFileSync(path.join(OUT,'model.json'),JSON.stringify(model.json()));
  fs.writeFileSync(path.join(OUT,'training.json'),JSON.stringify(training,null,2));

  // -------- Fresh game: learned model only. No teacher danger signal here. --------
  const evalRun=await openGame(context,'eval'); let eprev=null; const evalLog=[]; const evalCounts=Object.fromEntries(ACTIONS.map(a=>[a,0]));
  const EVAL_STEPS=105;
  for(let step=0;step<EVAL_STEPS;step++){
    const png=await evalRun.canvas.screenshot();
    if(step%12===0)fs.writeFileSync(path.join(OUT,'eval-frames',`${String(step).padStart(3,'0')}.png`),png);
    const {gray,w,h}=await pixelsFromPng(png); const x=compactObservation(gray,w,h,eprev); const pr=model.predict(x);
    let a=ACTIONS[pr.y];
    // Uncertain non-stay predictions are suppressed; uncertainty is not an extra game input.
    if(a!=='stay' && pr.confidence<0.36)a='stay';
    evalCounts[a]++; await act(evalRun.page,a);
    evalLog.push({step,a,confidence:+pr.confidence.toFixed(4),probs:pr.p.map(v=>+v.toFixed(4))});
    eprev=gray; await sleep(280);
  }
  const finalPng=await evalRun.canvas.screenshot(); fs.writeFileSync(path.join(OUT,'eval-final.png'),finalPng);
  fs.writeFileSync(path.join(OUT,'eval-log.json'),JSON.stringify(evalLog,null,2));
  const ev=evalRun.page.video(); await evalRun.page.close(); if(ev){const p=await ev.path();fs.copyFileSync(p,path.join(OUT,'learned-policy.webm'));}

  const summary={
    environment:'Official Subway Surfers web build on Poki, Chromium on Ubuntu/Xvfb',
    renderer:evalRun.exact,
    policyInputs:'two consecutive 32x18 grayscale pixel grids only',
    policyOutputs:ACTIONS,
    teacherSamples:samples.length,
    teacherActionCounts:Object.fromEntries(ACTIONS.map((a,i)=>[a,training.counts[i]])),
    trainingFinal:training.history.at(-1),
    evalSteps:EVAL_STEPS,
    evalActionCounts:evalCounts,
    caveat:'Agent v0 is imitation of a hand-built pixel heuristic, not reinforcement learning and not yet a strong gameplay benchmark.'
  };
  fs.writeFileSync(path.join(OUT,'summary.json'),JSON.stringify(summary,null,2));
  await context.close(); await browser.close();
  console.log('AGENT_V0_SUMMARY',JSON.stringify(summary));
})().catch(e=>{fs.writeFileSync(path.join(OUT,'fatal.txt'),String(e.stack||e));console.error(e);process.exit(1)});
