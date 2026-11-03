// Clicks through the real portal (production build) against the real backend,
// as a maker and a checker would. Every step prints ok/FAIL; screenshots go to outputs/e2e.
const { chromium } = require('playwright');
const B = process.env.KLC_API || 'http://127.0.0.1:3001/api/v1', UI = process.env.KLC_UI || 'http://127.0.0.1:5173';
const SHOTS = require('path').join(__dirname, 'screenshots'); require('fs').mkdirSync(SHOTS, { recursive: true });
const fails = [];
const check = (n, ok, d) => { console.log((ok ? '  ok   ' : '  FAIL ') + n + (ok || d === undefined ? '' : '  -> ' + String(d).slice(0, 200))); if (!ok) fails.push(n); };
async function api(method, path, body, token) {
  const r = await fetch(B + path, { method, headers: { 'content-type': 'application/json', ...(token ? { authorization: 'Bearer ' + token } : {}) }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, body: await r.json() };
}
const tok = async (u) => (await api('POST', '/auth/login', { username: u, password: 'Pass@100%' })).body.data.token;

async function login(browser, user) {
  const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => fails.push(`[${user}] page error: ${e.message}`));
  await page.goto(UI + '/login');
  await page.fill('#login-username', user);
  await page.fill('#login-password', 'Pass@100%');
  await page.click('button[type=submit]');
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 15000 });
  return page;
}

