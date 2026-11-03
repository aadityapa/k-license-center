import { http, publicHttp } from './http';
import type { PendingApproval } from './http';
import { downloadFile } from './http';
import type {
  Activation,
  AdminUser,
  NotificationItem,
  ApproveRequestBody,
  ApiClient,
  ApiClientCreated,
  ApiRequestLog,
  AuditLog,
  AuthUser,
  ChangeRequest,
  ChangeRequestDetail,
  ChangeRequestPage,
  ChangeRequestStatus,
  Customer,
  CustomerLicenses,
  DashboardData,
  DashboardOverview,
  EmailOutboxItem,
  EmailStatus,
  IssuedLicFile,
  IssuedVbsKey,
  IssueVbsKeyBody,
  License,
  LicenseRequest,
  LicenseRequestDetail,
  LicenseRequestSource,
  LicenseRequestStatus,
  LicenseDetail,
  LicenseKey,
  ListParams,
  LoginResponse,
  Paged,
  Permission,
  Product,
  ProductPlan,
  PublicCatalogue,
  PublicRequestForm,
  PublicRequestFormBody,
  PublicRequestOutcome,
  PublicRequestStarted,
  Renewal,
  Role,
  Setting,
} from '../../types';

// ---- Auth ----
export const authApi = {
  login: (username: string, password: string) =>
    http.post<LoginResponse>('/auth/login', { username, password }),
  logout: () => http.post<void>('/auth/logout'),
  me: () => http.get<AuthUser>('/auth/me'),
};

// ---- Dashboard ----
export const dashboardApi = {
  get: () => http.get<DashboardData>('/admin/dashboard'),
  overview: (days: number) => http.get<DashboardOverview>('/admin/dashboard/overview', { days }),
};

// ---- Products / Plans ----
export const productsApi = {
  remove: (id: number) => http.delete<{ deleted: true } | PendingApproval>(`/admin/products/${id}`),
  list: (params?: ListParams) => http.get<Paged<Product>>('/admin/products', params),
  get: (id: number) => http.get<Product>(`/admin/products/${id}`),
  create: (body: Partial<Product>) => http.post<Product | PendingApproval>('/admin/products', body),
  update: (id: number, body: Partial<Product>) =>
    http.put<Product | PendingApproval>(`/admin/products/${id}`, body),
};

export const plansApi = {
  list: (params?: ListParams) => http.get<Paged<ProductPlan>>('/admin/plans', params),
  get: (id: number) => http.get<ProductPlan>(`/admin/plans/${id}`),
  create: (body: Partial<ProductPlan>) => http.post<ProductPlan | PendingApproval>('/admin/plans', body),
  update: (id: number, body: Partial<ProductPlan>) =>
    http.put<ProductPlan | PendingApproval>(`/admin/plans/${id}`, body),
  /** Refused (409 PLAN_IN_USE) when any licence uses the plan — archive it instead. */
  remove: (id: number) => http.delete<{ planId: number; deleted: true } | PendingApproval>(`/admin/plans/${id}`),
};

// ---- Customers ----
export const customersApi = {
  list: (params?: ListParams) => http.get<Paged<Customer>>('/admin/customers', params),
  get: (id: number) => http.get<Customer>(`/admin/customers/${id}`),
  create: (body: Partial<Customer>) => http.post<Customer | PendingApproval>('/admin/customers', body),
  update: (id: number, body: Partial<Customer>) =>
    http.put<Customer | PendingApproval>(`/admin/customers/${id}`, body),
  licenses: (id: number) => http.get<CustomerLicenses>(`/admin/customers/${id}/licenses`),
  /** Refused (409 CUSTOMER_HAS_LICENSES) when the customer holds any licence. */
  remove: (id: number) =>
    http.delete<{ customerId: number; deleted: true } | PendingApproval>(`/admin/customers/${id}`),
};

// ---- Licenses ----
export interface CreateLicenseBody {
  customerId: number;
  productId: number;
  planId: number;
  /** Amount charged (compulsory; 0 for a free licence). */
  amount: number;
  notes?: string;
  autoRenewal?: boolean;
}

