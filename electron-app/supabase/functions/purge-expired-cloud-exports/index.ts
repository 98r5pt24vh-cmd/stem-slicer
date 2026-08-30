import { createClient } from "npm:@supabase/supabase-js@2"

const BATCH_SIZE = 100
const BUCKET = "cloud-export-masters"
const LEASE_SECONDS = 300

interface ClaimedAsset {
  asset_id: string
  object_path: string
  claim_id: string
}

function json(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  })
}

function requestSecret(request: Request): string {
  const authorization = request.headers.get("authorization") ?? ""
  return request.headers.get("x-cloud-cleanup-secret")
    ?? authorization.replace(/^Bearer\s+/i, "")
}

Deno.serve(async (request) => {
  if (request.method !== "POST") return json(405, { error: "Method not allowed." })

  const projectUrl = Deno.env.get("SUPABASE_URL") ?? ""
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? ""
  const cleanupSecret = Deno.env.get("CLOUD_EXPORT_CLEANUP_SECRET") ?? ""
  if (!projectUrl || !serviceRoleKey || !cleanupSecret) {
    return json(503, { error: "Cloud export cleanup is not configured." })
  }
  if (requestSecret(request) !== cleanupSecret) return json(401, { error: "Unauthorized." })

  const supabase = createClient(projectUrl, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  })
  // Claiming is an atomic SQL transition to `expiring`. A UUID token and short
  // lease prevent two scheduled invocations from deleting/finalizing the same
  // object, while allowing recovery if this worker stops midway.
  const claim = await supabase.rpc("claim_expired_cloud_export_assets", {
    p_limit: BATCH_SIZE,
    p_lease_seconds: LEASE_SECONDS,
  })

  if (claim.error) return json(500, { error: claim.error.message })
  const assets = (claim.data ?? []) as ClaimedAsset[]
  if (assets.length === 0) return json(200, { removed: 0, remaining: false })

  // Physical deletion must happen through the Storage API. If it fails, the
  // rows deliberately stay `expiring`; their leases make them retryable.
  const removed = await supabase.storage.from(BUCKET).remove(assets.map((asset) => asset.object_path))
  if (removed.error) return json(500, { error: removed.error.message, removed: 0 })

  const transitions = await Promise.all(assets.map((asset) => (
    supabase.rpc("finalize_cloud_export_asset_expiration", {
      p_asset_id: asset.asset_id,
      p_claim_id: asset.claim_id,
    })
  )))
  const transitionError = transitions.find((result) => result.error)?.error
  if (transitionError) {
    return json(500, {
      error: transitionError.message,
      removed: transitions.filter((result) => !result.error).length,
      retryable: true,
    })
  }

  return json(200, {
    removed: assets.length,
    remaining: assets.length === BATCH_SIZE,
  })
})
