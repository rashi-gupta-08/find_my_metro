/* Verify the curated local handover and render its architecture asset. */
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {chromium}=require('playwright');

(async()=>{
  const root=path.resolve(__dirname,'..'),out=path.join(root,'artifacts/evaluation-panel');
  const qa=path.join(root,'.local/evaluation-authoring');fs.mkdirSync(qa,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--disable-gpu']});
  try{
    if(process.argv.includes('--architecture')){
      const page=await browser.newPage({viewport:{width:1440,height:760},deviceScaleFactor:1.5});
      await page.setContent('<html><body style="margin:0">'+fs.readFileSync(path.join(out,'software-architecture.svg'),'utf8')+'</body></html>');
      await page.locator('svg').screenshot({path:path.join(out,'software-architecture.png'),timeout:20000});
      await page.close();console.log('Architecture asset rendered.');return;
    }
    const checks=[];
    for(const [name,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:391,height:844}]]){
      const page=await browser.newPage({viewport});const errors=[];page.on('pageerror',error=>errors.push(error.message));
      await page.goto(pathToFileURL(path.join(out,'START_HERE.html')).href);
      await page.waitForSelector('h1');
      const links=await page.locator('a').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')));
      const missing=links.filter(h=>h&&!/^(https?:|#)/.test(h)).filter(h=>!fs.existsSync(path.join(out,decodeURIComponent(h.split('#')[0]))));
      const content=await page.locator('body').innerText();
      const geometry=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth,
        images:[...document.images].map(i=>i.complete&&i.naturalWidth>0)}));
      await page.screenshot({path:path.join(qa,`evaluation-${name}.png`),fullPage:true});
      await page.locator('a[href="recorded-demo/panel-demo.html"]').click();
      await page.waitForSelector('#delay-log-body tr');
      const reports=await page.locator('#delay-log-body tr').count();
      await page.locator('#phase').selectOption('evidence_expired');
      const expired=await page.locator('#details tr td:nth-child(4)').allTextContents();
      checks.push({viewport:name,missingLinks:missing,jsErrors:errors,geometry,recordedReports:reports,
        expiryClients:expired.length,passed:!missing.length&&!errors.length&&geometry.width<=geometry.viewport&&geometry.images.every(Boolean)&&
          reports===400&&expired.length===100&&expired.every(x=>x==='schedule')&&content.includes('1.531')&&content.includes('4.548')&&content.includes('500 / 500')});
      await page.close();
    }
    const result={checks,allChecksPassed:checks.every(x=>x.passed)};
    fs.writeFileSync(path.join(out,'browser-verification.json'),JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify(result,null,2));if(!result.allChecksPassed)process.exitCode=1;
  }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
