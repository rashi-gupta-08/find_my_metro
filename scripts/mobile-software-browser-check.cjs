const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
(async()=>{
  const output='.local/mobile-software-check';await fs.mkdir(output,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const context=await browser.newContext({viewport:{width:390,height:844}});
  const page=await context.newPage();const errors=[],checks=[];
  page.on('pageerror',e=>errors.push(e.message));
  try{
    await page.goto('http://localhost:5174/');
    await page.locator('flt-glass-pane').waitFor({state:'attached'});
    await page.locator('flt-semantics-placeholder').waitFor({state:'attached'});
    await page.evaluate(()=>document.querySelector('flt-semantics-placeholder')?.click());
    await page.getByRole('button',{name:'Find my route',exact:true}).waitFor({timeout:30000});
    await page.getByRole('button',{name:'Find my route',exact:true}).click();
    await page.getByText(/min · 0 interchanges/).first().waitFor();
    checks.push('Flutter starts with the new Aqua journey planner and displays a backend route');
    await page.screenshot({path:output+'/flutter-journey.png'});
    await page.getByRole('button',{name:/All stations and source details/}).click();
    await page.getByText(/Noida Sector - 51/).first().waitFor();
    checks.push('Passenger can expand the complete station route and source details');
    await context.setOffline(true);
    await page.getByRole('button',{name:'Find my route',exact:true}).click();
    await page.getByText(/Offline Aqua estimate/).waitFor();
    checks.push('Disconnected journey falls back to the bundled static Aqua estimate');
    await page.screenshot({path:output+'/flutter-offline.png'});
    assert.deepEqual(errors,[]);
    await fs.writeFile(output+'/results.json',JSON.stringify({checks,errors,created_at:new Date().toISOString()},null,2));
    console.log(JSON.stringify({checks,errors},null,2));
  }catch(e){await page.screenshot({path:output+'/failure.png'});throw e;}
  finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
