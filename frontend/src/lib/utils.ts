import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import api from './api'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export function daysUntil(iso: string): number {
  const now = new Date()
  const target = new Date(iso)
  return Math.ceil((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
}

export function parseSubject(json: string): Record<string, string> {
  try {
    return JSON.parse(json)
  } catch {
    return { cn: 'Unknown' }
  }
}

export function parseSAN(json: string): { type: string; value: string }[] {
  try {
    return JSON.parse(json)
  } catch {
    return []
  }
}

// Extracts a readable message from an axios error whose response was
// requested as a blob — an error body (e.g. a 404/500 JSON {detail: ...})
// still arrives as a Blob when responseType: 'blob' is set, since axios
// picks the parse strategy before it knows the response is an error.
async function blobErrorMessage(err: any): Promise<string> {
  const data = err?.response?.data
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text())
      if (parsed?.detail) return typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail)
    } catch {
      // Not JSON (e.g. an HTML error page) — fall through to the generic message.
    }
  }
  return err?.message || 'Download failed.'
}

export async function authenticatedDownload(url: string, filename: string): Promise<void> {
  try {
    // Routed through the shared axios instance (baseURL cleared since
    // callers already pass a full "/api/v1/..." path) so it picks up the
    // same JWT/API-key/tenant headers — and the same 401-redirect-to-login
    // handling — as every other request in the app, rather than the old
    // fetch() call that only ever sent a (usually empty) X-API-Key header.
    const response = await api.get(url, { baseURL: '', responseType: 'blob' })
    const objectUrl = URL.createObjectURL(response.data)
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = filename
    // Firefox silently no-ops a detached anchor's click() — it has to be
    // in the document. Revoke on the next tick so the download has
    // actually started before the object URL is torn down.
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
  } catch (err: any) {
    alert(await blobErrorMessage(err))
  }
}
