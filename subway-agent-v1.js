const { chromium } = require('playwright');
const sharp = require('sharp');
const fs = require('fs');
const path = require('path');
const OUT='/tmp/subway-agent-v1'; fs.mkdirSync(OUT,{recursive:true}); fs.mkdirSync(path.join(OUT,'collect-frames'),{recursive:true}); fs.mkdirSync(path.join(OUT,'eval-frames'),{recursive:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const KEYS={left:'ArrowLeft',right:'ArrowRight',jump:'ArrowUp',roll:'ArrowDown'};
function randn(){let u=0,v=0;while(!u)u=Math.random();while(!v)v=Math.random();return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v)}

async function imageFromPng(buf,w=64,h=36){
  const {data}=await sharp(buf).resize(w,h,{fit:'fill'}).removeAlpha().raw().toBuffer({resolveWithObject:true});
  const gray=new Float32Array(w*h), rgb=new Float32Array(w*h*3);
  for(let i=0,p=0;i<gray.length;i++,p+=3){const r=data[p]/255,g=data[p+1]/255,b=data[p+2]/255;rgb[p]=r;rgb[p+1]=g;rgb[p+2]=b;gray[i]=.299*r+.587*g+.114*b;}
  return {gray,rgb,w,h};
}
function isDeathScreen(img){
  const {rgb,w,h}=img; let green=0,lower=0,orange=0,total=w*h;
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    const p=(y*w+x)*3,r=rgb[p],g=rgb[p+1],b=rgb[p+2];
    if(y>=h*.5){lower++; if(g>r*1.12&&g>b*1.25&&g>.38)green++;}
    if(r>.68&&g>.20&&g<.78&&b<.28)orange++;
  }
  return green/Math.max(1,lower)>.48 && orange/total>.10;
}
function compactObs(gray,w,h,prev){
  const ow=16,oh=9,n=ow*oh,out=new Float32Array(n*2); const sx=w/ow,sy=h/oh;
  for(let oy=0;oy<oh;oy++)for(let ox=0;ox<ow;ox++){
    const x0=Math.floor(ox*sx),x1=Math.max(x0+1,Math.floor((ox+1)*sx)),y0=Math.floor(oy*sy),y1=Math.max(y0+1,Math.floor((oy+1)*sy));
    let s=0,sp=0,c=0;for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){let i=y*w+x;s+=gray[i];sp+=prev?prev[i]:gray[i];c++;}
    let k=oy*ow+ox;out[k]=s/c-.5;out[n+k]=(s-sp)/c;
  }return out;
}
function laneDanger(gray,w,h,prev){
  const lanes=[[.12,.40],[.34,.66],[.60,.88]], y0=Math.floor(h*.38),y1=Math.floor(h*.90);
  return lanes.map(([xa,xb])=>{const x0=Math.floor(w*xa),x1=Math.floor(w*xb);let edge=0,temp=0,m=0,m2=0,c=0;
    for(let y=y0;y<y1-1;y++)for(let x=x0;x<x1-1;x++){const i=y*w+x,v=gray[i];edge+=Math.abs(v-gray[i+1])+Math.abs(v-gray[i+w]);if(prev)temp+=Math.abs(v-prev[i]);m+=v;m2+=v*v;c++;}
    edge/=2*c;temp/=c;m/=c;m2/=c;const sd=Math.sqrt(Math.max(0,m2-m*m));return edge*1.15+temp*.75+sd*.12;});
}
async function act(page,a){if(a!=='stay')await page.keyboard.press(KEYS[a])}

async function bootstrap(page,canvas){
  const box=await canvas.boundingBox();if(box)await canvas.click({position:{x:box.width/2,y:box.height/2},force:true});
  const seq=['Space','Enter','ArrowUp','Space','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','ArrowRight','ArrowUp','ArrowLeft','ArrowDown'];
  for(const k of seq){await page.keyboard.press(k);await sleep(520)}
  await sleep(1200);
}
async function openGame(context,tag){
  const page=await context.newPage();page.on('console',m=>fs.appendFileSync(path.join(OUT,`${tag}-console.log`),`[${m.type()}] ${m.text()}\n`));
  await page.goto('https://poki.com/en/g/subway-surfers',{waitUntil:'domcontentloaded',timeout:120000});
  let game=null,canvas=null,deadline=Date.now()+100000;while(Date.now()<deadline){game=page.frames().filter(f=>f.url().includes('.gdn.poki.com')).pop()||null;if(game){const c=game.locator('#pixi-canvas');if(await c.count().catch(()=>0)){canvas=c;break}}await sleep(700)}
  if(!canvas)throw new Error(`${tag}: pixi canvas missing`);
  const exact=await game.evaluate(()=>{const c=document.createElement('canvas'),gl=c.getContext('webgl',{stencil:true,failIfMajorPerformanceCaveat:true});if(!gl)return{ok:false};const e=gl.getExtension('WEBGL_debug_renderer_info');return{ok:true,stencil:gl.getParameter(gl.STENCIL_BITS),renderer:e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)}});
  if(!exact.ok)throw new Error(`${tag}: exact game WebGL requirement failed`);
  await bootstrap(page,canvas);return{page,game,canvas,exact};
}
async function recover(page,canvas){
  await page.keyboard.press('Space');await sleep(900);await bootstrap(page,canvas);
}
function explorerAction(d,lane,step,lastMove){
  const valid=[];if(lane>0)valid.push({a:'left',lane:lane-1,d:d[lane-1]});if(lane<2)valid.push({a:'right',lane:lane+1,d:d[lane+1]});valid.sort((a,b)=>a.d-b.d);const best=valid[0],here=d[lane];
  if(here>.105&&d.every(x=>x>.08))return'jump';
  if(best&&step-lastMove>=2&&here>.062&&best.d+.008<here)return best.a;
  if(here>.095)return'jump';
  // safe coverage actions: collection behavior only, never used by learned evaluator
  if(step%23===11&&best&&step-lastMove>=2&&best.d<.09)return best.a;
  if(step%31===17&&here<.08)return'jump';
  if(step%47===29&&here<.07)return'roll';
  return'stay';
}
function policyAction(d,lane,step,lastMove){
  const valid=[];if(lane>0)valid.push({a:'left',lane:lane-1,d:d[lane-1]});if(lane<2)valid.push({a:'right',lane:lane+1,d:d[lane+1]});valid.sort((a,b)=>a.d-b.d);const best=valid[0],here=d[lane];
  if(here>.105&&d.every(x=>x>.08))return'jump';
  if(best&&step-lastMove>=2&&here>.064&&best.d+.009<here)return best.a;
  if(here>.105)return'jump';
  return'stay';
}

