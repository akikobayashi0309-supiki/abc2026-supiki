import {
  GoogleAuthProvider,
  linkWithPopup,
  onAuthStateChanged,
  signInAnonymously,
  signInWithPopup,
  type User,
} from 'firebase/auth'
import { type FormEvent, useEffect, useState } from 'react'
import { type Generation, generate, listGenerations } from './api'
import { auth } from './firebase'

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [prompt, setPrompt] = useState('')
  const [history, setHistory] = useState<Generation[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // Guest mode: sign in anonymously so judges can try the app without an account.
  useEffect(
    () =>
      onAuthStateChanged(auth, (u) => {
        if (u) setUser(u)
        else signInAnonymously(auth).catch((e: Error) => setError(e.message))
      }),
    [],
  )

  useEffect(() => {
    if (!user) return
    listGenerations()
      .then(setHistory)
      .catch((e: Error) => setError(e.message))
  }, [user])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const g = await generate(prompt)
      setHistory((h) => [g, ...h])
      setPrompt('')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function signInWithGoogle() {
    const provider = new GoogleAuthProvider()
    try {
      // Upgrade the guest account so its history is kept.
      if (user?.isAnonymous) await linkWithPopup(user, provider)
      else await signInWithPopup(auth, provider)
      setUser(auth.currentUser)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <main>
      <header>
        <h1>AI Builder Cup 2026</h1>
        <span>
          {user?.isAnonymous ? 'Guest' : user?.email}
          {user?.isAnonymous && (
            <button type="button" onClick={signInWithGoogle}>
              Sign in with Google
            </button>
          )}
        </span>
      </header>

      <form onSubmit={onSubmit}>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Ask Gemini something..."
          rows={4}
        />
        <button type="submit" disabled={!user || busy || !prompt.trim()}>
          {busy ? 'Generating...' : 'Generate'}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      <ul>
        {history.map((g) => (
          <li key={g.id}>
            <p className="prompt">{g.prompt}</p>
            <p className="output">{g.output}</p>
            <small>
              {g.model} · {new Date(g.createdAt).toLocaleString()}
            </small>
          </li>
        ))}
      </ul>
    </main>
  )
}

export default App
