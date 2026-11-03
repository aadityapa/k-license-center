// Domain types mirroring the API payloads (camelCase projections of the PostgreSQL schema).

export type EntityStatus = 'ACTIVE' | 'INACTIVE';
export type LicenseStatus = 'DRAFT' | 'ACTIVE' | 'SUSPENDED' | 'EXPIRED' | 'REVOKED' | 'CANCELLED';
export type KeyStatus = 'ACTIVE' | 'REVOKED';
export type ActivationStatus = 'ACTIVE' | 'DEACTIVATED';
export type UserStatus = 'ACTIVE' | 'LOCKED' | 'INACTIVE';
export type ClientStatus = 'ACTIVE' | 'REVOKED';

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  /** Distinct product versions across the whole table — products list only. */
  versions?: string[];
  /**
   * Endpoint-specific aggregate. Activations return fleet health; renewals return
   * year-to-date totals. Every field is optional so one shape serves both.
   */
  summary?: {
    total?: number;
    active?: number;
    healthy?: number;
    stale?: number;
    healthPercent?: number;
    ytdCount?: number;
    ytdAmount?: number;
    pending?: number;
  };
}

export interface Product {
  productId: number;
  productCode: string;
  productName: string;
  keyPrefix: string;
  description?: string | null;
  version?: string | null;
  status: EntityStatus;
  /**
   * How a licence for this product is delivered:
   *   KSTK_KEY — typed PREF-XXXX-XXXX-XXXX key
   *   LIC_FILE — hardware-bound .lic file
   *   VBS_KEY  — Vehicle SIM signed key string carrying the whole grant
   * The licence screens branch on this instead of on the product code.
   */
  keyFormat?: KeyFormat;
  usesLicFile?: 'Y' | 'N';
  createdAt?: string;
  updatedAt?: string;
}

export type KeyFormat = 'KSTK_KEY' | 'LIC_FILE' | 'VBS_KEY';

/** Vehicle SIM grant, mirroring LicenseMode / LicenseEdition in the app. */
export const VBS_MODES = [
  { value: 0, label: 'Node-locked', hint: 'Perpetual, tied to one machine' },
  { value: 1, label: 'Subscription', hint: 'Expires with the licence' },
  { value: 2, label: 'Evaluation', hint: 'Time-limited trial' },
] as const;

export const VBS_EDITIONS = [
  { value: 1, label: 'Trial' },
  { value: 2, label: 'Pro' },
  { value: 3, label: 'Enterprise' },
] as const;

/** Per-protocol entitlements encoded in a Vehicle SIM key. */
export const VBS_FEATURES = ['Can', 'Lin', 'FlexRay', 'Ethernet', 'Rs232', 'Debugger', 'Xcp'] as const;

export type VbsFeature = (typeof VBS_FEATURES)[number];

export interface IssueVbsKeyBody {
  mode: number;
  edition: number;
  features: VbsFeature[];
  machineId?: string;
  licensedTo?: string;
  keyVersion: 'V2' | 'V3';
}

export interface IssuedVbsKey {
  licenseId: number;
  licenseKey: string;
  keyVersion: 'V2' | 'V3';
  licenceNo: string;
  licensedTo: string;
  expiry: string | null;
}

export interface ProductPlan {
  planId: number;
  productId: number;
  productCode?: string;
  productName?: string;
  planCode: string;
  planName: string;
  durationDays: number | null;
  isLifetime: boolean;
  price: number | null;
  currency: string;
  maxActivations: number;
  maxUsers?: number | null;
  maxBranches?: number | null;
  status: EntityStatus;
  createdAt?: string;
  updatedAt?: string;
}

export interface Customer {
  customerId: number;
  customerCode: string;
  companyName: string;
  contactPerson?: string | null;
  email?: string | null;
  mobile?: string | null;
  whatsapp?: string | null;
  addressLine1?: string | null;
  addressLine2?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  gstNumber?: string | null;
  status: EntityStatus;
  createdAt?: string;
  updatedAt?: string;
}

