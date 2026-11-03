const B=process.env.API_URL||'http://127.0.0.1:3001';
let fails=0;
async function login(u){const r=await fetch(B+'/api/v1/auth/login',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({username:u,password:'Pass@100%'})});const j=await r.json();if(!j.data?.token)throw new Error('login '+u+' '+JSON.stringify(j));return j.data.token;}
const tok=await login('admin');
async function get(p,t=tok){const r=await fetch(B+p,{headers:{authorization:'Bearer '+t}});const txt=await r.text();if(r.status>=400){fails++;console.log('FAIL',r.status,p,txt.slice(0,200));}else console.log('ok',r.status,p);try{return JSON.parse(txt)}catch{return txt}}
const paths=['/health/db','/api/v1/auth/me',
'/api/v1/admin/dashboard','/api/v1/admin/products','/api/v1/admin/products?sort=-productName','/api/v1/admin/products/1',
'/api/v1/admin/plans','/api/v1/admin/plans?productId=1&sort=durationDays','/api/v1/admin/plans/1',
'/api/v1/admin/customers','/api/v1/admin/customers?q=acme','/api/v1/admin/customers?createdFrom=2020-01-01&createdTo=2030-01-01&sort=-companyName','/api/v1/admin/customers/1','/api/v1/admin/customers/1/licenses',
'/api/v1/admin/licenses','/api/v1/admin/licenses?q=LIC-2026-100001','/api/v1/admin/licenses?q=acme&status=ACTIVE','/api/v1/admin/licenses?expiryFrom=2020-01-01&expiryTo=2030-01-01&createdFrom=2020-01-01&createdTo=2030-12-31&sort=-expiryDate','/api/v1/admin/licenses/1',
'/api/v1/admin/activations','/api/v1/admin/activations?q=x','/api/v1/admin/renewals','/api/v1/admin/renewals?q=x&from=2020-01-01&to=2030-01-01',
'/api/v1/admin/license-keys','/api/v1/admin/license-requests','/api/v1/admin/license-requests?q=a&createdFrom=2020-01-01&createdTo=2030-01-01',
'/api/v1/admin/email-outbox','/api/v1/admin/users','/api/v1/admin/roles','/api/v1/admin/permissions','/api/v1/admin/api-clients',
'/api/v1/admin/audit-logs','/api/v1/admin/audit-logs?from=2020-01-01&to=2030-01-01','/api/v1/admin/api-logs','/api/v1/admin/api-logs?q=x&from=2020-01-01&to=2030-01-01',
'/api/v1/admin/settings','/api/v1/admin/change-requests','/api/v1/admin/notifications','/api/v1/public/catalogue'];
for(const p of paths) await get(p);
// sort sweep on licenses/customers/etc
for (const [p,keys] of [['/api/v1/admin/licenses',['licenseNo','status','expiryDate','createdAt','customerName']],['/api/v1/admin/customers',['customerCode','companyName','createdAt']]]) for(const k of keys){ await get(p+'?sort=-'+k);}
for(const u of ['maker','checker','viewer']){const t=await login(u);await get('/api/v1/admin/dashboard',t);await get('/api/v1/auth/me',t);}
console.log('FAILS',fails);
