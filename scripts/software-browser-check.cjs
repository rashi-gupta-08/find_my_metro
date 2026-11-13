// Only generated software journeys are changed. Never register accounts or alter operator data.
const { chromium } = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
async function run() {
  const root = 'http://localhost:5173';
  const system = await (await fetch(root+'/api/v1/system')).json();
  if (!system.software_inputs || !system.synthetic) throw new Error('Requires the isolated software profile.');
  const browser = await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const errors = [];
  const out = path.resolve('.local/software/checks');
  await fs.mkdir(out,{recursive:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(root+'/?developer=1');
    await page.getByRole('button',{name:'Run journey',exact:true}).waitFor();
    await page.getByLabel('Software journey condition').selectOption('transition');
    await page.getByRole('button',{name:'Run journey',exact:true}).click();
    await page.getByText('Journey restarted.',{exact:false}).waitFor();
    const states = [];
    const started = Date.now();
    while (Date.now()-started<18000) {
      const {trips}=await (await page.request.get(root+'/api/v1/trips')).json();
      const trip=trips.find(item=>item.line_id==='dmrc-software');
      if (trip) states.push({source:trip.state.source,context:trip.state.context,reason:trip.state.reason});
      await page.waitForTimeout(1000);
    }
    if (!states.some(item=>item.source==='estimate') || !states.some(item=>item.source==='crowd')) throw new Error('Transition did not hand over to qualified reports.');
    await page.getByRole('heading',{name:'Source tracking',exact:true}).waitFor();
    await page.screenshot({path:path.join(out,'web-tracking.png'),fullPage:true});
    await page.getByRole('button',{name:'Home',exact:true}).click();
    await page.getByLabel('Arrivals station').selectOption('dmrc-test-4');
    await page.locator('.arrival-card').first().waitFor();
    const mobileViewport=await browser.newPage({viewport:{width:390,height:844}});
    mobileViewport.on('pageerror',error=>errors.push(error.message));
    await mobileViewport.goto(root);
    await mobileViewport.locator('.software-controls').waitFor();
    if (await mobileViewport.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+2)) throw new Error('Web app overflows the mobile viewport.');
    await mobileViewport.screenshot({path:path.join(out,'web-phone.png'),fullPage:true});
    await page.getByLabel('Software journey condition').selectOption('normal');
    await page.getByRole('button',{name:'Run journey',exact:true}).click();
    await page.waitForTimeout(1500);
    const routeResponse=await page.request.get(root+'/api/v1/routes?origin=dmrc-test-1&destination=dmrc-test-4');
    if(routeResponse.status()!==200 || (await routeResponse.json()).routes.length<2) throw new Error('Route endpoint did not return valid alternatives.');
    const flutter = await browser.newPage({viewport:{width:390,height:844}});
    flutter.on('pageerror',error=>errors.push(error.message));
    let offline=false,flutterSocket;
    await flutter.routeWebSocket('**/ws/eta/**',async socket=>{
      if(offline) { await socket.close({code:1001});return; }
      flutterSocket=socket;socket.connectToServer();
    });
    await flutter.goto('http://localhost:5174');
    await flutter.locator('flt-glass-pane').waitFor({state:'attached',timeout:30000});
    await flutter.waitForTimeout(4000);
    await flutter.locator('flt-semantics-placeholder').evaluate(el=>el.click()).catch(()=>{});
    await flutter.getByText('FindMyMetro',{exact:true}).waitFor({timeout:10000});
    await flutter.getByText('Next trains at Surface Terminal',{exact:true}).waitFor();
    await flutter.screenshot({path:path.join(out,'flutter-phone.png')});
    offline=true;
    await flutter.route('**/api/**',route=>route.abort('internetdisconnected'));
    await flutterSocket.close({code:1001});
    await flutter.getByText(/Cached · snapshot/).waitFor({timeout:15000});
    await flutter.waitForTimeout(4500);
    await flutter.screenshot({path:path.join(out,'flutter-cached.png')});
    offline=false;
    await flutter.unroute('**/api/**');
    await flutter.getByText(/Connected · snapshot [0-2]s old/).waitFor({timeout:15000});
    if (errors.length) throw new Error(errors.join('\n'));
    console.log(JSON.stringify({web_handover:true,web_eta:true,route_alternatives:true,web_phone_layout:true,flutter_connected:true,flutter_cached_age:true,flutter_reconnect:true,synthetic_model:system.prediction.active,states:[...new Set(states.map(item=>`${item.context}:${item.source}`))],screenshots:out},null,2));
  } finally { await browser.close(); }
}
run().catch(error=>{console.error(error.message);process.exitCode=1;});
