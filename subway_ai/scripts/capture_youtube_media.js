#!/usr/bin/env node
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

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
  const embedUrl=`https://www.youtube-nocookie.com/embed/${id}?autoplay=1&mute=1&controls=0&playsinline=1&rel=0`;

  fs.mkdirSync(path.dirname(outPath),{recursive:true});
  const diag=outPath+'.diagnostics.json';
  const browser = await chromium.launch({headless:true,args:['--autoplay-policy=no-user-gesture-required','--no-sandbox','--disable-dev-shm-usage']});
  const context = await browser.newContext({viewport:{width:1280,height:720},acceptDownloads:true,locale:'en-US'});
  const page = await context.newPage();
  const consoleLog=[];
  page.on('console',m=>consoleLog.push(`[${m.type()}] ${m.text()}`));
  page.on('pageerror',e=>consoleLog.push(`[pageerror] ${String(e)}`));

  try{
    await page.goto(embedUrl,{waitUntil:'domcontentloaded',timeout:45000});
    const deadline=Date.now()+45000;
    let state=null;
    while(Date.now()<deadline){
      state=await page.evaluate(()=>{
        const v=document.querySelector('video');
        return {
          href:location.href,
          title:document.title,
          text:(document.body?.innerText||'').slice(0,1200),
          hasVideo:!!v,
          readyState:v?.readyState??null,
          paused:v?.paused??null,
          currentTime:v?.currentTime??null,
          duration:v?.duration??null,
          videoWidth:v?.videoWidth??null,
          videoHeight:v?.videoHeight??null,
          captureStream:!!v?.captureStream
        };
      });
      if(state.hasVideo && state.readyState>=2){
        await page.evaluate(async()=>{const v=document.querySelector('video');v.muted=true;v.volume=0;try{await v.play();}catch{}});
        state=await page.evaluate(()=>{const v=document.querySelector('video');return {readyState:v?.readyState,paused:v?.paused,currentTime:v?.currentTime};});
        if(state.readyState>=2 && state.paused===false) break;
      }
      await page.waitForTimeout(1000);
    }

    const meta=await page.evaluate(()=>{
      const v=document.querySelector('video');
      return {title:document.title,text:(document.body?.innerText||'').slice(0,1200),hasVideo:!!v,
        readyState:v?.readyState??null,paused:v?.paused??null,currentTime:v?.currentTime??null,
        duration:v?.duration??null,videoWidth:v?.videoWidth??null,videoHeight:v?.videoHeight??null,
        captureStream:!!v?.captureStream};
    });
    fs.writeFileSync(diag,JSON.stringify({sourceUrl,embedUrl,meta,consoleLog},null,2));
    if(!meta.hasVideo || meta.readyState<2 || meta.paused!==false || !meta.captureStream){
      throw new Error(`embed video unavailable: ${JSON.stringify(meta)}`);
    }

    fs.writeFileSync(outPath+'.meta.json',JSON.stringify({sourceUrl,embedUrl,requested_seconds:seconds,...meta},null,2));
    const downloadPromise=page.waitForEvent('download',{timeout:(seconds+20)*1000});
    await page.evaluate(async(seconds)=>{
      const v=document.querySelector('video');
      const stream=v.captureStream();
      for(const t of stream.getAudioTracks()) t.stop();
      const mime=MediaRecorder.isTypeSupported('video/webm;codecs=vp8')?'video/webm;codecs=vp8':'video/webm';
      const chunks=[];
      const recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:2500000});
      const stopped=new Promise((resolve,reject)=>{
        recorder.ondataavailable=e=>{if(e.data?.size)chunks.push(e.data)};
        recorder.onerror=e=>reject(e.error||new Error('MediaRecorder error'));
        recorder.onstop=()=>{
          const blob=new Blob(chunks,{type:mime});
          const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='capture.webm';
          document.body.appendChild(a);a.click();a.remove();resolve();
        };
      });
      recorder.start(1000);
      await new Promise(r=>setTimeout(r,seconds*1000));
      recorder.stop();
      await stopped;
    },seconds);
    const download=await downloadPromise;
    await download.saveAs(outPath);
    console.log(JSON.stringify({ok:true,outPath,seconds,...meta}));
  } finally {
    await browser.close();
  }
}

main().catch(e=>{console.error(e.stack||e);process.exit(1)});