export interface RenewLicenseBody {
  planId?: number;
  amount?: number;
  paymentRef?: string;
  notes?: string;
}

export const licensesApi = {
  remove: (id: number) => http.delete<{ deleted: true } | PendingApproval>(`/admin/licenses/${id}`),
  list: (params?: ListParams) => http.get<Paged<License>>('/admin/licenses', params),
  get: (id: number) => http.get<LicenseDetail>(`/admin/licenses/${id}`),
  create: (body: CreateLicenseBody) => http.post<License | PendingApproval>('/admin/licenses', body),
  activate: (id: number) => http.post<LicenseDetail | PendingApproval>(`/admin/licenses/${id}/activate`),
  renew: (id: number, body: RenewLicenseBody) =>
    http.post<LicenseDetail | PendingApproval>(`/admin/licenses/${id}/renew`, body),
  suspend: (id: number, reason: string) =>
    http.post<LicenseDetail | PendingApproval>(`/admin/licenses/${id}/suspend`, { reason }),
  reactivate: (id: number, reason?: string) =>
    http.post<LicenseDetail | PendingApproval>(
      `/admin/licenses/${id}/reactivate`,
      reason ? { reason } : undefined,
    ),
  revoke: (id: number, reason: string) =>
    http.post<LicenseDetail | PendingApproval>(`/admin/licenses/${id}/revoke`, { reason }),
  regenerateKey: (id: number, reason: string) =>
    http.post<{ licenseKey: string } | PendingApproval>(`/admin/licenses/${id}/regenerate-key`, { reason }),
  /** KStack/KFlash: sign an uploaded .lic request for a machine that cannot reach the portal. */
  issueLicFile: (id: number, licFile: string) =>
    http.post<IssuedLicFile | PendingApproval>(`/admin/licenses/${id}/issue-lic-file`, { licFile }),
  /** Vehicle SIM only: mints a key carrying mode, edition and per-protocol features. */
  issueVbsKey: (id: number, body: IssueVbsKeyBody) =>
    http.post<IssuedVbsKey | PendingApproval>(`/admin/licenses/${id}/issue-vbs-key`, body),
};

export const licenseKeysApi = {
  list: (params?: ListParams) => http.get<Paged<LicenseKey>>('/admin/license-keys', params),
  /** Revoked keys only (409 KEY_ACTIVE for the live key). */
  remove: (id: number) => http.delete<{ keyId: number; deleted: true } | PendingApproval>(`/admin/license-keys/${id}`),
};

export const activationsApi = {
  remove: (id: number) => http.delete<{ deleted: true } | PendingApproval>(`/admin/activations/${id}`),
  list: (params?: ListParams) => http.get<Paged<Activation>>('/admin/activations', params),
  deactivate: (id: number, reason: string) =>
    http.post<Activation | PendingApproval>(`/admin/activations/${id}/deactivate`, { reason }),
  /** The signed .lic issued to this machine, saved by the browser. */
  downloadLicFile: (id: number) => downloadFile(`/admin/activations/${id}/lic-file`, `activation-${id}.lic`),
};

export const renewalsApi = {
  remove: (id: number) => http.delete<{ deleted: true } | PendingApproval>(`/admin/renewals/${id}`),
  list: (params?: ListParams) => http.get<Paged<Renewal>>('/admin/renewals', params),
};

// ---- API clients / logs ----
export const apiClientsApi = {
  remove: (id: number) => http.delete<{ deleted: true } | PendingApproval>(`/admin/api-clients/${id}`),
  list: (params?: ListParams) => http.get<Paged<ApiClient>>('/admin/api-clients', params),
  create: (body: { productId: number; name: string }) =>
    http.post<ApiClientCreated>('/admin/api-clients', body),
  revoke: (id: number, reason?: string) =>
    http.post<ApiClient>(`/admin/api-clients/${id}/revoke`, reason ? { reason } : undefined),
};

export const apiLogsApi = {
  list: (params?: ListParams) => http.get<Paged<ApiRequestLog>>('/admin/api-logs', params),
};

