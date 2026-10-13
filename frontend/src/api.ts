import { auth } from './firebase'

export type Generation = {
  id: string
  prompt: string
  output: string
  model: string
  createdAt: string
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const user = auth.currentUser
  if (!user) throw new Error('Not signed in')
  const token = await user.getIdToken()
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...init.headers,
    },
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

export const generate = (prompt: string) =>
  request<Generation>('/api/generate', {
    method: 'POST',
    body: JSON.stringify({ prompt }),
  })

export const listGenerations = () => request<Generation[]>('/api/generations')
