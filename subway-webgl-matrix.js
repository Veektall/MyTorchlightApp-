const { chromium } = require('playwright');
const fs = require('fs');
const { execSync } = require('child_process');
const OUT='/tmp/subway-webgl-matrix';
fs.mkdirSync(OUT,{recursive:true});

function exactProbe(){
  const make=(opts,kind='webgl')=>{
    const c=document.createElement('canvas');
    let gl=null,err=null;
    try{gl=c.getContext(kind,opts)||(kind==='webgl'?c.getContext('experimental-webgl',opts):null)}catch(e){err=String(e)}
    if(!gl)return {ok:false,error:err};
    let renderer=null,vendor=null,version=null,attrs=null,stencilBits=null;
    try{
      attrs=gl.getContextAttributes(); version=gl.getParameter(gl.VERSION); stencilBits=gl.getParameter(gl.STENCIL_BITS);
      const ext=gl.getExtension('WEBGL_debug_renderer_info');
      renderer=ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);
      vendor=ext?gl.getParameter(ext.UNMASKED_VENDOR_WEBGL):gl.getParameter(gl.VENDOR);
    }catch(e){}
    return {ok:true,attrs,stencilBits,version,renderer,vendor};
  };
  return {
    ua:navigator.userAgent,
    webglRenderingContext:typeof WebGLRenderingContext!=='undefined',
    exact:make({stencil:true,failIfMajorPerformanceCaveat:true},'webgl'),
    noCaveat:make({stencil:true,failIfMajorPerformanceCaveat:false},'webgl'),
    webgl2:make({stencil:true,failIfMajorPerformanceCaveat:true},'webgl2')
  };
}

const pw=chromium.executablePath();
let chrome=null;
for(const p of ['/usr/bin/google-chrome','/usr/bin/google-chrome-stable','/usr/bin/chromium','/usr/bin/chromium-browser']){
  try{execSync(`test -x ${p}`);chrome=p;break}catch(e){}
}
const variants=[];
function add(name,args,exe=pw,env={}){variants.push({name,args,exe,env});}
add('pw-swiftshader-angle', ['--enable-webgl','--ignore-gpu-blocklist','--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader-webgl']);
add('pw-desktop-llvmpipe', ['--enable-webgl','--ignore-gpu-blocklist','--use-gl=desktop']);
add('pw-egl-llvmpipe', ['--enable-webgl','--ignore-gpu-blocklist','--use-gl=egl']);
add('pw-angle-gl-llvmpipe', ['--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=gl']);
add('pw-angle-default', ['--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle']);
if(chrome){
  add('chrome-desktop-llvmpipe',['--enable-webgl','--ignore-gpu-blocklist','--use-gl=desktop'],chrome);
  add('chrome-angle-gl-llvmpipe',['--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=gl'],chrome);
  add('chrome-swiftshader-angle',['--enable-webgl','--ignore-gpu-blocklist','--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader-webgl'],chrome);
}

(async()=>{
  const results={playwrightExecutable:pw,systemChrome:chrome,variants:[]};
  for(const v of variants){
    const rec={name:v.name,executable:v.exe,args:v.args};
    let browser;
    try{
      browser=await chromium.launch({headless:false,executablePath:v.exe,args:[...v.args,'--no-sandbox','--disable-dev-shm-usage'],env:{...process.env,...v.env}});
      const ctx=await browser.newContext({viewport:{width:640,height:480}});
      const page=await ctx.newPage();
      await page.goto('about:blank');
      rec.probe=await page.evaluate(exactProbe);
      // Only exercise the real official page if the exact Pixi gate passes.
      if(rec.probe.exact && rec.probe.exact.ok){
        rec.exactGatePass=true;
        await page.goto('https://poki.com/en/g/subway-surfers',{waitUntil:'domcontentloaded',timeout:120000});
        await page.waitForTimeout(18000);
        const game=page.frames().filter(f=>f.url().includes('.gdn.poki.com')).pop();
        if(game){
          rec.gameFrame={url:game.url(),text:(await game.locator('body').innerText().catch(()=>'' )).slice(0,500),canvasCount:await game.locator('canvas').count()};
          await game.locator('body').screenshot({path:`${OUT}/${v.name}-game.png`}).catch(()=>{});
        }
      }else rec.exactGatePass=false;
      await ctx.close();
    }catch(e){rec.error=String(e.stack||e)}
    finally{if(browser)await browser.close().catch(()=>{})}
    results.variants.push(rec);
    fs.writeFileSync(`${OUT}/matrix.json`,JSON.stringify(results,null,2));
    console.log(v.name,JSON.stringify(rec.probe||rec.error));
  }
  fs.writeFileSync(`${OUT}/matrix.json`,JSON.stringify(results,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