// ---- Users / Roles ----
export const usersApi = {
  list: (params?: ListParams) => http.get<Paged<AdminUser>>('/admin/users', params),
  create: (body: Partial<AdminUser> & { password?: string; roleIds?: number[] }) =>
    http.post<AdminUser>('/admin/users', body),
  update: (id: number, body: Partial<AdminUser> & { password?: string }) =>
    http.put<AdminUser>(`/admin/users/${id}`, body),
  setRoles: (id: number, roleIds: number[]) => http.put<AdminUser>(`/admin/users/${id}/roles`, { roleIds }),
  remove: (id: number) => http.delete<{ userId: number; deleted: true }>(`/admin/users/${id}`),
};

export const rolesApi = {
  list: () => http.get<Role[] | Paged<Role>>('/admin/roles'),
  permissions: () => http.get<Permission[] | Paged<Permission>>('/admin/permissions'),
  setPermissions: (roleId: number, permissions: string[]) =>
    http.put<Role>(`/admin/roles/${roleId}/permissions`, { permissions }),
};

// ---- Audit ----
export const auditApi = {
  list: (params?: ListParams) => http.get<Paged<AuditLog>>('/admin/audit-logs', params),
};

// ---- Settings ----
export const settingsApi = {
  list: () => http.get<Setting[] | Paged<Setting>>('/admin/settings'),
  // Backend expects a { settings: { key: value } } map.
  update: (settings: Array<{ settingKey: string; settingValue: string }>) =>
    http.put<Setting[] | Paged<Setting> | PendingApproval>('/admin/settings', {
      settings: Object.fromEntries(settings.map((s) => [s.settingKey, s.settingValue])),
    }),
};

// ---- Change requests (maker-checker) ----
export interface ChangeRequestListParams extends ListParams {
  status?: ChangeRequestStatus;
  entityType?: string;
  /** "1" scopes the list to the caller's own submissions. */
  mine?: '1';
}

export const changeRequestsApi = {
  remove: (id: number) => http.delete<{ deleted: true } | PendingApproval>(`/admin/change-requests/${id}`),
  list: (params?: ChangeRequestListParams) =>
    http.get<ChangeRequestPage>('/admin/change-requests', params),
  get: (id: number) => http.get<ChangeRequestDetail>(`/admin/change-requests/${id}`),
  approve: (id: number, comment?: string) =>
    http.post<{ requestId: number; status: ChangeRequest['status']; result?: unknown }>(
      `/admin/change-requests/${id}/approve`,
      comment ? { comment } : {},
    ),
  reject: (id: number, comment: string) =>
    http.post<{ requestId: number; status: ChangeRequest['status'] }>(
      `/admin/change-requests/${id}/reject`,
      { comment },
    ),
  cancel: (id: number) =>
    http.post<{ requestId: number; status: ChangeRequest['status'] }>(
      `/admin/change-requests/${id}/cancel`,
    ),
};

// ---- Licence requests (admin side of the self-service flow) ----
export interface LicenseRequestListParams extends ListParams {
  status?: LicenseRequestStatus;
  source?: LicenseRequestSource;
  productId?: number;
  /** YYYY-MM-DD */
  createdFrom?: string;
  createdTo?: string;
}

export interface InviteResult {
  requestId: number;
  email: string;
  status: LicenseRequestStatus;
  expiresHours: number;
  message: string;
}

export interface ApproveRequestResult {
  requestId: number;
  status: LicenseRequestStatus;
  licenseId: number;
  licenseNo: string;
  customerId: number;
  expiryDate: string | null;
  message: string;
}

export interface RejectRequestResult {
  requestId: number;
  status: LicenseRequestStatus;
  message: string;
}

export interface ResendInviteResult {
  requestId: number;
  status: LicenseRequestStatus;
  expiresHours: number;
  message: string;
}

