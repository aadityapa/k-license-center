import { Navigate, Route, Routes } from 'react-router-dom';
import { RequireAuth } from './auth/RequireAuth';
import { AppLayout } from './layout/AppLayout';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/dashboard/DashboardPage';
import { ProductsListPage } from './pages/products/ProductsListPage';
import { ProductDetailPage } from './pages/products/ProductDetailPage';
import { PlansPage } from './pages/products/PlansPage';
import { CustomersListPage } from './pages/customers/CustomersListPage';
import { CustomerDetailPage } from './pages/customers/CustomerDetailPage';
import { LicensesListPage } from './pages/licenses/LicensesListPage';
import { LicenseDetailPage } from './pages/licenses/LicenseDetailPage';
import { LicenseKeysPage } from './pages/licenses/LicenseKeysPage';
import { ActivationsPage } from './pages/licenses/ActivationsPage';
import { RenewalsPage } from './pages/licenses/RenewalsPage';
import { ApiClientsPage } from './pages/authorization/ApiClientsPage';
import { ApiLogsPage } from './pages/authorization/ApiLogsPage';
import { UsersPage } from './pages/security/UsersPage';
import { RolesPage } from './pages/security/RolesPage';
import { AuditLogsPage } from './pages/audit/AuditLogsPage';
import { ApprovalsPage } from './pages/approvals/ApprovalsPage';
import { LicenseRequestsPage } from './pages/requests/LicenseRequestsPage';
import { EmailOutboxPage } from './pages/requests/EmailOutboxPage';
import { RequestLicensePage } from './pages/public/RequestLicensePage';
import { CompleteRequestPage } from './pages/public/CompleteRequestPage';
import { SettingsPage } from './pages/SettingsPage';

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* Public, unauthenticated: the requester is not a user of this console,
          so these sit outside RequireAuth and outside the app shell. */}
      <Route path="/request" element={<RequestLicensePage />} />
      <Route path="/request/:token" element={<CompleteRequestPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/products" element={<ProductsListPage />} />
          <Route path="/products/:id" element={<ProductDetailPage />} />
          <Route path="/plans" element={<PlansPage />} />
          <Route path="/customers" element={<CustomersListPage />} />
          <Route path="/customers/:id" element={<CustomerDetailPage />} />
          <Route path="/licenses" element={<LicensesListPage />} />
          <Route path="/licenses/:id" element={<LicenseDetailPage />} />
          <Route path="/license-keys" element={<LicenseKeysPage />} />
          <Route path="/activations" element={<ActivationsPage />} />
          <Route path="/renewals" element={<RenewalsPage />} />
          <Route path="/api-clients" element={<ApiClientsPage />} />
          <Route path="/api-logs" element={<ApiLogsPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/roles" element={<RolesPage />} />
          <Route path="/license-requests" element={<LicenseRequestsPage />} />
          <Route path="/email-outbox" element={<EmailOutboxPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/audit-logs" element={<AuditLogsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}
