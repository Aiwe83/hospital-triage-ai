# secrets/

This directory is **mounted read-only** into the `mcp-server` container at
`/secrets`. The MCP server reads its Google service-account JSON from this
location to perform real Google Drive uploads via the `drive_upload` tool.

## Files expected here

| File | Used by | Notes |
|------|---------|-------|
| `service-account.json` | mcp-server (Drive tool) | Download from GCP Console → IAM → Service Accounts → Keys → "Add key" → JSON. **Never commit.** |

## Why `service-account.json` (and not OAuth)?

Service accounts are non-interactive and work well from inside a container
with no browser. The trade-off is that files created by a service account
are **owned by that service account**, not by your personal Google account.
The user sees them as "Shared with me" — fine for a course MVP.

To make uploaded reports visible inside your own Drive folder hierarchy,
**share the destination folder with the service account's email** (rol:
Editor). The service account email is printed by `mcp-server` on every
successful upload (`service_account_email` field in the response).

## Quick check the credentials are wired

```bash
curl -s http://localhost:7800/tools/drive_status | jq
```

Expected when configured:

```json
{
  "configured": true,
  "service_account_json_path": "/secrets/service-account.json",
  "default_folder_id": "1L4lph5jiOUD8A3eki2m2pkV2B1CllT8e"
}
```
