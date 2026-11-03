const { chromium } = require('playwright');
const API = 'http://127.0.0.1:3001/api/v1';
const VH = { 'content-type': 'application/json', 'x-client-key': 'demo-vehsim-client', 'x-client-secret': 'demo-secret-vehsim' };
(async () => {
  let fails = 0; const ok = (c, m) => { console.log(c ? '  ok  ' : '  FAIL', m); if (!c) fails++; };
  const post = (p, b, h) => fetch(API + p, { method: 'POST', headers: h ?? { 'content-type': 'application/json' }, body: JSON.stringify(b) }).then((r) => r.json());
  // an app reports a clock change
  const r = await post('/license/clock-alert', { productCode: 'VEHICLESIM', installationId: 'UIBENCH000000001', kind: 'MOVED_BACK',
    localTime: new Date(Date.now() - 3 * 86400e3).toISOString(), referenceTime: new Date().toISOString(), deltaSeconds: -3 * 86400, deviceName: 'TEST-BENCH-3' }, VH);
  ok(r.data?.recorded === true, 'app alert accepted');
  // a machine gets a trial, then asks again
  const tok = (await post('/auth/login', { username: 'checker', password: 'Pass@100%' })).data.token;
  const H = { 'content-type': 'application/json', authorization: 'Bearer ' + tok };
  const MID = 'F00DBABE12345678';
  const ask = async () => (await post('/public/vbs-request', { machineId: MID, email: 'again@trial.example', companyName: 'Trial Again Ltd', hostName: 'AGAIN-PC' })).data.requestId;
  const first = await ask();
  await post(`/admin/license-requests/${first}/approve`, { planCode: 'TRIAL', amount: 0, vbs: { mode: 0, edition: 2, features: ['Can'] } }, H);
  await fetch(`${API}/public/vbs-status/${MID}`);
  const second = await ask();

  const b = await chromium.launch();
  const p = await (await b.newContext({ viewport: { width: 1500, height: 1000 } })).newPage();
  await p.goto('http://127.0.0.1:4173/login');
  await p.fill('#login-username', 'checker'); await p.fill('#login-password', 'Pass@100%');
  await p.click('.lg-submit'); await p.waitForTimeout(1500);
  ok(await p.locator('.notif-btn.has-critical').count() === 1, 'bell pulses red for an unread critical alert');
  await p.click('.notif-btn'); await p.waitForTimeout(400);
  const crit = p.locator('.notif-item.is-critical').first();
  const text = await crit.innerText();
  ok(/CRITICAL/.test(text) && /moved back 3 days/.test(text) && /TEST-BENCH-3/.test(text), `critical alert reads clearly: "${text.replace(/\n/g, ' ')}"`);
  await p.screenshot({ path: '/tmp/bell.png' });
  await p.keyboard.press('Escape');

  await p.goto(`http://127.0.0.1:4173/license-requests?open=${second}`); await p.waitForTimeout(1500);
  const modal = await p.locator('.modal').innerText();
  ok(/already had a trial/.test(modal), 'reviewer is warned the machine already had a trial');
  const trialOpt = p.locator('#apr-plan option', { hasText: 'TRIAL' });
  ok(await trialOpt.isDisabled(), 'trial plan cannot be chosen for it');
  ok((await p.inputValue('#apr-plan')) === '', 'requested trial is not pre-selected');
  await p.screenshot({ path: '/tmp/trial-warning.png' });
  await b.close();
  console.log('FAILS', fails);
})();