class Regressor{
  constructor(input,hidden=32,out=3){this.input=input;this.hidden=hidden;this.out=out;this.w1=new Float32Array(input*hidden);this.b1=new Float32Array(hidden);this.w2=new Float32Array(hidden*out);this.b2=new Float32Array(out);for(let i=0;i<this.w1.length;i++)this.w1[i]=randn()*Math.sqrt(2/input);for(let i=0;i<this.w2.length;i++)this.w2[i]=randn()*Math.sqrt(2/hidden);}
  f(x){const h=new Float32Array(this.hidden);for(let j=0;j<this.hidden;j++){let s=this.b1[j],o=j*this.input;for(let i=0;i<this.input;i++)s+=this.w1[o+i]*x[i];h[j]=s>0?s:0}const z=new Float32Array(this.out);for(let k=0;k<this.out;k++){let s=this.b2[k],o=k*this.hidden;for(let j=0;j<this.hidden;j++)s+=this.w2[o+j]*h[j];z[k]=s}return{h,z}}
  train(train,stats,epochs=16,lr=.008){let hist=[];for(let ep=0;ep<epochs;ep++){for(let ii=train.length-1;ii>0;ii--){let j=(Math.random()*(ii+1))|0;[train[ii],train[j]]=[train[j],train[ii]]}let loss=0;for(const s of train){const{h,z}=this.f(s.x),dz=new Float32Array(this.out);for(let k=0;k<this.out;k++){const target=(s.y[k]-stats.mean[k])/stats.std[k],e=z[k]-target;dz[k]=2*e/this.out;loss+=e*e/this.out}const dh=new Float32Array(this.hidden);for(let k=0;k<this.out;k++){let o=k*this.hidden;for(let j=0;j<this.hidden;j++){dh[j]+=this.w2[o+j]*dz[k];this.w2[o+j]-=lr*dz[k]*h[j]}this.b2[k]-=lr*dz[k]}for(let j=0;j<this.hidden;j++)if(h[j]>0){let g=dh[j],o=j*this.input;for(let i=0;i<this.input;i++)this.w1[o+i]-=lr*g*s.x[i];this.b1[j]-=lr*g}}hist.push({epoch:ep+1,standardizedMSE:loss/train.length});lr*=.90}return hist}
  predict(x,stats){const z=this.f(x).z;return Array.from(z,(v,k)=>Math.max(0,Math.min(.5,v*stats.std[k]+stats.mean[k])))}
  json(stats){return{input:this.input,hidden:this.hidden,out:this.out,stats,w1:Array.from(this.w1),b1:Array.from(this.b1),w2:Array.from(this.w2),b2:Array.from(this.b2)}}
}
function targetStats(samples){const mean=[0,0,0],std=[0,0,0];for(const s of samples)for(let k=0;k<3;k++)mean[k]+=s.y[k]/samples.length;for(const s of samples)for(let k=0;k<3;k++)std[k]+=(s.y[k]-mean[k])**2/samples.length;for(let k=0;k<3;k++)std[k]=Math.max(.008,Math.sqrt(std[k]));return{mean,std}}
function mse(model,samples,stats){let se=[0,0,0];for(const s of samples){const p=model.predict(s.x,stats);for(let k=0;k<3;k++)se[k]+=(p[k]-s.y[k])**2}return se.map(v=>v/samples.length)}
function baselineMse(samples,mean){let se=[0,0,0];for(const s of samples)for(let k=0;k<3;k++)se[k]+=(mean[k]-s.y[k])**2;return se.map(v=>v/samples.length)}