(async () => {
  const browser = await chromium.launch();
  const admin = await tok('admin'), maker = await tok('maker');

  console.log('A. maker-checker on a data change');
  const custs = (await api('GET', '/admin/customers', null, admin)).body.data.items;
  const c = custs[0];
  const sub = await api('PUT', `/admin/customers/${c.customerId}`, { ...c, contactPerson: 'Changed By Maker' }, maker);
  check('maker\'s edit is held for approval (202)', sub.status === 202, JSON.stringify(sub.body));
  const crId = sub.body.data?.changeRequestId;

  const mp = await login(browser, 'maker');
  await mp.goto(UI + '/approvals');
  await mp.getByText('Changed By Maker').first().or(mp.locator('tr', { hasText: String(c.companyName) }).first()).waitFor({ timeout: 10000 }).catch(() => {});
  await mp.locator('tr', { hasText: 'CUSTOMER' }).first().click().catch(() => {});
  await mp.waitForTimeout(800);
  check('maker sees own request but NO Approve button', (await mp.getByRole('button', { name: /^Approve$/ }).count()) === 0);
  await mp.screenshot({ path: `${SHOTS}/1-maker-own-request.png` });

  const cp = await login(browser, 'checker');
  await cp.goto(UI + '/approvals');
  await cp.locator('tr', { hasText: 'CUSTOMER' }).first().click();
  const approveBtn = cp.getByRole('button', { name: /^Approve$/ });
  await approveBtn.waitFor({ timeout: 10000 });
  check('checker sees Approve', await approveBtn.isVisible());
  await cp.screenshot({ path: `${SHOTS}/2-checker-review.png` });
  await approveBtn.click();
  await cp.waitForTimeout(1200);
  const cr = await api('GET', `/admin/change-requests/${crId}`, null, admin);
  check('change request APPROVED via the UI', cr.body.data?.status === 'APPROVED', cr.body.data?.status);
  const after = await api('GET', `/admin/customers/${c.customerId}`, null, admin);
  check('the customer record actually changed', JSON.stringify(after.body.data).includes('Changed By Maker'));

  console.log('B. Vehicle SIM request: bell -> review -> grant -> app collects');
  const MID = '7E57AB1E00C0FFEE';
  const ask = await api('POST', '/public/vbs-request', { machineId: MID, email: 'ops@acme.example', companyName: 'Acme Test Rig', hostName: 'RIG-01', appVersion: '1.0.0.0',
    macAddress: 'FC9D052BF108', cpuId: '178BFBFF00B40F40', biosSerial: 'no serial; fw American 1.70', motherboardId: '07E6220_PA1C099047', osName: 'Microsoft Windows 10 Pro',
    edition: 3, mode: 0, features: ['Can', 'Lin', 'FlexRay', 'Xcp'] });
  check('app request accepted', ask.status === 202);
  await cp.goto(UI + '/');
  const badge = cp.locator('.notif-count');
  await badge.waitFor({ timeout: 25000 });
  check('bell shows an unread count', Number(await badge.textContent()) >= 1, await badge.textContent());
  await cp.screenshot({ path: `${SHOTS}/3-bell-unread.png` });
  await cp.locator('.notif-btn').click();
  const item = cp.locator('.notif-item', { hasText: 'ops@acme.example' }).first();
  await item.waitFor({ timeout: 5000 });
  check('bell lists the request by product and requester', (await item.textContent()).includes('Vehicle SIM'));
  await cp.screenshot({ path: `${SHOTS}/4-bell-open.png` });
  await item.click();
  await cp.getByText('Requested from the Vehicle SIM app').waitFor({ timeout: 10000 });
  check('bell opens the request straight away', true);
  check('reviewer sees the hardware identity', (await cp.getByText('FC9D052BF108').count()) > 0 && (await cp.getByText(MID).count()) > 0);
  await cp.selectOption('#apr-plan', 'YEARLY');
  await cp.fill('#apr-amount', '25000');
  await cp.selectOption('#apr-edition', '2');            // grant Pro, not the Enterprise asked for
  await cp.locator('.toggle-chip', { hasText: /^Xcp$/ }).click();      // and drop XCP
  await cp.locator('.toggle-chip', { hasText: /^FlexRay$/ }).click();  // and FlexRay
  await cp.screenshot({ path: `${SHOTS}/5-grant-chosen.png`, fullPage: true });
  await cp.getByRole('button', { name: /Approve & issue/ }).click();
  await cp.waitForTimeout(1500);
  const st = await api('GET', `/public/vbs-status/${MID}`);
  check('app can now collect its key', st.body.data?.approved === true, JSON.stringify(st.body));
  const payload = Buffer.from(st.body.data.licenseKey.split('.')[0].replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString();
  const f = payload.split('|');
  check('key carries the reviewer\'s grant: Pro, Can+Lin only, this machine', f[2] === '2' && f[5] === '3' && f[6] === MID, payload);

  console.log('C. a maker cannot approve a licence request in the UI either');
  await api('POST', '/public/vbs-request', { machineId: 'AAAABBBBCCCCDDDD', email: 'x@y.example', companyName: 'Other Co' });
  await mp.goto(UI + '/license-requests');
  await mp.locator('tr', { hasText: 'x@y.example' }).first().click();
  await mp.getByText('Requested from the Vehicle SIM app').waitFor({ timeout: 10000 });
  check('maker sees the request but no "Approve & issue"', (await mp.getByRole('button', { name: /Approve & issue/ }).count()) === 0);
  await mp.screenshot({ path: `${SHOTS}/6-maker-no-approve.png` });

  console.log('D. issue a .lic by hand: upload -> signed file downloads');
  const ap = await login(browser, 'admin');
  const lics = (await api('GET', '/admin/licenses?status=ACTIVE&pageSize=100', null, admin)).body.data.items;
  const kf = lics.find((l) => l.productCode === 'KFLASH' && l.currentActivations < l.maxActivations);
  await ap.goto(`${UI}/licenses/${kf.licenseId}`);
  await ap.getByText('Issue Activation File').waitFor({ timeout: 10000 });
  await ap.setInputFiles('input[type=file]', { name: 'license 5.Lic', mimeType: 'text/plain', buffer: Buffer.from(JSON.stringify({ Product: 'Kflash', Customer: '', MacAddress: 'C403A843DD85', CPUID: 'BFEBFBFF000906A4', BIOS: 'R5PTCJ00S00322B', MotherBoardId: 'R521PTCJ000PE3MB', SerialKey: '', Key: '' })) });
  const [dl] = await Promise.all([ap.waitForEvent('download', { timeout: 10000 }), ap.getByRole('button', { name: /Issue signed file/ }).click()]);
  check('signed .lic downloaded with a proper name', /^kflash-LIC-.*\.lic$/.test(dl.suggestedFilename()), dl.suggestedFilename());
  const text = require('fs').readFileSync(await dl.path(), 'utf8');
  check('file is signed and bound to the uploaded hardware', /"Key": "[A-Za-z0-9+/=]{40,}"/.test(text) && text.includes('C403A843DD85'));
  await ap.waitForTimeout(800);
  await ap.locator('.card', { hasText: 'Activations (' }).first().screenshot({ path: `${SHOTS}/7-activations-row.png` });
  const [dl2] = await Promise.all([ap.waitForEvent('download', { timeout: 10000 }), ap.getByRole('button', { name: /^\.lic$/ }).first().click()]);
  check('the same file can be downloaded again from the machine row', require('fs').readFileSync(await dl2.path(), 'utf8') === text);

  await browser.close();
  console.log('\nFAILURES: ' + (fails.length ? fails.join(' | ') : 'none'));
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { console.log('CRASH', e.message.split('\n').slice(0, 4).join(' | ')); process.exit(2); });
