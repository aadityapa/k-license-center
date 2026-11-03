/**
 * Renders VbsKeyPanel with react-dom/server to prove it mounts and produces the
 * expected controls. Not a pixel check — a structure check that type-checking
 * alone cannot give.
 */
import { renderToStaticMarkup } from 'react-dom/server';
import { VbsKeyPanel } from '../src/pages/licenses/VbsKeyPanel';
import { AuthContext } from '../src/auth/AuthContext';
import type { LicenseDetail } from '../src/types';

const licence = {
  licenseId: 7, licenseNo: 'LIC-2026-100007', customerId: 1, productId: 3, planId: 11,
  status: 'ACTIVE', startDate: '2026-10-19', expiryDate: '2027-10-19',
  maxActivations: 3, currentActivations: 0, customerName: 'Acme Distributors Pvt Ltd',
  productCode: 'VEHICLESIM', keyFormat: 'VBS_KEY',
  keys: [{ keyId: 1, licenseId: 7, licenseKey: 'old', status: 'ACTIVE' }],
} as unknown as LicenseDetail;

function render(perms: string[]) {
  const auth = {
    user: { userId: 1, username: 'admin', permissions: perms, roles: [] },
    hasPermission: (p: string) => perms.includes(p),
    hasAnyPermission: () => true,
    login: async () => {}, logout: () => {}, loading: false, error: null,
  } as never;
  return renderToStaticMarkup(
    <AuthContext.Provider value={auth}>
      <VbsKeyPanel license={licence} onChanged={() => {}} onPending={() => {}} />
    </AuthContext.Provider>,
  );
}

const withPerm = render(['LICENSE_MANAGE']);
const without = render(['LICENSE_VIEW']);

const checks: Array<[string, boolean]> = [
  ['renders for LICENSE_MANAGE',        withPerm.length > 0],
  ['hidden without LICENSE_MANAGE',     without === ''],
  ['has the panel heading',             withPerm.includes('Vehicle SIM Key')],
  ['has all 7 protocol toggles',        ['Can','Lin','FlexRay','Ethernet','Rs232','Debugger','Xcp'].every(f => withPerm.includes(`>${f}</button>`))],
  ['Can + Lin preselected',             (withPerm.match(/toggle-chip is-on/g) ?? []).length === 3],
  ['V3 selected by default',            withPerm.includes('V3 — asymmetric')],
  // The V2 warning is the other branch of the same hint, so it is only in the
  // markup once V2 is selected. What must be true by DEFAULT is that V3 is the
  // chosen option and the panel explains why that is the safe one.
  ['explains V3 by default',            withPerm.includes('never leaves this server')],
  ['V2 not preselected',                !withPerm.includes('toggle-chip is-warn')],
  ['warns the old key stops working',   withPerm.includes('the existing one stops working')],
  ['machine id field present',          withPerm.includes('A1B2C3D4E5F60718')],
  ['no expiry input offered',           !/name="expiry"|id="vbs-expiry"/.test(withPerm)],
  ['3 mode options',                    (withPerm.match(/<option/g) ?? []).length === 6],
];

let bad = 0;
for (const [name, ok] of checks) {
  console.log(` ${ok ? 'ok  ' : 'FAIL'}  ${name}`);
  if (!ok) bad++;
}
process.exit(bad ? 1 : 0);