(async()=>{
  const browser=await chromium.launch({headless:false,args:['--autoplay-policy=no-user-gesture-required','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=gl','--disable-dev-shm-usage','--no-sandbox']});
  const context=await browser.newContext({viewport:{width:1280,height:720},locale:'en-US',recordVideo:{dir:path.join(OUT,'video'),size:{width:1280,height:720}}});
  const col=await openGame(context,'collect');fs.writeFileSync(path.join(OUT,'native-webgl.json'),JSON.stringify(col.exact,null,2));
  const samples=[],collectLog=[];let prev=null,lane=1,lastMove=-99,deaths=0,attempts=0;const TARGET=240;
  while(samples.length<TARGET&&attempts<650){attempts++;const png=await col.canvas.screenshot();const img=await imageFromPng(png);
    if(isDeathScreen(img)){deaths++;fs.writeFileSync(path.join(OUT,`collect-death-${String(deaths).padStart(2,'0')}.png`),png);await recover(col.page,col.canvas);prev=null;lane=1;lastMove=-99;continue}
    const d=laneDanger(img.gray,img.w,img.h,prev),x=compactObs(img.gray,img.w,img.h,prev),step=samples.length,a=explorerAction(d,lane,step,lastMove);
    samples.push({x,y:d});collectLog.push({step,a,laneBefore:lane,d:d.map(v=>+v.toFixed(4))});if(step%30===0)fs.writeFileSync(path.join(OUT,'collect-frames',`${String(step).padStart(3,'0')}.png`),png);
    await act(col.page,a);if(a==='left'){lane=Math.max(0,lane-1);lastMove=step}else if(a==='right'){lane=Math.min(2,lane+1);lastMove=step}prev=img.gray;await sleep(230);
  }
  if(samples.length<TARGET)throw new Error(`only collected ${samples.length} active frames`);
  fs.writeFileSync(path.join(OUT,'collect-log.json'),JSON.stringify(collectLog,null,2));const cv=col.page.video();await col.page.close();if(cv){const p=await cv.path();fs.copyFileSync(p,path.join(OUT,'collection.webm'))}

  const cut=Math.floor(samples.length*.80),train=samples.slice(0,cut),val=samples.slice(cut),stats=targetStats(train),model=new Regressor(train[0].x.length,32,3),history=model.train(train,stats,18,.0075);
  const trainMSE=mse(model,train,stats),valMSE=mse(model,val,stats),base=baselineMse(val,stats.mean);
  fs.writeFileSync(path.join(OUT,'model.json'),JSON.stringify(model.json(stats)));fs.writeFileSync(path.join(OUT,'training.json'),JSON.stringify({history,stats,trainMSE,valMSE,baselineValMSE:base},null,2));

  const ev=await openGame(context,'eval');let eprev=null,elane=1,elast=-99,deathStep=null;const evalLog=[],counts={stay:0,left:0,right:0,jump:0,roll:0};const MAX=140;
  for(let step=0;step<MAX;step++){
    const png=await ev.canvas.screenshot();const img=await imageFromPng(png);if(isDeathScreen(img)){deathStep=step;fs.writeFileSync(path.join(OUT,'eval-death.png'),png);break}
    if(step%14===0)fs.writeFileSync(path.join(OUT,'eval-frames',`${String(step).padStart(3,'0')}.png`),png);
    const x=compactObs(img.gray,img.w,img.h,eprev),d=model.predict(x,stats),a=policyAction(d,elane,step,elast);counts[a]++;await act(ev.page,a);evalLog.push({step,a,laneBefore:elane,predDanger:d.map(v=>+v.toFixed(4))});if(a==='left'){elane=Math.max(0,elane-1);elast=step}else if(a==='right'){elane=Math.min(2,elane+1);elast=step}eprev=img.gray;await sleep(245);
  }
  const final=await ev.canvas.screenshot();fs.writeFileSync(path.join(OUT,'eval-final.png'),final);fs.writeFileSync(path.join(OUT,'eval-log.json'),JSON.stringify(evalLog,null,2));const vv=ev.page.video();await ev.page.close();if(vv){const p=await vv.path();fs.copyFileSync(p,path.join(OUT,'learned-danger-policy.webm'))}
  const summary={environment:'Official Subway Surfers web build on Poki, unmodified WebGL gate',renderer:ev.exact,trainingActiveFrames:samples.length,collectionDeathsExcluded:deaths,model:'two-frame 16x9 grayscale MLP -> 3 learned lane-danger values',validationMSE:valMSE,meanBaselineMSE:base,evalMaxSteps:MAX,evalSurvivedSteps:deathStep===null?MAX:deathStep,evalDeathDetected:deathStep!==null,evalActionCounts:counts,caveat:'v1 learns a dense visual hazard representation distilled from a hand-built pixel metric; it is not yet end-to-end RL.'};
  fs.writeFileSync(path.join(OUT,'summary.json'),JSON.stringify(summary,null,2));await context.close();await browser.close();console.log('AGENT_V1_SUMMARY',JSON.stringify(summary));
})().catch(e=>{fs.writeFileSync(path.join(OUT,'fatal.txt'),String(e.stack||e));console.error(e);process.exit(1)});