export interface License {
  licenseId: number;
  licenseNo: string;
  /** Random, unguessable serial a customer quotes to support, e.g. SN-VSIM-7F3A-K9D2. */
  serialNo?: string;
  amount?: number | null;
  currency?: string;
  /** Globally unique id (UUID v4) for other systems to reference this licence. */
  licenseUid?: string;
  customerId: number;
  productId: number;
  planId: number;
  status: LicenseStatus;
  startDate?: string | null;
  expiryDate?: string | null; // null = lifetime
  maxActivations: number;
  maxUsers?: number | null;
  maxBranches?: number | null;
  currentActivations: number;
  autoRenewal?: boolean;
  notes?: string | null;
  createdAt?: string;
  updatedAt?: string;
  // denormalized display fields the API joins in for lists / detail
  customerName?: string;
  customerCode?: string;
  productName?: string;
  productCode?: string;
  /** How this licence is delivered. Drives which key UI the detail page shows. */
  keyFormat?: KeyFormat;
  planName?: string;
  planCode?: string;
  licenseKey?: string | null; // current ACTIVE key when included on detail
}

export interface LicenseKey {
  keyId: number;
  licenseId: number;
  licenseKey: string;
  status: KeyStatus;
  generatedAt?: string;
  generatedBy?: string | number | null;
  revokedAt?: string | null;
  licenseNo?: string;
  customerName?: string;
  productName?: string;
  productCode?: string;
}

export interface Activation {
  activationId: number;
  licenseId: number;
  installationId: string;
  deviceId?: string | null;
  machineFingerprint?: string | null;
  deviceName?: string | null;
  osInfo?: string | null;
  appVersion?: string | null;
  ipAddress?: string | null;
  status: ActivationStatus;
  activatedAt?: string;
  lastHeartbeatAt?: string | null;
  deactivatedAt?: string | null;
  deactivatedBy?: string | number | null;
  deactivationReason?: string | null;
  /** Set when a signed .lic was issued to this machine; it can be downloaded again. */
  licFileIssuedAt?: string | null;
  licenseNo?: string;
  customerName?: string;
  productName?: string;
  productCode?: string;
}

export interface Renewal {
  renewalId: number;
  licenseId: number;
  prevPlanId?: number | null;
  newPlanId?: number | null;
  prevPlanName?: string | null;
  newPlanName?: string | null;
  prevExpiryDate?: string | null;
  newExpiryDate?: string | null;
  renewalDate?: string;
  amount?: number | null;
  currency?: string | null;
  paymentRef?: string | null;
  performedBy?: string | number | null;
  performedByName?: string | null;
  notes?: string | null;
  licenseNo?: string;
  customerName?: string;
  productName?: string;
}

export interface LicenseHistoryEntry {
  historyId: number;
  licenseId: number;
  oldStatus?: LicenseStatus | null;
  newStatus: LicenseStatus;
  changedAt: string;
  changedBy?: string | number | null;
  reason?: string | null;
  requestId?: string | null;
}

/** A computer the licence is bound to / was requested for, with the hardware the app reported. */
export interface LicenseComputer {
  machineId: string;
  boundToKey: boolean;
  macAddress?: string | null;
  cpuId?: string | null;
  biosSerial?: string | null;
  motherboardId?: string | null;
  hostName?: string | null;
  osName?: string | null;
  appVersion?: string | null;
  requestId?: number | null;
  requestedAt?: string | null;
}

export interface LicenseDetail extends License {
  vbsMachineId?: string | null;
  computers?: LicenseComputer[];
  keys?: LicenseKey[];
  activations?: Activation[];
  renewals?: Renewal[];
  history?: LicenseHistoryEntry[];
}

export interface CustomerLicenses {
  licenses: License[];
  keys?: LicenseKey[];
  activations?: Activation[];
  renewals?: Renewal[];
  history?: LicenseHistoryEntry[];
}

export interface ApiClient {
  clientId: number;
  productId: number;
  productName?: string;
  productCode?: string;
  clientKey: string;
  name: string;
  status: ClientStatus;
  lastUsedAt?: string | null;
  createdAt?: string;
}

export interface ApiClientCreated extends ApiClient {
  clientSecret: string; // returned exactly once at creation
}

