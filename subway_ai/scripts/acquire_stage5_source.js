#!/usr/bin/env node
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

function arg(name, fallback=null){ const i=process.argv.indexOf(name); return i>=0 ? process.argv[i+1] : fallback; }
const sample = arg('--sample','240805-s1s47azglp');
const out = arg('--out');
const expected = (arg('--sha256')||'').toLowerCase();
if(!out) throw new Error('--out required');
fs.mkdirSync(path.dirname(out),{recursive:true});

(async()=>{
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({acceptDownloads:true, viewport:{width:1280,height:900}});
  const url = `https://tria.ge/${sample}/static1`;
  await page.goto(url,{waitUntil:'domcontentloaded',timeout:60000});
  await page.waitForTimeout(1500);
  await page.screenshot({path:'/tmp/stage5-triage-page.png',fullPage:true});
  const locator = page.getByText(/Download Sample/i).first();
  if(await locator.count()===0) throw new Error('Download Sample control not found');
  const downloadPromise = page.waitForEvent('download',{timeout:30000});
  await locator.click({timeout:15000});
  const dl = await downloadPromise;
  const tmp = await dl.path();
  if(!tmp) throw new Error('download had no temporary path');
  fs.copyFileSync(tmp,out);
  const buf=fs.readFileSync(out);
  const sha=crypto.createHash('sha256').update(buf).digest('hex');
  console.log(JSON.stringify({sample,url,out,bytes:buf.length,sha256:sha,suggestedFilename:dl.suggestedFilename()},null,2));
  if(expected && sha!==expected){
    console.log('Downloaded object is likely the UI ZIP wrapper; SHA check deferred until extraction.');
  }
  await browser.close();
})().catch(e=>{ console.error(e); process.exit(2); });
