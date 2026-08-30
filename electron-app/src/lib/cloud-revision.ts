import type { CloudExportActivity, CloudState } from "@/shared/contracts"

export function cloudStateRevision(state: CloudState): string {
  return JSON.stringify({
    configured: state.configured,
    projectUrl: state.projectUrl,
    authenticated: state.authenticated,
    userEmail: state.userEmail,
    profile: state.profile,
    connections: state.connections,
    libraries: state.libraries,
    testAccounts: state.testAccounts,
  })
}

export function cloudActivityRevision(activity: CloudExportActivity[]): string {
  return JSON.stringify(activity)
}