export interface ApiRequestLog {
  logId: number;
  requestId?: string | null;
  clientId?: number | null;
  clientName?: string | null;
  clientKey?: string | null;
  endpoint: string;
  method: string;
  licenseKeyHash?: string | null;
  resultCode?: string | null;
  httpStatus: number;
  ipAddress?: string | null;
  durationMs?: number | null;
  createdAt: string;
}

export interface AuditLog {
  auditId: number;
  userId?: number | null;
  actor?: string | null;
  action: string;
  entityType?: string | null;
  entityId?: number | string | null;
  requestId?: string | null;
  ipAddress?: string | null;
  beforeState?: string | Record<string, unknown> | null;
  afterState?: string | Record<string, unknown> | null;
  createdAt: string;
}

export interface Role {
  roleId: number;
  roleCode: string;
  roleName?: string | null;
  description?: string | null;
  permissions?: string[];
}

export interface Permission {
  permId: number;
  permCode: string;
  description?: string | null;
}

export interface AdminUser {
  userId: number;
  username: string;
  email?: string | null;
  fullName?: string | null;
  status: UserStatus;
  lastLoginAt?: string | null;
  roles?: Role[];
  roleIds?: number[];
  createdAt?: string;
}

export interface AuthUser {
  userId: number;
  username: string;
  fullName?: string | null;
  email?: string | null;
  roles?: string[];
  permissions: string[];
}

export interface LoginResponse {
  token: string;
  user: AuthUser;
}

export interface Setting {
  settingKey: string;
  settingValue: string;
  description?: string | null;
  updatedAt?: string | null;
}

export interface DashboardProductStats {
  productId: number;
  productCode: string;
  productName: string;
  activeLicenses: number;
  expiringSoon: number;
  expiredLicenses: number;
  activations: number;
  totalLicenses?: number;
}

export interface DashboardStatusCount {
  status: string;
  count: number;
}

export interface DashboardData {
  totals: {
    products: number;
    customers: number;
    licenses: number;
    activeLicenses: number;
    trialLicenses: number;
    expiringSoon: number;
    expiredLicenses: number;
    suspendedLicenses: number;
    revokedLicenses: number;
    totalActivations: number;
  };
  /** 14-day daily counts ending today, oldest first. Real counts; days with none are 0. */
  trends?: {
    licensesCreated: number[];
    activations: number[];
  };
  /**
   * Posture computed server-side from signals the system actually records
   * (rejected API calls, locked accounts, revoked/suspended licences).
   */
  security?: {
    score: number;
    posture: 'VERIFIED' | 'ELEVATED' | 'AT_RISK';
    requests24h: number;
    signals: Array<{ key: string; label: string; count: number }>;
  };
  licensesByStatus: DashboardStatusCount[];
  products: DashboardProductStats[];
  recentLicenses: License[];
  recentActivations: Activation[];
  upcomingRenewals: License[];
  recentAuditEvents: AuditLog[];
}

/* ---------- Maker-checker governance ---------- */

export type ChangeRequestStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELLED' | 'FAILED';

export type ChangeEntityType =
  | 'CUSTOMER'
  | 'PRODUCT'
  | 'PLAN'
  | 'LICENSE'
  | 'ACTIVATION'
  | 'API_CLIENT'
  | 'USER'
  | 'ROLE'
  | 'SETTING';

/** List-row projection of a change request. */
export interface ChangeRequest {
  requestId: number;
  entityType: ChangeEntityType | string;
  entityId?: number | null;
  operation: string;
  summary: string;
  status: ChangeRequestStatus;
  requestedBy: number;
  requestedAt: string;
  requestNote?: string | null;
  reviewedBy?: number | null;
  reviewedAt?: string | null;
  reviewComment?: string | null;
  appliedAt?: string | null;
  errorMessage?: string | null;
  requestedByName?: string | null;
  reviewedByName?: string | null;
}

/** Single-request view: adds the payload and the reviewer's diff base. */
export interface ChangeRequestDetail extends ChangeRequest {
  payload: Record<string, unknown> | null;
  beforeState: Record<string, unknown> | null;
}

