/* Verify the offline evidence viewer in desktop and mobile Chrome. */
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');

(async()=>{
  const root=path.resolve(__dirname,'..');
  const out=path.join(root,'artifacts','operator-crowd-100-users');
  const qa=path.join(root,'.local','operator-crowd-render');
  fs.mkdirSync(qa,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const checks=[];
  try {
    for(const [name,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:391,height:844}]]){
      const page=await browser.newPage({viewport});
      const errors=[];page.on('pageerror',error=>errors.push(error.message));
      await page.goto(pathToFileURL(path.join(out,'panel-demo.html')).href);
      await page.waitForSelector('#details tr');
      const initialRows=await page.locator('#details tr').count();
      const reportRows=await page.locator('#delay-log-body tr').count();
      const examples=await page.locator('#delay-examples').innerText();
      await page.locator('#delay-phase').selectOption('boundary_agreement');
      await page.locator('#delay-outcome').selectOption('validated');
      const boundaryValidReports=await page.locator('#delay-log-body tr').count();
      await page.locator('#delay-operator').selectOption('NMRC');
      const nmrcValidReports=await page.locator('#delay-log-body tr').count();
      await page.locator('#delay-outcome').selectOption('historical');
      const historicalReports=await page.locator('#delay-log-body tr').count();
      const staleReason=await page.locator('#delay-log-body').innerText();
      await page.locator('#delay-outcome').selectOption('rejected');
      const rejectedReports=await page.locator('#delay-log-body tr').count();
      const rejectedReason=await page.locator('#delay-log-body').innerText();
      await page.locator('[data-delay-example="2"]').click();
      const exampleNavigation=await page.locator('#phase').inputValue()==='fresh_evidence_recovery'&&
        await page.locator('#delay-phase').inputValue()==='fresh_evidence_recovery'&&
        await page.locator('#delay-log-body tr').count()===50;
      await page.locator('#phase').selectOption('boundary_agreement');
      const boundary=await page.locator('#summary').innerText();
      await page.locator('#next').click();
      await page.locator('#cohort').selectOption('DMRC surface to underground');
      const underground=await page.locator('#details').innerText();
      const filteredRows=await page.locator('#details tr').count();
      await page.locator('#phase').selectOption('evidence_expired');
      await page.locator('#cohort').selectOption('all');
      const expirySources=await page.locator('#details tr td:nth-child(4)').allTextContents();
      await page.locator('#delay-phase').selectOption('evidence_expired');
      const expiryMessage=await page.locator('#delay-log-body').innerText();
      await page.locator('[data-delay-example="0"]').click();
      const geometry=await page.evaluate(()=>({document:document.documentElement.scrollWidth,viewport:innerWidth,
        imageLoaded:document.querySelector('img').complete&&document.querySelector('img').naturalWidth>0}));
      await page.screenshot({path:path.join(qa,`panel-${name}.png`),fullPage:true});
      const delayChecks={reportRows,boundaryValidReports,nmrcValidReports,historicalReports,rejectedReports,exampleNavigation,
        passed:reportRows===400&&boundaryValidReports===60&&nmrcValidReports===30&&historicalReports===10&&rejectedReports===10&&
          staleReason.includes('45 seconds old')&&rejectedReason.includes('250 m')&&
          ['+6 min','+8 min','+10 min'].every(value=>examples.includes(value))&&exampleNavigation&&expiryMessage.includes('No reports were submitted')};
      const result={viewport:name,initialRows,filteredRows,delayChecks,jsErrors:errors,geometry,
        passed:initialRows===100&&filteredRows===25&&boundary.includes('transition')&&boundary.includes('Crowd agreement')&&
          underground.includes('schedule')&&expirySources.length===100&&expirySources.every(x=>x==='schedule')&&
          errors.length===0&&geometry.document<=geometry.viewport&&geometry.imageLoaded&&delayChecks.passed};
      checks.push(result);await page.close();
    }
  } finally {await browser.close();}
  const result={checks,all_checks_passed:checks.every(x=>x.passed)};
  fs.writeFileSync(path.join(out,'panel-viewer-verification.json'),JSON.stringify(result,null,2)+'\n');
  process.stdout.write(JSON.stringify(result,null,2)+'\n');
  if(!result.all_checks_passed)process.exitCode=1;
})().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1});