export const licenseRequestsApi = {
  remove: (id: number) => http.delete<{ deleted: true } | PendingApproval>(`/admin/license-requests/${id}`),
  list: (params?: LicenseRequestListParams) =>
    http.get<Paged<LicenseRequest>>('/admin/license-requests', params),
  get: (id: number) => http.get<LicenseRequestDetail>(`/admin/license-requests/${id}`),
  invite: (body: { email: string; productCode: string; planCode?: string }) =>
    http.post<InviteResult>('/admin/license-requests/invite', body),
  approve: (id: number, body: ApproveRequestBody) =>
    http.post<ApproveRequestResult>(`/admin/license-requests/${id}/approve`, body),
  reject: (id: number, comment: string) =>
    http.post<RejectRequestResult>(`/admin/license-requests/${id}/reject`, { comment }),
  resend: (id: number) => http.post<ResendInviteResult>(`/admin/license-requests/${id}/resend`),
};

// ---- Email outbox ----
export interface EmailOutboxListParams extends ListParams {
  status?: EmailStatus;
}

/** Retry is honest about queue-only mode: SKIPPED with delivered = false. */
export interface EmailRetryResult {
  emailId: number;
  delivered: boolean;
  status: EmailStatus;
  message: string;
}

export const emailOutboxApi = {
  remove: (id: number) => http.delete<{ deleted: true } | PendingApproval>(`/admin/email-outbox/${id}`),
  list: (params?: EmailOutboxListParams) => http.get<Paged<EmailOutboxItem>>('/admin/email-outbox', params),
  get: (id: number) => http.get<EmailOutboxItem>(`/admin/email-outbox/${id}`),
  retry: (id: number) => http.post<EmailRetryResult>(`/admin/email-outbox/${id}/retry`),
};

// ---- Public, unauthenticated request flow ----
// These go through publicHttp: no Authorization header, no redirect on 401.
export const publicApi = {
  catalogue: () => publicHttp.get<PublicCatalogue>('/public/catalogue'),
  start: (email: string, productCode: string) =>
    publicHttp.post<PublicRequestStarted>('/public/license-requests', { email, productCode }),
  form: (token: string) =>
    publicHttp.get<PublicRequestForm>(`/public/license-requests/${encodeURIComponent(token)}`),
  submit: (token: string, body: PublicRequestFormBody) =>
    publicHttp.post<PublicRequestOutcome>(
      `/public/license-requests/${encodeURIComponent(token)}`,
      body,
    ),
};

/** Some list-ish endpoints may return either a bare array or a paged envelope. */
export function asItems<T>(data: T[] | Paged<T>): T[] {
  return Array.isArray(data) ? data : data.items;
}

export const notificationsApi = {
  list: (limit = 20) =>
    http.get<{ items: NotificationItem[]; unread: number }>('/admin/notifications', { limit }),
  ack: (eventIds?: number[]) =>
    http.post<{ acknowledged: number }>('/admin/notifications/ack', eventIds ? { eventIds } : {}),
};

/** A computer that changed its clock, and whether it was reactivated. */
export interface ClockAlert {
  eventId: number;
  alertAt: string;
  installationId: string;
  productCode: string | null;
  deviceName: string | null;
  licenseNo: string | null;
  customerName: string | null;
  kind: 'MOVED_BACK' | 'MOVED_FORWARD' | 'WRONG_TIME' | string;
  localTime: string | null;
  referenceTime: string | null;
  deltaSeconds: number | null;
  /** ALLOWED = date moved forward (licence keeps working); BLOCKED = waiting for reactivation. */
  state: 'BLOCKED' | 'RELEASE_SENT' | 'REACTIVATED' | 'ALLOWED';
  reactivatedBy: string | null;
  reactivationRequestedAt: string | null;
  reactivatedAt: string | null;
}

export const clockAlertsApi = {
  list: (days = 30) => http.get<{ items: ClockAlert[]; days: number; serverTime: string }>('/admin/clock-alerts', { days }),
  reactivate: (installationId: string, productCode: string, note?: string) =>
    http.post<{ releaseSent: true } | PendingApproval>('/admin/clock-alerts/reactivate', { installationId, productCode, note }),
};

export const systemApi = {
  /** The licence server's date and time. */
  time: () => http.get<{ serverTime: string; timeZone: string; utcOffsetMinutes: number }>('/admin/system/time'),
};
