# Cloud export master cleanup

This function is the physical half of the 30-day Cloud Activity retention
policy. The database atomically claims expired assets; this function removes
their private Storage objects and finalizes only the matching claim tokens.

## Remote configuration required

The repository cannot safely version project-specific URLs, service keys, or
cleanup secrets. After deploying the migration and Edge Function to the target
Supabase project:

1. Set a strong `CLOUD_EXPORT_CLEANUP_SECRET` Edge Function secret. The hosted
   `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are supplied by Supabase.
2. Create a Supabase Cron scheduled HTTP invocation (recommended: every 15
   minutes) that sends `POST` to the deployed
   `purge-expired-cloud-exports` function.
3. Include the cleanup secret in the `x-cloud-cleanup-secret` header and the
   project's normal function authorization header. Never commit either value.
4. Monitor non-2xx responses. A failed Storage removal or stale claim is safe:
   metadata remains `expiring` and becomes claimable again after its five-minute
   lease.

Without that remote schedule, expiration metadata remains safe but the Storage
objects are not physically deleted. SQL alone must never be treated as physical
Storage deletion.
