/**
 * Tooltip.jsx — reusable hover tooltip for AIBridge
 * Usage: <Tooltip text="What this button does"><button>Click</button></Tooltip>
 */

import { useState, useRef } from 'react'

export default function Tooltip({ text, children, position = 'top', delay = 300 }) {
  const [visible, setVisible] = useState(false)
  const timer = useRef(null)

  const show = () => {
    timer.current = setTimeout(() => setVisible(true), delay)
  }
  const hide = () => {
    clearTimeout(timer.current)
    setVisible(false)
  }

  const pos = {
    top:    { bottom: '100%', left: '50%', transform: 'translateX(-50%)', marginBottom: 6 },
    bottom: { top: '100%',   left: '50%', transform: 'translateX(-50%)', marginTop: 6 },
    left:   { right: '100%', top: '50%',  transform: 'translateY(-50%)', marginRight: 6 },
    right:  { left: '100%',  top: '50%',  transform: 'translateY(-50%)', marginLeft: 6 },
  }

  const arrow = {
    top:    { top: '100%',  left: '50%', transform: 'translateX(-50%)', borderColor: '#1e293b transparent transparent transparent' },
    bottom: { bottom: '100%', left: '50%', transform: 'translateX(-50%)', borderColor: 'transparent transparent #1e293b transparent' },
    left:   { left: '100%', top: '50%',  transform: 'translateY(-50%)', borderColor: 'transparent transparent transparent #1e293b' },
    right:  { right: '100%', top: '50%', transform: 'translateY(-50%)', borderColor: 'transparent #1e293b transparent transparent' },
  }

  return (
    <div style={{ position: 'relative', display: 'inline-flex' }} onMouseEnter={show} onMouseLeave={hide}>
      {children}
      {visible && text && (
        <div style={{ position: 'absolute', zIndex: 9999, ...pos[position], pointerEvents: 'none' }}>
          <div style={{ background: '#1e293b', color: '#fff', fontSize: 11, padding: '5px 9px', borderRadius: 5, whiteSpace: 'nowrap', maxWidth: 220, lineHeight: 1.4, boxShadow: '0 2px 8px rgba(0,0,0,.25)', wordBreak: 'break-word', whiteSpace: 'normal' }}>
            {text}
          </div>
          <div style={{ position: 'absolute', width: 0, height: 0, border: '4px solid', ...arrow[position] }} />
        </div>
      )}
    </div>
  )
}
