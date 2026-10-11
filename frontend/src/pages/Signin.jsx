import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { signIn } from '../lib/auth'
import monitor from '../assets/signin2-v2.png'
import '../SigninMonitor.css'

export default function SigninMonitor() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [focused, setFocused] = useState(null)
  const [blinking, setBlinking] = useState(false)
  const sceneRef = useRef(null)
  const navigate = useNavigate()

  // Blink every few seconds
  useEffect(() => {
    let timer
    const next = () => {
      timer = setTimeout(() => {
        setBlinking(true)
        setTimeout(() => setBlinking(false), 200)
        next()
      }, 2500 + Math.random() * 3000)
    }
    next()
    return () => clearTimeout(timer)
  }, [])

  // Dots follow the mouse
  useEffect(() => {
    const onMove = (e) => {
      const box = sceneRef.current.getBoundingClientRect()
      const x = (e.clientX - box.left) / box.width - 0.5   // -0.5 to 0.5
      const y = (e.clientY - box.top) / box.height - 0.35
      sceneRef.current.style.setProperty('--look-x', Math.max(-1, Math.min(1, x * 2)))
      sceneRef.current.style.setProperty('--look-y', Math.max(-1, Math.min(1, y * 2)))
    }
    window.addEventListener('mousemove', onMove)
    return () => window.removeEventListener('mousemove', onMove)
  }, [])

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (!email.trim() || !password) throw new Error('Enter your email and password')
      await signIn(email, password)
      navigate('/dashboard')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // An eye shows its dot until you type in it, and closes when it blinks.
  // While you type your password, the email eye stays closed so it can't peek.
  const eyeClass = (name, value) => {
    const typing = focused === name || value
    const closed = (blinking && !typing) || (name === 'email' && focused === 'password')
    return ['eye', `eye-${name}`, typing && 'typing', closed && 'closed'].filter(Boolean).join(' ')
  }

  return (
    <div className="signin-page">
      <header className="signin-header">
        <Link to="/" className="logo">Market Moves</Link>
        <p> <Link to="/signup"> New here? Create an account</Link></p>
      </header>

      <form ref={sceneRef} className="scene" onSubmit={handleSubmit} noValidate>
        <img src={monitor} alt="" className="scene-art" />

        <Link to="/" className="spot back">BACK</Link>

        <label htmlFor="email" className="spot label label-email">EMAIL</label>
        <label htmlFor="password" className="spot label label-password">PASSWORD</label>

        <div className={eyeClass('email', email)}>
          <input id="email" type="email" autoComplete="email" value={email}
            onChange={(e) => setEmail(e.target.value)}
            onFocus={() => setFocused('email')} onBlur={() => setFocused(null)} />
          <span className="dot" />
          <span className="lid" />
        </div>

        <div className={eyeClass('password', password)}>
          <input id="password" type="password" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)}
            onFocus={() => setFocused('password')} onBlur={() => setFocused(null)} />
          <span className="dot" />
          <span className="lid" />
        </div>

        <p className="spot error" role="alert">{error}</p>

        <button type="submit" className="spot confirm" disabled={loading}>
          {loading ? 'WAIT…' : 'CONFIRM'}
        </button>
      </form>
    </div>
  )
}
