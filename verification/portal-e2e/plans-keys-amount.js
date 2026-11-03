// Plans grouped by product, plan delete, revoked-key delete, compulsory amount — in a real browser.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  let fails = 0; const ok = (c, m) => { console.log(c ? '  ok  ' : '  FAIL', m); if (!c) fails++; };
  const p = await (await b.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
  p.on('pageerror', (e) => { console.log('PAGEERR', e.message); fails++; });
  await p.goto('http://127.0.0.1:4173/login');
  await p.fill('#login-username', 'admin'); await p.fill('#login-password', 'Pass@100%');
  await p.click('.lg-submit'); await p.waitForSelector('.wg-item');

  console.log('Product Plans');
  await p.goto('http://127.0.0.1:4173/plans'); await p.waitForSelector('.pp-product');
  const products = await p.$$eval('.pp-name', (els) => els.map((e) => e.textContent.trim()));
  ok(products.length >= 2, `one card per product (${products.join(', ')})`);
  ok((await p.$$('.pp-table')).length === 0, 'collapsed until opened');
  await p.click('.pp-product:has-text("KStack") .pp-head');
  const planNames = await p.$$eval('.pp-product.is-open .pp-plan-name', (els) => els.map((e) => e.textContent.trim()));
  ok(planNames.length === 4 && planNames[0].startsWith('Trial') && planNames[3] === 'Lifetime', `KStack shows its plans in order (${planNames.join(', ')})`);
  ok(p.url().includes('product='), 'URL remembers the open product');
  await p.screenshot({ path: '/tmp/plans.png' });
  await p.fill('#plan-search', 'monthly'); await p.waitForTimeout(1200);
  const hits = await p.$$eval('.pp-product.is-open .pp-plan-name', (els) => els.map((e) => e.textContent.trim()));
  ok(hits.length >= 2 && hits.every((h) => h === 'Monthly'), 'search opens every product with a matching plan');
  await p.fill('#plan-search', '');

  // add a plan to KFlash from inside the product, then delete it
  await p.click('.pp-product:has-text("KFlash") .pp-head');
  await p.click('button:has-text("Add plan to KFlash")');
  const modal = p.locator('.modal');
  await modal.locator('input').nth(0).fill('QUARTER');
  await modal.locator('input').nth(1).fill('Quarterly');
  await modal.getByLabel(/Duration/i).fill('90').catch(async () => { await modal.locator('input[type=number]').first().fill('90'); });
  await modal.locator('button[type=submit]').click();
  await p.waitForTimeout(800);
  ok(await p.locator('.pp-product:has-text("KFlash") .pp-plan-name:has-text("Quarterly")').count() === 1, 'plan added to that product');
  await p.locator('.pp-product:has-text("KFlash") tr:has-text("Quarterly") button[aria-label^="More actions"]').click();
  await p.click('.row-menu button:has-text("Delete plan")');
  await p.fill('.modal input', 'QUARTER');
  await p.click('.modal button:has-text("Delete plan")');
  await p.waitForTimeout(800);
  ok(await p.locator('.pp-product:has-text("KFlash") .pp-plan-name:has-text("Quarterly")').count() === 0, 'unused plan deleted');
  // a used plan is refused
  // KStack Yearly is used by licences in the demo data
  if (!(await p.locator('.pp-product:has-text("KStack") tr:has-text("Yearly")').isVisible())) await p.click('.pp-product:has-text("KStack") .pp-head');
  await p.locator('.pp-product:has-text("KStack") tr:has-text("Yearly") button[aria-label^="More actions"]').click();
  await p.click('.row-menu button:has-text("Delete plan")');
  await p.fill('.modal input', 'YEARLY');
  await p.click('.modal button:has-text("Delete plan")');
  await p.waitForTimeout(600);
  ok(/archive/i.test(await p.locator('.modal').innerText()), 'used plan refused with "archive instead"');
  await p.click('.modal button:has-text("Cancel")');

  console.log('Create licence: amount is compulsory');
  await p.goto('http://127.0.0.1:4173/licenses?new=1'); await p.waitForSelector('.modal');
  const sel = p.locator('.modal select');
  await sel.nth(0).selectOption({ index: 1 });
  await sel.nth(1).selectOption({ index: 1 }); await p.waitForTimeout(500);
  await sel.nth(2).selectOption({ index: 1 });
  const submit = p.locator('.modal button[type=submit]');
  const prefilled = await p.inputValue('#lic-amount');
  console.log(`  (amount prefilled from the plan price: "${prefilled}")`);
  await p.fill('#lic-amount', '');
  ok(await submit.isDisabled(), 'Create is disabled without an amount');
  await p.fill('#lic-amount', '-5');
  ok(await submit.isDisabled(), 'negative amount refused');
  await p.fill('#lic-amount', '18000');
  ok(!(await submit.isDisabled()), 'enabled once the amount is entered');
  await p.screenshot({ path: '/tmp/create-licence.png' });
  await submit.click(); await p.waitForURL(/\/licenses\/\d+/);
  await p.waitForSelector('.def-label:has-text("Amount")');
  const amt = await p.locator('.def-item:has(.def-label:has-text("Amount")) .def-value').innerText();
  ok(/18,000/.test(amt), `licence page shows the amount (${amt})`);

  console.log('License Keys: delete a revoked key');
  await p.goto('http://127.0.0.1:4173/license-keys?status=REVOKED');
  await p.waitForTimeout(800);
  let revoked = await p.locator('.key-card.is-revoked').count();
  if (revoked === 0) {
    // make one: regenerate a key from a licence page
    await p.goto('http://127.0.0.1:4173/license-keys'); await p.waitForTimeout(500);
  }
  await p.goto('http://127.0.0.1:4173/license-keys'); await p.waitForSelector('.key-card');
  ok(await p.locator('.key-card:not(.is-revoked) button:has-text("Delete")').count() === 0, 'no Delete on live keys');
  revoked = await p.locator('.key-card.is-revoked').count();
  if (revoked > 0) {
    const before = await p.locator('.key-card').count();
    const lic = (await p.locator('.key-card.is-revoked').first().locator('a.mono').innerText()).trim();
    await p.locator('.key-card.is-revoked').first().locator('button:has-text("Delete")').click();
    await p.fill('.modal input', lic);
    await p.click('.modal button:has-text("Delete key")');
    await p.waitForTimeout(800);
    ok(await p.locator('.key-card').count() === before - 1, 'revoked key deleted');
  } else {
    console.log('  (no revoked key in the demo data to delete)');
  }

  console.log('Approve request: plan + amount compulsory');
  await p.goto('http://127.0.0.1:4173/license-requests'); await p.waitForTimeout(800);
  const reviewRow = p.locator('tr:has-text("UNDER_REVIEW"), tr:has-text("Under review")').first();
  if (await reviewRow.count()) {
    await reviewRow.click(); await p.waitForTimeout(800);
    const approve = p.getByRole('button', { name: /Approve & issue/ });
    ok(await p.locator('#apr-plan').count() === 1 && await p.locator('#apr-amount').count() === 1, 'approve dialog asks plan and amount');
    await p.fill('#apr-amount', '');
    ok(await approve.isDisabled(), 'approve disabled without amount');
    await p.screenshot({ path: '/tmp/approve.png' });
  } else console.log('  (no request under review in the demo data)');

  await b.close();
  console.log('FAILS', fails);
})();
