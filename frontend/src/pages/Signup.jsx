import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { MIN_PASSWORD, signUp } from '../lib/auth'
import monitor from '../assets/signin2-blank.png'
import '../SignupMonitor.css'

// Each field: its id, the label written on the screen, input type, autofill hint,
// which spot on the screen it goes in (see the .field-… classes in the CSS),
// and which part of the face it shows (eye, nose or smile).
const FIELDS = [
  { id: 'firstName', label: 'FIRST NAME', type: 'text', autoComplete: 'given-name', spot: 'first', face: 'eye' },
  { id: 'lastName', label: 'LAST NAME', type: 'text', autoComplete: 'family-name', spot: 'last', face: 'eye' },
  { id: 'email', label: 'EMAIL', type: 'email', autoComplete: 'email', spot: 'email', face: 'nose' },
  { id: 'password', label: 'PASSWORD', type: 'password', autoComplete: 'new-password', spot: 'password', face: 'smile-left' },
  { id: 'confirm', label: 'CONFIRM PASSWORD', type: 'password', autoComplete: 'new-password', spot: 'confirm', face: 'smile-right' },
]

export default function SignupMonitor() {
  // One object holds every field's value, e.g. { firstName: 'Maya', email: '...' }
  const [values, setValues] = useState({ firstName: '', lastName: '', email: '', password: '', confirm: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const sceneRef = useRef(null)

  // Make the eyes follow the mouse: we store how far left/right and up/down the
  // mouse is (-1 to 1) in CSS variables, and the CSS moves the dots with them.
  useEffect(() => {
    const onMove = (e) => {
      const box = sceneRef.current.getBoundingClientRect()
      const x = ((e.clientX - box.left) / box.width - 0.5) * 2
      const y = ((e.clientY - box.top) / box.height - 0.25) * 2
      sceneRef.current.style.setProperty('--look-x', Math.max(-1, Math.min(1, x)))
      sceneRef.current.style.setProperty('--look-y', Math.max(-1, Math.min(1, y)))
    }
    window.addEventListener('mousemove', onMove)
    return () => window.removeEventListener('mousemove', onMove)
  }, [])

  // Update just the field that changed
  const update = (id, value) => setValues((v) => ({ ...v, [id]: value }))

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    // Check the form before sending it
    if (Object.values(values).some((v) => !v.trim())) {
      setError('Please fill in every box')
      return
    }
    if (values.password.length < MIN_PASSWORD) {
      setError(`Password must be at least ${MIN_PASSWORD} characters`)
      return
    }
    if (values.password !== values.confirm) {
      setError("Passwords don't match")
      return
    }

    setLoading(true)
    try {
      await signUp(values)
      navigate('/signin')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="signup-page">
      <header className="signup-header">
        <Link to="/" className="logo">MyAPP</Link>
        <p>Already have an account? <Link to="/signin">Sign in</Link></p>
      </header>

      {/* The drawing, with the labels, boxes and button placed on top of it */}
      <form ref={sceneRef} className="signup-scene" onSubmit={handleSubmit} noValidate>
        <img src={monitor} alt="" className="scene-art" />

        <Link to="/" className="spot back">BACK</Link>

        {FIELDS.map((f) => (
          <div key={f.id} className={`field field-${f.spot}`}>
            <label htmlFor={f.id} className="spot field-label">{f.label}</label>
            <input
              id={f.id}
              type={f.type}
              autoComplete={f.autoComplete}
              value={values[f.id]}
              onChange={(e) => update(f.id, e.target.value)}
              placeholder=" " /* a blank placeholder lets the CSS tell when the box has text */
            />
            {/* The face part drawn on this box. The CSS hides it while you type. */}
            <span className={`face face-${f.face}`} aria-hidden="true">
              {f.face === 'eye' && <><span className="dot" /><span className="lid" /></>}
              {f.face === 'nose' && <span className="nose" />}
              {f.face.startsWith('smile') && <span className="smile" />}
            </span>
          </div>
        ))}

        <p className="spot error" role="alert">{error}</p>

        <button type="submit" className="spot confirm" disabled={loading}>
          {loading ? 'WAIT…' : 'CONFIRM'}
        </button>
      </form>
    </div>
  )
}