/** The change-requests list adds a global pending count for the nav badge. */
export interface ChangeRequestPage extends Paged<ChangeRequest> {
  pendingTotal: number;
}

/* ---------- Self-service licence requests ---------- */

export type LicenseRequestStatus =
  | 'INVITED'
  | 'SUBMITTED'
  | 'UNDER_REVIEW'
  | 'AUTO_ISSUED'
  | 'APPROVED'
  | 'REJECTED'
  | 'EXPIRED';

/** PUBLIC = the requester started it themselves; INVITE = staff invited them. */
export type LicenseRequestSource = 'PUBLIC' | 'INVITE';

/** List-row projection of a licence request. */
export interface LicenseRequest {
  requestId: number;
  email: string;
  status: LicenseRequestStatus;
  source: LicenseRequestSource;
  productId?: number | null;
  planId?: number | null;
  companyName?: string | null;
  domainName?: string | null;
  contactPerson?: string | null;
  contactPhone?: string | null;
  customerId?: number | null;
  licenseId?: number | null;
  invitedBy?: number | null;
  reviewedBy?: number | null;
  reviewedAt?: string | null;
  reviewComment?: string | null;
  createdAt?: string;
  submittedAt?: string | null;
  issuedAt?: string | null;
  tokenExpiresAt?: string | null;
  // denormalized display fields the API joins in
  productCode?: string | null;
  productName?: string | null;
  /** How the product is delivered; VBS_KEY requests show the grant picker on approval. */
  keyFormat?: KeyFormat | null;
  planCode?: string | null;
  planName?: string | null;
  customerName?: string | null;
  licenseNo?: string | null;
  /** Installation identity: hardware fingerprint for .lic products, Machine ID for Vehicle SIM. */
  hwFingerprint?: string | null;
  /** Raw request payload the product posted (a .lic file, or a Vehicle SIM request). */
  licRequestJson?: string | null;
  /** Hardware identity, the same fields the Karnex .lic file carries. */
  macAddress?: string | null;
  cpuId?: string | null;
  biosSerial?: string | null;
  motherboardId?: string | null;
  hostName?: string | null;
  appVersion?: string | null;
}

/** The reviewer's grant when approving a request raised by the Vehicle SIM app. */
export interface ApproveRequestBody {
  comment?: string;
  planCode: string;
  amount: number;
  vbs?: {
    mode?: number;
    edition?: number;
    features?: VbsFeature[];
    keyVersion?: 'V2' | 'V3';
  };
}

/**
 * Single-request view: adds everything the requester submitted plus the
 * outcome. The request token is never returned by the API, by design.
 */
export interface LicenseRequestDetail extends LicenseRequest {
  /** Set when this computer already had a trial of the product (one trial per computer). */
  priorTrial?: { licenseNo: string; licenseId: number } | null;
  osName?: string | null;
  osVersion?: string | null;
  hostName?: string | null;
  appVersion?: string | null;
  intendedInstalls?: number | null;
  intendedUsers?: number | null;
  intendedBranches?: number | null;
  notes?: string | null;
  ipAddress?: string | null;
  customerCode?: string | null;
  licenseStatus?: LicenseStatus | null;
  expiryDate?: string | null;
  keyStatus?: KeyStatus | null;
  invitedByName?: string | null;
  reviewedByName?: string | null;
}

export type EmailStatus = 'QUEUED' | 'SENT' | 'FAILED' | 'SKIPPED';

/** A row of EMAIL_OUTBOX. `bodyText` is only present on the detail endpoint. */
export interface EmailOutboxItem {
  emailId: number;
  toAddress: string;
  subject: string;
  bodyText?: string | null;
  template?: string | null;
  relatedType?: string | null;
  relatedId?: number | null;
  status: EmailStatus;
  attempts?: number | null;
  errorMessage?: string | null;
  createdAt?: string;
  sentAt?: string | null;
}

/* ---------- Public (unauthenticated) request flow ---------- */

export interface PublicCataloguePlan {
  planCode: string;
  planName: string;
  durationDays: number | null;
  isLifetime: boolean;
}

