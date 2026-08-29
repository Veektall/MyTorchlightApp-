#!/usr/bin/env node
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const http = require('http');

function videoId(url){
  const u=new URL(url);
  if(u.hostname==='youtu.be') return u.pathname.slice(1);
  if(u.searchParams.get('v')) return u.searchParams.get('v');
  const m=u.pathname.match(/\/(?:embed|shorts)\/([^/?]+)/);
  return m?m[1]:null;
}

async function main(){
  const [,, sourceUrl, outPath, secondsRaw] = process.argv;
  if(!sourceUrl || !outPath) throw new Error('usage: capture_youtube_media.js <url> <out.webm> [seconds]');
  const seconds = Number(secondsRaw || 30);
  const id=videoId(sourceUrl);
  if(!id) throw new Error('could not resolve YouTube video id');
  const embedUrl=`https://www.youtube-nocookie.com/embed/${id}?autoplay=1&mute=1&controls=0&playsinline=1&rel=0&modestbranding=1`;

  fs.mkdirSync(path.dirname(outPath),{recursive:true});
  const tempVideoDir=path.join(path.dirname(outPath),'.pw-video');
  fs.rmSync(tempVideoDir,{recursive:true,force:true});
  fs.mkdirSync(tempVideoDir,{recursive:true});
  const diag=outPath+'.diagnostics.json';

  const html=`<!doctype html><html><head><meta name="referrer" content="origin"><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#000}iframe{border:0;width:100vw;height:100vh;display:block}</style></head><body><iframe id="player" src="${embedUrl}" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></body></html>`;
  const server=http.createServer((req,res)=>{res.writeHead(200,{'Content-Type':'text/html','Referrer-Policy':'origin'});res.end(html)});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve)});
  const port=server.address().port;

  const browser = await chromium.launch({headless:true,args:['--autoplay-policy=no-user-gesture-required','--no-sandbox','--disable-dev-shm-usage']});
  const context = await browser.newContext({viewport:{width:1280,height:720},locale:'en-US',recordVideo:{dir:tempVideoDir,size:{width:1280,height:720}}});
  const page = await context.newPage();
  const consoleLog=[];
  page.on('console',m=>consoleLog.push(`[${m.type()}] ${m.text()}`));
  page.on('pageerror',e=>consoleLog.push(`[pageerror] ${String(e)}`));

  try{
    await page.goto(`http://127.0.0.1:${port}/`,{waitUntil:'domcontentloaded',timeout:30000});
    let playerFrame=null,meta=null;
    const deadline=Date.now()+45000;
    while(Date.now()<deadline){
      playerFrame=page.frames().find(f=>f.url().includes('youtube-nocookie.com/embed/'))||null;
      if(playerFrame){
        meta=await playerFrame.evaluate(()=>{
          const v=document.querySelector('video');
          return {title:document.title,text:(document.body?.innerText||'').slice(0,1200),hasVideo:!!v,
            readyState:v?.readyState??null,paused:v?.paused??null,currentTime:v?.currentTime??null,
            duration:v?.duration??null,videoWidth:v?.videoWidth??null,videoHeight:v?.videoHeight??null};
        }).catch(()=>null);
        if(meta?.hasVideo && meta.readyState>=2){
          await playerFrame.evaluate(async()=>{const v=document.querySelector('video');v.muted=true;v.volume=0;try{await v.play()}catch{}}).catch(()=>{});
          await page.waitForTimeout(1000);
          meta=await playerFrame.evaluate(()=>{const v=document.querySelector('video');return {title:document.title,text:(document.body?.innerText||'').slice(0,1200),hasVideo:!!v,readyState:v?.readyState??null,paused:v?.paused??null,currentTime:v?.currentTime??null,duration:v?.duration??null,videoWidth:v?.videoWidth??null,videoHeight:v?.videoHeight??null}}).catch(()=>meta);
          if(meta?.paused===false && (meta.currentTime||0)>0) break;
        }
      }
      await page.waitForTimeout(1000);
    }

    await page.screenshot({path:outPath+'.startup.png'}).catch(()=>{});
    fs.writeFileSync(diag,JSON.stringify({sourceUrl,embedUrl,localReferrer:`http://127.0.0.1:${port}/`,meta,consoleLog},null,2));
    if(!meta?.hasVideo || meta.readyState<2 || meta.paused!==false){
      throw new Error(`referred embed video unavailable: ${JSON.stringify(meta)}`);
    }

    const startTime=meta.currentTime||0;
    await page.waitForTimeout(seconds*1000);
    const endMeta=await playerFrame.evaluate(()=>{const v=document.querySelector('video');return {currentTime:v?.currentTime??null,paused:v?.paused??null,readyState:v?.readyState??null}}).catch(()=>null);
    if(!endMeta || (endMeta.currentTime||0)-startTime < Math.max(2,seconds*0.6)){
      throw new Error(`video did not advance enough: start=${startTime} end=${endMeta?.currentTime}`);
    }

    fs.writeFileSync(outPath+'.meta.json',JSON.stringify({sourceUrl,embedUrl,requested_seconds:seconds,startTime,endTime:endMeta.currentTime,...meta},null,2));
    const video=page.video();
    await page.close();
    await context.close();
    if(!video) throw new Error('Playwright page video handle missing');
    const recorded=await video.path();
    fs.copyFileSync(recorded,outPath);
    console.log(JSON.stringify({ok:true,outPath,seconds,startTime,endTime:endMeta.currentTime,...meta}));
  } finally {
    await browser.close().catch(()=>{});
    await new Promise(resolve=>server.close(resolve));
    fs.rmSync(tempVideoDir,{recursive:true,force:true});
  }
}

main().catch(e=>{console.error(e.stack||e);process.exit(1)});
