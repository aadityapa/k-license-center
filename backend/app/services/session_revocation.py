"""
Ends a user's existing sign-ins.

Admin tokens are stateless JWTs, so deleting, locking or deactivating a user
would otherwise leave their open sessions working until the token expires.
Each change records "tokens issued before now are void" for that user, and
authentication rejects such tokens. Kept in process memory: after a restart
old tokens are checked only by expiry, and the database still refuses new
sign-ins.
"""
from __future__ import annotations

import threading
import time

_revoked_before: dict[int, int] = {}
_lock = threading.Lock()


def revoke_sessions(user_id: int) -> None:
    with _lock:
        _revoked_before[user_id] = int(time.time())


def is_revoked(user_id: int, iat: int | None) -> bool:
    cutoff = _revoked_before.get(user_id)
    if cutoff is None:
        return False
    # <= : iat has one-second resolution, so a token minted in the same second
    # as the revocation is treated as revoked (at worst: sign in once more).
    return iat is None or iat <= cutoff
