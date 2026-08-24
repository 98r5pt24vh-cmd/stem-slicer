import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import { App } from "./App"
import "@/styles/globals.css"

const root = document.getElementById("root")
if (!root) throw new Error("Point de montage React introuvable.")

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
