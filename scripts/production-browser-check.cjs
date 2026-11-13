const { chromium } = require('playwright');
const crypto = require('node:crypto');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const failures = [], checks = [], errors = [];
  const username = 'qa_'+crypto.randomBytes(5).toString('hex');
  const password = crypto.randomBytes(24).toString('base64url');
  const newPassword = crypto.randomBytes(24).toString('base64url');
  let registered = false;
  page.on('pageerror', error => errors.push(error.message));
  async function check(name, action) { try { await action(); checks.push(name); } catch (error) { failures.push({ name, reason: error.message }); } }
  try {
    await page.goto('http://localhost:5173/');
    await page.getByText('Metro connections', { exact:true }).waitFor();
    await check('No simulated passenger data or demo controls', async () => {
      assert.equal(await page.getByLabel('Demo scenario').count(), 0);
      const text = await page.locator('body').innerText();
      assert(!/prototype|simulated|seeded demo|academic demo/i.test(text));
      assert(!/prototype|demo/i.test(await page.title()));
      assert(text.includes('Arrival data is not connected'));
    });
    await check('Both official metro operator connections', async () => {
      const links = await page.getByRole('link', { name:/Official journey information/ }).evaluateAll(items=>items.map(item=>item.href));
      assert(links.some(link=>link.startsWith('https://delhimetrorail.com/')));
      assert(links.some(link=>link.startsWith('https://www.nmrcnoida.com/')));
      await page.getByLabel('Metro operator').selectOption('nmrc');
    });
    await check('Built assets and content security policy', async () => {
      const response = await context.request.get('http://localhost:5173/');
      assert(response.headers()['content-security-policy'].includes("script-src 'self'"));
      assert.equal((await context.request.get('http://localhost:5173/@vite/client')).status(), 404);
      assert.equal((await context.request.get('http://localhost:5173/api/v1/demo/status')).status(), 404);
    });
    await check('Anonymous reports require sign-in', async () => {
      await page.getByRole('button',{name:'Report',exact:true}).click();
      await page.getByRole('dialog').getByRole('heading',{name:'Welcome back'}).waitFor();
    });
    await check('Registration creates a real passenger account', async () => {
      await page.getByRole('button',{name:'Create an account',exact:true}).click();
      await page.getByLabel('YOUR NAME',{exact:true}).fill('Browser verification');
      await page.getByLabel('USERNAME',{exact:true}).fill(username);
      await page.getByLabel('USERNAME',{exact:true}).focus(); await page.waitForTimeout(1200);
      assert(await page.getByLabel('USERNAME',{exact:true}).evaluate(item=>document.activeElement===item));
      await page.getByLabel('PASSWORD',{exact:true}).fill(password);
      await page.getByRole('button',{name:'Create account',exact:true}).click();
      await page.getByRole('button',{name:'Browser verification',exact:true}).waitFor(); registered = true;
      const account = await page.evaluate(async()=> (await fetch('/api/v1/auth/me')).json());
      assert.equal(account.user.role,'passenger'); assert.equal(account.user.verified_contributor,false);
      const cookies = await context.cookies(); assert(cookies.find(cookie=>cookie.name==='metro_session').httpOnly);
      const storage = await page.evaluate(()=>JSON.stringify(localStorage)); assert(!storage.includes(password)); assert(!storage.includes('csrf_token'));
    });
    await check('CSRF and admin access enforced through frontend proxy', async () => {
      const outcomes = await page.evaluate(async()=> {
        const denied = await fetch('/api/v1/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        const admin = await fetch('/api/v1/events'); return [denied.status,admin.status];
      }); assert.deepEqual(outcomes,[403,403]);
    });
    await check('Account survives reload and remains unverified', async () => {
      await page.reload(); await page.getByRole('button',{name:'Browser verification',exact:true}).waitFor();
      await page.getByRole('button',{name:'Browser verification',exact:true}).click();
      await page.getByText('Contributor verification is required', {exact:false}).waitFor();
      await page.keyboard.press('Escape'); assert.equal(await page.getByRole('dialog').count(),0);
    });
    await check('Account sign-out revokes session', async () => {
      await page.getByRole('button',{name:'Browser verification',exact:true}).click();
      await page.getByRole('button',{name:'Sign out and clear queued reports',exact:true}).click();
      await page.getByRole('button',{name:'Sign in',exact:true}).waitFor();
      const account = await page.evaluate(async()=> (await fetch('/api/v1/auth/me')).json()); assert.equal(account.user,null);
    });
    await check('Sign-in and password change work', async () => {
      await page.getByRole('button',{name:'Sign in',exact:true}).click();
      await page.getByLabel('USERNAME',{exact:true}).fill(username); await page.getByLabel('PASSWORD',{exact:true}).fill(password);
      await page.getByRole('dialog').getByRole('button',{name:'Sign in',exact:true}).click();
      await page.getByRole('button',{name:'Browser verification',exact:true}).waitFor();
      await page.getByRole('button',{name:'Browser verification',exact:true}).click();
      await page.getByText('Change password',{exact:true}).click();
      await page.getByLabel('CURRENT PASSWORD',{exact:true}).first().fill(password);
      await page.getByLabel('NEW PASSWORD',{exact:true}).fill(newPassword);
      await page.getByRole('button',{name:'Change password and sign out',exact:true}).click();
      await page.getByText('Password changed. Sign in again.',{exact:true}).waitFor();
      await page.getByLabel('USERNAME',{exact:true}).fill(username);await page.getByLabel('PASSWORD',{exact:true}).fill(newPassword);
      await page.getByRole('dialog').getByRole('button',{name:'Sign in',exact:true}).click();
      await page.getByRole('button',{name:'Browser verification',exact:true}).waitFor();
    });
    await check('Account deletion removes the verification account', async () => {
      await page.getByRole('button',{name:'Browser verification',exact:true}).click();
      await page.getByText('Delete account and personal reports',{exact:true}).click();
      await page.getByLabel('CURRENT PASSWORD',{exact:true}).last().fill(newPassword);
      await page.getByRole('button',{name:'Delete my account',exact:true}).click();
      await page.getByText('Your account and personal reports have been deleted.',{exact:true}).waitFor();registered=false;
      await page.keyboard.press('Escape');
    });
    await check('Mobile layouts have no horizontal overflow', async () => {
      for (const width of [390,320]) { await page.setViewportSize({width,height:850}); await page.waitForTimeout(200); assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)); }
      await page.screenshot({path:'test-results/production-mobile.png',fullPage:true});
    });
    await check('No browser runtime errors',async()=>assert.deepEqual(errors,[]));
    await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'test-results/production-desktop.png',fullPage:true});
  } finally {
    if (registered) {
      // Remove only the account created by this run; never touch passenger accounts.
      await page.evaluate(async ({ username,password,newPassword })=>{
        for (const value of [newPassword,password]) {
          const result = await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password:value})});
          if(result.ok) {const auth=await result.json();await fetch('/api/v1/auth/account/delete',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':auth.csrf_token},body:JSON.stringify({current_password:value})});break;}
        }
      },{username,password,newPassword}).catch(()=>{});
    }
    await browser.close();
  }
  fs.writeFileSync('test-results/production-browser.json',JSON.stringify({checks,failures,errors},null,2));
  console.log(JSON.stringify({passed:checks.length,failures,errors},null,2));
  if(failures.length) process.exitCode=1;
})();