export interface PublicCatalogueProduct {
  productId: number;
  productCode: string;
  productName: string;
  plans: PublicCataloguePlan[];
}

export interface PublicCatalogue {
  products: PublicCatalogueProduct[];
}

/** Plan as offered on the emailed form — includes the entitlement caps. */
export interface PublicFormPlan extends PublicCataloguePlan {
  maxActivations: number;
  maxUsers: number | null;
  maxBranches: number | null;
}

/** The form behind a single-use token. */
export interface PublicRequestForm {
  email: string;
  productCode: string;
  productName: string;
  expiresAt: string | null;
  plans: PublicFormPlan[];
}

/** Body of the public form submission. */
export interface PublicRequestFormBody {
  companyName: string;
  domainName?: string;
  contactPerson: string;
  contactPhone: string;
  planCode: string;
  osName?: string;
  osVersion?: string;
  hostName?: string;
  appVersion?: string;
  intendedInstalls?: number;
  intendedUsers?: number;
  intendedBranches?: number;
  notes?: string;
}

/** 202 from starting a request — deliberately says nothing about the address. */
export interface PublicRequestStarted {
  submitted: boolean;
  message: string;
  requestId: number;
}

/**
 * Outcome of submitting the form. A trial is issued immediately (the key itself
 * is emailed, never returned here); anything else goes to human review.
 */
export type PublicRequestOutcome =
  | { issued: true; message: string; licenseNo: string; expiryDate: string | null }
  | { issued: false; message: string };

export interface ListParams {
  page?: number;
  pageSize?: number;
  sort?: string;
  q?: string;
  [key: string]: string | number | boolean | undefined;
}

/** A row from the portal bell. */
export interface NotificationItem {
  eventId: number;
  eventType: string;
  entityType: string;
  entityId?: number | null;
  customerId?: number | null;
  payload?: unknown;
  status: 'PENDING' | 'SENT' | 'FAILED' | 'SKIPPED';
  createdAt: string;
}

/** A .lic issued by hand from an uploaded request. */
export interface IssuedLicFile {
  licenseId: number;
  activationId: number;
  licFile: string;
  fileName: string;
  fingerprint: string;
  reissued: boolean;
}

/* ---------- Dashboard overview (GET /admin/dashboard/overview) ---------- */
export interface OverviewKpi { value: number; previous: number; changePct: number | null; periodNew?: number }
export interface OverviewPoint { date: string; revenue: number; licenses: number; activations: number }
export interface OverviewProduct { productCode: string; productName: string; licenses: number; revenue: number; active: number; total: number }
export interface OverviewMonth { month: string; label: string; newCustomers: number; totalCustomers: number }
export interface OverviewAction { key: string; label: string; count: number; to: string }
export interface DashboardOverview {
  period: { days: number; from: string; to: string; previousFrom: string };
  kpis: { revenue: OverviewKpi; licenses: OverviewKpi; activeCustomers: OverviewKpi; activations: OverviewKpi };
  series: OverviewPoint[];
  products: OverviewProduct[];
  customerGrowth: OverviewMonth[];
  licenseStatus: { total: number; active: number; draft: number; suspended: number; expired: number; revoked: number; cancelled: number; expiringSoon: number };
  health: { apiSuccessPct: number; authSuccessPct: number; database: string; requests24h: number; securityAlerts: number; failedActivations24h: number; pendingRequests: number; clockAlerts7d?: number };
  pendingActions: OverviewAction[];
  topCustomers: Array<{ customerId: number; customerName: string; seats: number; licenses: number }>;
  recentLicenses: Array<{ licenseId: number; licenseNo: string; customerId: number; customerName: string; productCode: string; productName: string; planName: string; status: string; createdAt: string | null; expiryDate: string | null }>;
  recentActivations: Array<{ activationId: number; licenseId: number; licenseNo: string; productName: string; customerName: string; deviceName: string; osInfo: string | null; status: string; activatedAt: string | null }>;
  recentCustomers: Array<{ customerId: number; companyName: string; contactPerson: string | null; email: string | null; status: string; createdAt: string | null; activeLicenses: number }>;
}
