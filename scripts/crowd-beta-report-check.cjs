// Read-only visual and interaction checks of the generated beta report.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
async function main(){
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const output=path.resolve('.local/crowd-beta/report-checks');await fs.mkdir(output,{recursive:true});
  const errors=[];
  try{
    const page=await browser.newPage({viewport:{width:1360,height:1000}});page.on('pageerror',e=>errors.push(e.message));
    await page.goto(pathToFileURL(path.resolve('artifacts/crowdsourcing-beta/latest-report.html')).href);
    assert.equal(await page.locator('.scenario').count(),47);
    assert((await page.locator('.cards').innerText()).includes('47/47'));
    await page.locator('.scenario').first().locator('summary').first().click();
    assert(await page.getByRole('cell',{name:'confirmed',exact:true}).first().isVisible());
    await page.screenshot({path:path.join(output,'beta-report-desktop.png'),fullPage:false});
    await page.getByRole('searchbox',{name:'Search scenarios'}).fill('underground');
    assert.equal(await page.locator('.scenario:visible').count(),2);
    await page.getByRole('searchbox',{name:'Search scenarios'}).fill('');
    await page.getByRole('combobox',{name:'Filter results'}).selectOption('failed');
    assert.equal(await page.locator('.scenario:visible').count(),0);
    await page.getByRole('combobox',{name:'Filter results'}).selectOption('all');
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=390));
    await page.screenshot({path:path.join(output,'beta-report-phone.png'),fullPage:false});
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({scenario_cards:47,passed_scenarios:47,search_and_filters:'passed',mobile_overflow:false,errors},null,2));
  }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
