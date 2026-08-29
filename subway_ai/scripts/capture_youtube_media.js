#!/usr/bin/env node
const { chromium } = require('playwright');
const fs = require('fs');

async function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }

async function main(){
  const [,, url, outPath, secondsRaw] = process.argv;
  if(!url || !outPath) throw new Error('usage: capture_youtube_media.js <url> <out.webm> [seconds]');
  const seconds = Number(secondsRaw || 60);
  const browser = await chromium.launch({headless:true,args:['--autoplay-policy=no-user-gesture-required','--no-sandbox','--disable-dev-shm-usage']});
  const context = await browser.newContext({viewport:{width:1280,height:720},acceptDownloads:true,locale:'en-US'});
  const page = await context.newPage();
  await page.goto(url,{waitUntil:'domcontentloaded',timeout:120000});

  for(const label of ['Accept all','I agree','Reject all']){
    const b=page.getByRole('button',{name:label,exact:false});
    if(await b.count().catch(()=>0)){ await b.first().click({timeout:3000}).catch(()=>{}); await sleep(1000); }
  }

  await page.waitForSelector('video',{timeout:60000});
  await page.evaluate(async()=>{
    const v=document.querySelector('video');
    v.muted=true; v.volume=0; v.playbackRate=1;
    try{v.currentTime=0;}catch{}
    await v.play();
  });
  await page.waitForFunction(()=>{const v=document.querySelector('video');return v && v.readyState>=3 && !v.paused;},{timeout:30000});

  const meta=await page.evaluate(()=>{const v=document.querySelector('video');return {duration:v.duration,videoWidth:v.videoWidth,videoHeight:v.videoHeight,currentTime:v.currentTime};});
  fs.mkdirSync(require('path').dirname(outPath),{recursive:true});
  fs.writeFileSync(outPath+'.meta.json',JSON.stringify({url,requested_seconds:seconds,...meta},null,2));

  const downloadPromise=page.waitForEvent('download',{timeout:(seconds+30)*1000});
  const recordPromise=page.evaluate(async(seconds)=>{
    const v=document.querySelector('video');
    if(!v.captureStream) throw new Error('HTMLVideoElement.captureStream is unavailable');
    const stream=v.captureStream();
    for(const t of stream.getAudioTracks()) t.stop();
    const mime=MediaRecorder.isTypeSupported('video/webm;codecs=vp8')?'video/webm;codecs=vp8':'video/webm';
    const chunks=[];
    const recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:2500000});
    const done=new Promise((resolve,reject)=>{
      recorder.ondataavailable=e=>{if(e.data && e.data.size)chunks.push(e.data);};
      recorder.onerror=e=>reject(e.error||new Error('MediaRecorder error'));
      recorder.onstop=()=>{
        const blob=new Blob(chunks,{type:mime});
        const a=document.createElement('a');
        a.href=URL.createObjectURL(blob); a.download='capture.webm';
        document.body.appendChild(a); a.click(); a.remove();
        resolve();
      };
    });
    recorder.start(1000);
    await new Promise(r=>setTimeout(r,seconds*1000));
    recorder.stop();
    await done;
  },seconds);
  const download=await downloadPromise;
  await download.saveAs(outPath);
  await recordPromise;
  await browser.close();
  console.log(JSON.stringify({ok:true,outPath,seconds,...meta}));
}

main().catch(e=>{console.error(e.stack||e);process.exit(1)});
