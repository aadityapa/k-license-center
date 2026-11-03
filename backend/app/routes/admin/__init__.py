"""/api/v1/admin — every route here requires a signed-in admin (see deps.require / deps.admin_ctx)."""
from fastapi import APIRouter

from . import (
    activations, api_clients, clock_alerts, api_logs, audit_logs, change_requests, customers, dashboard,
    email_outbox, license_keys, license_requests, licenses, notifications, plans, products,
    renewals, roles, settings, users,
)

router = APIRouter()

router.include_router(products.router, prefix="/products")
router.include_router(plans.router, prefix="/plans")
router.include_router(customers.router, prefix="/customers")
router.include_router(licenses.router, prefix="/licenses")
router.include_router(activations.router, prefix="/activations")
router.include_router(renewals.router, prefix="/renewals")
router.include_router(license_keys.router, prefix="/license-keys")
router.include_router(license_requests.router, prefix="/license-requests")
router.include_router(email_outbox.router, prefix="/email-outbox")
router.include_router(users.router, prefix="/users")
router.include_router(roles.router, prefix="/roles")
router.include_router(roles.permissions_router, prefix="/permissions")
router.include_router(api_clients.router, prefix="/api-clients")
router.include_router(audit_logs.router, prefix="/audit-logs")
router.include_router(api_logs.router, prefix="/api-logs")
router.include_router(dashboard.router, prefix="/dashboard")
router.include_router(settings.router, prefix="/settings")
router.include_router(change_requests.router, prefix="/change-requests")
router.include_router(notifications.router, prefix="/notifications")
router.include_router(clock_alerts.router, prefix="/clock-alerts")
router.include_router(clock_alerts.system_router, prefix="/system")
