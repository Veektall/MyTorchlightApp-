const { chromium } = require('playwright');
const fs=require('fs');
const OUT='/tmp/subway-input';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

async function main(){
  fs.rmSync(OUT,{recursive:true,force:true}); fs.mkdirSync(`${OUT}/frames`,{recursive:true});
  const browser=await chromium.launch({headless:false,args:[
    '--autoplay-policy=no-user-gesture-required','--enable-webgl','--ignore-gpu-blocklist',
    '--use-gl=angle','--use-angle=gl','--disable-dev-shm-usage','--no-sandbox'
  ]});
  const context=await browser.newContext({viewport:{width:1280,height:720},locale:'en-US'});
  await context.addInitScript(()=>{
    window.__probeKeys=[];
    const rec=(phase,e)=>window.__probeKeys.push({phase,key:e.key,code:e.code,keyCode:e.keyCode,which:e.which,target:e.target&&e.target.tagName,isTrusted:e.isTrusted,t:performance.now()});
    addEventListener('keydown',e=>rec('down',e),true);
    addEventListener('keyup',e=>rec('up',e),true);
  });
  const page=await context.newPage();
  await page.goto('https://poki.com/en/g/subway-surfers',{waitUntil:'domcontentloaded',timeout:120000});
  let game=null,canvas=null;
  const deadline=Date.now()+90000;
  while(Date.now()<deadline){
    game=page.frames().filter(f=>f.url().includes('.gdn.poki.com')).pop()||null;
    if(game){const c=game.locator('#pixi-canvas');if(await c.count().catch(()=>0)){canvas=c;break;}}
    await sleep(1000);
  }
  if(!canvas)throw new Error('game canvas not found');
  const exact=await game.evaluate(()=>{const c=document.createElement('canvas');const gl=c.getContext('webgl',{stencil:true,failIfMajorPerformanceCaveat:true});return !!gl});
  if(!exact)throw new Error('exact webgl gate failed');
  await canvas.evaluate(el=>{el.tabIndex=0;el.focus()});
  await canvas.click({position:{x:300,y:250},force:true});
  await canvas.press('Space',{delay:150});
  await sleep(3500);
  fs.writeFileSync(`${OUT}/frames/00-start.png`,await canvas.screenshot());

  const seq=['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'];
  for(let cycle=0;cycle<3;cycle++){
    for(const key of seq){
      await canvas.evaluate(el=>{el.tabIndex=0;el.focus()});
      await canvas.press(key,{delay:180});
      await sleep(1400);
    }
  }
  fs.writeFileSync(`${OUT}/frames/10-after-canvas-press.png`,await canvas.screenshot());
  fs.writeFileSync(`${OUT}/keys-after-canvas-press.json`,JSON.stringify(await game.evaluate(()=>window.__probeKeys||[]),null,2));

  for(let cycle=0;cycle<3;cycle++){
    for(const key of seq){
      await canvas.click({position:{x:300,y:250},force:true});
      await canvas.evaluate(el=>{el.tabIndex=0;el.focus()});
      await page.keyboard.down(key); await sleep(220); await page.keyboard.up(key);
      await sleep(1400);
    }
  }
  fs.writeFileSync(`${OUT}/frames/20-after-page-downup.png`,await canvas.screenshot());
  fs.writeFileSync(`${OUT}/keys-final.json`,JSON.stringify(await game.evaluate(()=>window.__probeKeys||[]),null,2));
  fs.writeFileSync(`${OUT}/state.json`,JSON.stringify({url:game.url(),exact,keyCount:(await game.evaluate(()=>window.__probeKeys||[])).length},null,2));
  await browser.close();
}
main().catch(e=>{fs.mkdirSync(OUT,{recursive:true});fs.writeFileSync(`${OUT}/fatal.txt`,String(e.stack||e));console.error(e);process.exit(1)});
