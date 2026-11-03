/** Server-renders LicFilePanel to prove it mounts, gates on permission, and shows its controls. */
import { renderToStaticMarkup } from 'react-dom/server';
import { LicFilePanel } from '../src/pages/licenses/LicFilePanel';
import { AuthContext } from '../src/auth/AuthContext';
import type { LicenseDetail } from '../src/types';

const licence = {
  licenseId: 9, licenseNo: 'LIC-2026-100009', customerId: 1, productId: 2, planId: 7,
  status: 'ACTIVE', maxActivations: 3, currentActivations: 1, keyFormat: 'LIC_FILE', productCode: 'KFLASH',
} as unknown as LicenseDetail;

function render(perms: string[]) {
  const auth = { user: { userId: 1, username: 'u', permissions: perms, roles: [] }, hasPermission: (p: string) => perms.includes(p),
    hasAnyPermission: () => true, login: async () => {}, logout: () => {}, loading: false, error: null } as never;
  return renderToStaticMarkup(
    <AuthContext.Provider value={auth}><LicFilePanel license={licence} onChanged={() => {}} onPending={() => {}} /></AuthContext.Provider>);
}
const yes = render(['LICENSE_MANAGE']);
const checks: Array<[string, boolean]> = [
  ['renders for LICENSE_MANAGE', yes.includes('Issue Activation File')],
  ['hidden without LICENSE_MANAGE', render(['LICENSE_VIEW']) === ''],
  ['file input accepts .lic', /type="file"[^>]*accept="\.lic/.test(yes)],
  ['issue button disabled until a file is chosen', /<button[^>]*disabled=""[^>]*>.*Issue signed file/.test(yes)],
  ['shows free seats (2 of 3)', yes.includes('2 of 3 seats free')],
];
let bad = 0;
for (const [n, ok] of checks) { console.log(` ${ok ? 'ok  ' : 'FAIL'}  ${n}`); if (!ok) bad++; }
process.exit(bad ? 1 : 0);
