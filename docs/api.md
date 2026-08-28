# API Notes

FastAPI exposes OpenAPI at `/openapi.json` and interactive documentation at `/docs`.
All product endpoints use `/api/v1`.

Authentication uses an HttpOnly, SameSite=Strict session cookie. Mutating browser
requests also require the CSRF token cookie value in `X-CSRF-Token`. WebSocket
connections are authenticated with the session cookie during the HTTP upgrade.

Every `CommandRequest` contains:

```json
{
  "robotId": "robot UUID",
  "type": "reset_arm",
  "params": { "side": "left" },
  "idempotencyKey": "caller-generated UUID",
  "expectedRevision": 42,
  "controlLeaseId": "lease UUID"
}
```

The robot ID and idempotency key form a unique database constraint. A mismatched
revision returns `409`, while an invalid or expired lease returns `403`.
