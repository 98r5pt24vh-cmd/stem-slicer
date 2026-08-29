import { randomBytes } from "node:crypto"
import { chmod, mkdir, readFile, writeFile } from "node:fs/promises"
import { homedir } from "node:os"
import path from "node:path"
import process from "node:process"
import { URL } from "node:url"

import { createClient } from "@supabase/supabase-js"

const cloudRoot = path.join(
  homedir(),
  "Library",
  "Caches",
  "Stem Slicer",
  "electron-prototype",
  "cloud",
)
const settingsPath = path.join(cloudRoot, "settings.json")
const credentialsPath = path.join(cloudRoot, "alpha-test-credentials.json")

const settings = JSON.parse(await readFile(settingsPath, "utf8"))
if (!settings.projectUrl || !settings.publishableKey) {
  throw new Error(`Cloud configuration is incomplete in ${settingsPath}`)
}

async function loadOrCreateCredentials() {
  try {
    return JSON.parse(await readFile(credentialsPath, "utf8"))
  } catch {
    const suffix = randomBytes(6).toString("hex")
    const created = {
      projectRef: new URL(settings.projectUrl).hostname.split(".")[0],
      createdAt: new Date().toISOString(),
      accounts: {
        nrgy: {
          email: `slicer-alpha-nrgy-${suffix}@example.com`,
          password: randomBytes(32).toString("base64url"),
          handle: "plus-nrgy",
          displayName: "+NRGY",
        },
        xt: {
          email: `slicer-alpha-xt-${suffix}@example.com`,
          password: randomBytes(32).toString("base64url"),
          handle: "xt-alpha",
          displayName: "XT",
        },
      },
    }
    await mkdir(cloudRoot, { recursive: true })
    await writeFile(credentialsPath, `${JSON.stringify(created, null, 2)}\n`, { mode: 0o600 })
    await chmod(credentialsPath, 0o600)
    return created
  }
}

function client() {
  return createClient(settings.projectUrl, settings.publishableKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
  })
}

async function ensureAccount(account) {
  const supabase = client()
  let auth = await supabase.auth.signInWithPassword({
    email: account.email,
    password: account.password,
  })

  if (auth.error) {
    auth = await supabase.auth.signUp({
      email: account.email,
      password: account.password,
      options: {
        data: {
          handle: account.handle,
          display_name: account.displayName,
        },
      },
    })
  }

  if (auth.error) throw auth.error
  if (!auth.data.session || !auth.data.user) {
    throw new Error(`No active session was returned for ${account.displayName}. Is email confirmation disabled?`)
  }

  const profile = await supabase.from("profiles").upsert({
    id: auth.data.user.id,
    handle: account.handle,
    display_name: account.displayName,
  }, { onConflict: "id" }).select("id,handle,display_name").single()
  if (profile.error) throw profile.error

  await supabase.auth.signOut({ scope: "local" })
  return profile.data
}

const credentials = await loadOrCreateCredentials()
const profiles = []
for (const account of Object.values(credentials.accounts)) {
  profiles.push(await ensureAccount(account))
}

process.stdout.write(`${JSON.stringify({
  ok: true,
  credentialsPath,
  accounts: profiles.map((profile) => ({
    id: profile.id,
    handle: profile.handle,
    displayName: profile.display_name,
  })),
}, null, 2)}\n`)
