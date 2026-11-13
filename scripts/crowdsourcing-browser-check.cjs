// Mutations are allowed only in the isolated test stack started by test-crowdsourcing.ps1.
const { chromium }=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const crypto=require('node:crypto');
const root=process.env.METRO_CROWD_CHECK_URL;
assert.equal(root,'http://localhost:5180','Refusing to send test reports to the passenger app');
const output=path.resolve(process.env.METRO_CROWD_CHECK_OUTPUT || '');
assert(output.startsWith(path.resolve('.local/crowd-checks')+path.sep));
async function eventually(check,description,timeout=25000) {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline) { if(await check())return; await new Promise(resolve=>setTimeout(resolve,1000)); }
  throw new Error(`Timed out: ${description}`);
}
async function main() {
  const checks=[],errors=[],contexts=[],users=[],bodies=[];
  const browser=await chromium.launch({headless:true,executablePath:process.env.METRO_CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const guard=await browser.newContext();
    const health=await (await guard.request.get(root+'/api/v1/health')).json();
    const system=await (await guard.request.get(root+'/api/v1/system')).json();
    assert.equal(health.database,'sqlite');assert.equal(health.simulated,false);assert.equal(system.synthetic,true);assert.equal(system.software_inputs,true);
    const network=await (await guard.request.get(root+'/api/v1/network')).json();
    const station=network.stations.find(station=>station.id==='dmrc-sftn');
    const line=network.lines.find(line=>line.station_ids.includes(station.id) && line.station_ids.some(id=>id==='dmrc-necc'));
    assert(station && line);assert.equal(station.zone,'surface');await guard.close();
    for(let index=0;index<3;index++) {
      const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['geolocation'],geolocation:{latitude:station.lat,longitude:station.lng,accuracy:10}});
      contexts.push(context);
      // Test notification denial without opening a native permission dialog.
      await context.addInitScript(()=>{Object.defineProperty(window,'Notification',{value:class {static permission='default';static async requestPermission(){return 'denied';}}});});
      const page=await context.newPage();page.setDefaultTimeout(25000);page.on('pageerror',error=>errors.push(error.message));
      await page.goto(root);await page.getByRole('button',{name:'Sign in',exact:true}).click();
      await page.getByRole('button',{name:'Create an account',exact:true}).click();
      const dialog=page.getByRole('dialog');
      await dialog.locator('input[autocomplete="name"]').fill(`Test passenger ${index+1}`);
      await dialog.locator('input[autocomplete="username"]').fill(`crowd_${crypto.randomBytes(5).toString('hex')}`);
      await dialog.locator('input[type="password"]').fill(crypto.randomBytes(20).toString('base64url'));
      await dialog.getByRole('button',{name:'Create account',exact:true}).click();
      await dialog.waitFor({state:'hidden'});
      users.push((await (await page.request.get(root+'/api/v1/auth/me')).json()).user);
      page.on('request',request=>{if(request.method()==='POST' && request.url().endsWith('/api/v1/reports/batch'))bodies.push({index,report:request.postDataJSON().reports[0]});});
    }
    checks.push('Three real accounts and independent authenticated browser sessions in an isolated database');
    const pages=contexts.map(context=>context.pages()[0]);
    // All three capture their own GPS fix and original timestamp through the normal web form.
    await Promise.all(pages.map(async page=>{
      await page.getByRole('button',{name:'Report',exact:true}).click();
      await page.getByRole('button',{name:'Report at station'}).click();
      await page.getByRole('combobox',{name:'Search report at station'}).fill('52');
      await page.getByRole('option',{name:/52/}).click();
    }));
    await Promise.all(pages.map(async page=>{
      await page.getByRole('button',{name:'Check GPS and send report'}).click();
      await page.getByRole('status').filter({hasText:'Report saved'}).waitFor();
      await page.keyboard.press('Escape');
    }));
    await eventually(async()=>{
      const status=await (await pages[0].request.get(root+'/api/v1/service-status')).json();
      return status.signals.some(signal=>signal.station_id===station.id && signal.line_id===line.id && signal.status==='confirmed' && signal.confirmations===3 && signal.delay_seconds===300);
    },'worker validates and confirms three reports');
    for(const page of pages)await page.locator('.report-outcome').filter({hasText:'Agreement confirmed'}).waitFor();
    assert.equal(bodies.length,3);checks.push('Normal GPS form → durable ingestion → worker validation → three-account agreement → private confirmed outcomes');
    const reward=await (await pages[0].request.get(root+'/api/v1/contributions/mine')).json();
    assert.equal(reward.points,10);assert.equal(reward.validated_contributions,1);
    checks.push('Independently confirmed reports earn one durable contribution award');
    const page=pages[0];
    for(const [label,search] of [['From','52'],['To','Electronic City']]) {
      await page.getByRole('button',{name:`${label} station`,exact:true}).click();
      await page.getByRole('combobox',{name:`Search ${label.toLowerCase()} station`}).fill(search);
      await page.getByRole('option').first().click();
    }
    await page.getByRole('button',{name:'Find my route',exact:true}).click();
    await page.locator('.route-method').filter({hasText:'Journey updates connected'}).waitFor();
    await page.locator('.journey-source[data-source="crowd"]').first().waitFor();
    await page.locator('.delay-alert').filter({hasText:'5 min extra wait'}).waitFor();
    const routeResult=await (await page.request.get(root+`/api/v1/routes?origin=${station.id}&destination=dmrc-necc`)).json();
    assert.equal(routeResult.routes[0].delay_seconds,300);assert.equal(routeResult.routes[0].source_statuses[0].scope,'station_service');
    assert.equal(routeResult.routes[0].source_statuses[0].next_arrival,null);
    await page.getByRole('button',{name:'Enable journey delay alerts'}).click();
    await page.getByRole('status').filter({hasText:'Notification permission was not granted'}).waitFor();
    checks.push('Live journey WebSocket receives community delay once, with in-app alerts and no invented train identity; notification denial remains usable');
    await page.evaluate(()=>{
      window.Notification.permission='granted';window.Notification.requestPermission=async()=> 'granted';
      window.testNotifications=[];
      ServiceWorkerRegistration.prototype.showNotification=async function(title,options){window.testNotifications.push({title,body:options.body});};
    });
    await page.getByRole('button',{name:'Enable journey delay alerts'}).click();
    await eventually(async()=>page.evaluate(()=>window.testNotifications.length===1),'opt-in notification');
    await page.waitForTimeout(2500);
    assert.equal(await page.evaluate(()=>window.testNotifications.length),1);
    await page.getByRole('button',{name:'Disable journey notifications'}).click();
    checks.push('Opt-in notification delivery is deduplicated across repeated live snapshots (delivery stubbed; no native notification sent)');
    await page.screenshot({path:path.join(output,'confirmed-journey.png'),fullPage:true});
    const me=await (await page.request.get(root+'/api/v1/auth/me')).json();
    const headers={'Origin':root,'X-CSRF-Token':me.csrf_token};
    const duplicate=await page.request.post(root+'/api/v1/surface-reports/batch',{headers,data:{reports:[bodies.find(body=>body.index===0).report]}});
    assert.equal((await duplicate.json()).acknowledgements[0].status,'duplicate');
    const owned=await (await page.request.get(root+'/api/v1/surface-reports/mine')).json();
    assert.equal(owned.reports.length,1);assert(!JSON.stringify(owned).includes('latitude'));
    const foreign=bodies.find(body=>body.index===1).report.event_id;
    // Ownership is enforced by private history even in the test profile.
    assert(!owned.reports.some(report=>report.event_id===foreign));
    checks.push('Duplicate delivery does not increase agreement; private history exposes only the owner and omits GPS coordinates');
    const bad={...bodies[0].report,event_id:crypto.randomUUID(),observed_at:new Date().toISOString(),latitude:0,longitude:0};
    await page.request.post(root+'/api/v1/surface-reports/batch',{headers,data:{reports:[bad]}});
    const historical={...bad,event_id:crypto.randomUUID(),latitude:station.lat,longitude:station.lng,observed_at:new Date(Date.now()-301000).toISOString()};
    await page.request.post(root+'/api/v1/surface-reports/batch',{headers,data:{reports:[historical]}});
    await eventually(async()=>{
      const history=await (await page.request.get(root+'/api/v1/surface-reports/mine')).json();
      return history.reports.some(report=>report.event_id===bad.event_id && report.outcome==='rejected' && report.reason==='outside_station_proximity') && history.reports.some(report=>report.event_id===historical.event_id && report.outcome==='historical');
    },'rejected GPS and historical upload outcomes');
    checks.push('Real worker rejects off-station GPS and retains old uploads without changing current evidence');
    // Queue with the real API unavailable, close the modal, and let the shared hook retry on reconnect.
    await page.getByRole('button',{name:'Home',exact:true}).click();
    await page.getByRole('button',{name:'Report',exact:true}).click();
    await contexts[0].setOffline(true);
    await page.getByRole('button',{name:'Check GPS and send report'}).click();
    await page.getByRole('status').filter({hasText:'Saved locally'}).waitFor();
    await page.keyboard.press('Escape');
    await page.getByText('1 report(s) waiting to upload',{exact:true}).waitFor();
    const queued=await page.evaluate(id=>JSON.parse(localStorage.getItem(`metro-surface-queue:${id}`)),users[0].id);
    assert.equal(queued.length,1);
    await contexts[0].setOffline(false);
    await eventually(async()=>page.evaluate(id=>JSON.parse(localStorage.getItem(`metro-surface-queue:${id}`) || '[]').length===0,users[0].id),'automatic retry while report dialog is closed',30000);
    await eventually(async()=>{
      const history=await (await page.request.get(root+'/api/v1/surface-reports/mine')).json();
      return history.reports?.some(report=>report.event_id===queued[0].event_id && Date.parse(report.observed_at)===Date.parse(queued[0].observed_at));
    },'original queued timestamp preserved');
    checks.push('Offline reports retry automatically with the modal closed, preserving event ID and observation time');
    await page.getByRole('button',{name:'Find my route',exact:true}).click();
    await page.locator('.route-method').filter({hasText:'Journey updates connected'}).waitFor();
    await page.evaluate(async()=>{await navigator.serviceWorker.ready;});
    await eventually(async()=>page.evaluate(()=>Boolean(navigator.serviceWorker.controller)),'offline worker takes control');
    const cached=await page.evaluate(async()=>{const requests=[];for(const key of await caches.keys())for(const request of await (await caches.open(key)).keys())requests.push(new URL(request.url).pathname);return requests;});
    assert(cached.includes('/index.html'));assert(cached.some(url=>url.startsWith('/assets/')));assert(cached.every(url=>!url.startsWith('/api/') && !url.startsWith('/ws/')));
    await contexts[0].setOffline(true);
    await page.reload({waitUntil:'domcontentloaded'});
    await page.getByRole('button',{name:'Find my route',exact:true}).waitFor();
    await page.getByRole('button',{name:'Find my route',exact:true}).click();
    await page.locator('.journey-card').first().waitFor();
    await page.locator('.route-method').filter({hasText:'Saved journey'}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Sign in',exact:true}).count(),1);
    await page.screenshot({path:path.join(output,'offline-reload.png'),fullPage:true});
    await contexts[0].setOffline(false);
    await page.locator('.route-method').filter({hasText:'Journey updates connected'}).waitFor();
    await page.getByRole('button',{name:users[0].display_name,exact:true}).waitFor();
    checks.push('App reloads offline with saved network/journey and visible age; private API/auth responses are never cached; reconnect refreshes');
    await eventually(async()=>Date.now()>=Math.max(...bodies.slice(0,3).map(body=>Date.parse(body.report.observed_at)))+30000,'original quorum expires after 30 seconds',35000);
    const expiredRoutes=await (await page.request.get(root+`/api/v1/routes?origin=${station.id}&destination=dmrc-necc`)).json();
    assert.equal(expiredRoutes.routes[0].delay_seconds,0);
    assert.equal((await (await page.request.get(root+'/api/v1/contributions/mine')).json()).points,10);
    checks.push('Live delay expires after 30 seconds without new input; repeated uploads do not duplicate rewards');
    assert.deepEqual(errors,[]);
    await fs.writeFile(path.join(output,'results.json'),JSON.stringify({checks,errors,created_at:new Date().toISOString(),database:'isolated SQLite test database',hardware_used:false},null,2));
    console.log(JSON.stringify({checks,errors,output},null,2));
  } catch(error) {
    for(let index=0;index<contexts.length;index++)await contexts[index].pages()[0]?.screenshot({path:path.join(output,`failure-${index}.png`),fullPage:true}).catch(()=>{});
    await fs.writeFile(path.join(output,'failure.txt'),String(error));throw error;
  } finally {await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
