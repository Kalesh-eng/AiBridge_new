/**
 * VirtualOffice.jsx — AIBridge Data Team 3D Office
 * Uses ONLY @react-three/fiber + three.js — no @react-three/drei
 */

import React, { useRef, useState, useEffect, useCallback } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'

// ── Agent config ──────────────────────────────────────────────────────────────
const AGENTS = [
  { id: 'sarah',   name: 'Sarah',   role: 'Data Analyst',    emoji: '📊', hex: 0x4A90D9, deskPos: [-2.6, 0, -1.5] },
  { id: 'marcus',  name: 'Marcus',  role: 'Strategy Advisor',emoji: '🎯', hex: 0xE85D4A, deskPos: [-0.4, 0, -1.5] },
  { id: 'dev_etl', name: 'Dev ETL', role: 'ETL Engineer',    emoji: '🔧', hex: 0xF5A623, deskPos: [ 1.8, 0, -1.5] },
  { id: 'quinn',   name: 'Quinn',   role: 'Data Quality',    emoji: '🛡️', hex: 0x7ED321, deskPos: [-2.6, 0,  1.0] },
  { id: 'maya',    name: 'Maya',    role: 'Communications',  emoji: '📱', hex: 0xBD10E0, deskPos: [-0.4, 0,  1.0] },
]

// ── Primitive helpers ─────────────────────────────────────────────────────────
function Box({ pos, size, color, emissive = 0x000000, emissiveIntensity = 0, roughness = 0.7, opacity = 1 }) {
  return (
    <mesh position={pos} castShadow receiveShadow>
      <boxGeometry args={size} />
      <meshStandardMaterial
        color={color}
        emissive={emissive}
        emissiveIntensity={emissiveIntensity}
        roughness={roughness}
        transparent={opacity < 1}
        opacity={opacity}
      />
    </mesh>
  )
}

function Sphere({ pos, r, color, emissive = 0x000000, emissiveIntensity = 0 }) {
  return (
    <mesh position={pos} castShadow>
      <sphereGeometry args={[r, 12, 12]} />
      <meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={emissiveIntensity} />
    </mesh>
  )
}

// ── Floor & walls ─────────────────────────────────────────────────────────────
// Room 10×8, origin at center. Desks cluster around x=-1..2, z=-1.5..1.2
function Room() {
  return (
    <group>
      {/* floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[10, 8]} />
        <meshStandardMaterial color={0xD5CCBE} roughness={0.95} />
      </mesh>
      {/* floor tile lines */}
      {Array.from({length:6}).map((_,i) => (
        <Box key={`fx${i}`} pos={[-5+i*2, 0.001, 0]} size={[0.02, 0.001, 8]} color={0xC0B8A8} roughness={1} />
      ))}
      {Array.from({length:5}).map((_,i) => (
        <Box key={`fz${i}`} pos={[0, 0.001, -4+i*2]} size={[10, 0.001, 0.02]} color={0xC0B8A8} roughness={1} />
      ))}

      {/* back wall — behind desks, z = -4 */}
      <mesh position={[0, 2, -4]} receiveShadow>
        <boxGeometry args={[10, 4, 0.2]} />
        <meshStandardMaterial color={0x3A4F8A} roughness={0.85} />
      </mesh>
      {/* left wall, x = -5 */}
      <mesh position={[-5, 2, 0]} receiveShadow>
        <boxGeometry args={[0.2, 4, 8]} />
        <meshStandardMaterial color={0x2E4070} roughness={0.85} />
      </mesh>
      {/* right wall, x = 5 — semi-transparent so camera from right side sees through */}
      <mesh position={[5, 2, 0]} receiveShadow>
        <boxGeometry args={[0.2, 4, 8]} />
        <meshStandardMaterial color={0x2E4070} roughness={0.85} opacity={0.3} transparent />
      </mesh>
      {/* ceiling */}
      <mesh position={[0, 4, 0]}>
        <boxGeometry args={[10, 0.1, 8]} />
        <meshStandardMaterial color={0x1E2A4A} roughness={0.95} opacity={0.4} transparent />
      </mesh>

      {/* windows in back wall */}
      <Box pos={[-1.5, 2.6, -3.9]} size={[2.4, 1.6, 0.05]} color={0xADD8F0} emissive={0x87CEEB} emissiveIntensity={0.2} roughness={0.1} />
      <Box pos={[ 2.0, 2.6, -3.9]} size={[2.0, 1.4, 0.05]} color={0xADD8F0} emissive={0x87CEEB} emissiveIntensity={0.2} roughness={0.1} />

      {/* baseboard accent */}
      <Box pos={[0, 0.05, -3.9]}  size={[10, 0.1, 0.05]} color={0x4A90D9} emissive={0x4A90D9} emissiveIntensity={0.15} roughness={0.4} />
      <Box pos={[-4.9, 0.05, 0]}  size={[0.05, 0.1, 8]}  color={0x4A90D9} emissive={0x4A90D9} emissiveIntensity={0.15} roughness={0.4} />
    </group>
  )
}

// ── Desk ──────────────────────────────────────────────────────────────────────
function Desk({ pos, hex, status }) {
  const screenColor = status === 'working' ? hex : 0x0D1F33
  const glow = status === 'working' ? 0.6 : 0.04
  return (
    <group position={pos}>
      {/* tabletop */}
      <Box pos={[0, 0.74, 0]}       size={[1.3, 0.06, 0.75]} color={0x9B7B2A} roughness={0.5} />
      {/* legs */}
      <Box pos={[-0.58,0.37,-0.30]} size={[0.06,0.74,0.06]} color={0x7A6035} />
      <Box pos={[ 0.58,0.37,-0.30]} size={[0.06,0.74,0.06]} color={0x7A6035} />
      <Box pos={[-0.58,0.37, 0.30]} size={[0.06,0.74,0.06]} color={0x7A6035} />
      <Box pos={[ 0.58,0.37, 0.30]} size={[0.06,0.74,0.06]} color={0x7A6035} />
      {/* monitor */}
      <Box pos={[0, 0.86,-0.24]} size={[0.07,0.18,0.07]} color={0x1A1A1A} />
      <Box pos={[0, 1.08,-0.24]} size={[0.60,0.40,0.04]} color={0x111111} />
      <Box pos={[0, 1.08,-0.22]} size={[0.54,0.34,0.01]} color={screenColor} emissive={screenColor} emissiveIntensity={glow} roughness={0.05} />
      {/* keyboard */}
      <Box pos={[0,0.78, 0.06]}    size={[0.40,0.02,0.14]} color={0x222222} />
      <Box pos={[0.28,0.78, 0.06]} size={[0.07,0.02,0.10]} color={0x2A2A2A} />
      {/* chair */}
      <Box pos={[0, 0.44, 0.48]}  size={[0.52,0.06,0.52]} color={0x1B3D7A} roughness={0.85} />
      <Box pos={[0, 0.68, 0.22]}  size={[0.52,0.48,0.06]} color={0x1B3D7A} roughness={0.85} />
      <Box pos={[-0.22,0.22,0.22]} size={[0.04,0.44,0.04]} color={0x2A2A2A} />
      <Box pos={[ 0.22,0.22,0.22]} size={[0.04,0.44,0.04]} color={0x2A2A2A} />
      <Box pos={[-0.22,0.22,0.70]} size={[0.04,0.44,0.04]} color={0x2A2A2A} />
      <Box pos={[ 0.22,0.22,0.70]} size={[0.04,0.44,0.04]} color={0x2A2A2A} />
    </group>
  )
}

// ── Agent body ────────────────────────────────────────────────────────────────
function AgentBody({ pos, hex, status }) {
  const bodyRef = useRef()
  const [offset] = useState(() => Math.random() * Math.PI * 2)
  useFrame(({ clock }) => {
    if (!bodyRef.current) return
    if (status === 'working') {
      bodyRef.current.rotation.x = Math.sin(clock.elapsedTime * 3.5 + offset) * 0.05
    } else {
      bodyRef.current.rotation.x = THREE.MathUtils.lerp(bodyRef.current.rotation.x, 0, 0.08)
    }
  })
  const dot = status === 'working' ? 0x00FF88 : 0x444444
  return (
    <group position={pos}>
      <group ref={bodyRef}>
        <Box pos={[0,1.08,0]}     size={[0.20,0.26,0.13]} color={hex} roughness={0.9} />
        <Box pos={[0,1.42,0]}     size={[0.18,0.19,0.17]} color={0xFDBCB4} roughness={0.95} />
        <Box pos={[0,1.54,0]}     size={[0.19,0.06,0.18]} color={0x1C0F0A} roughness={1.0} />
        <Box pos={[-0.14,1.06,0]} size={[0.06,0.20,0.06]} color={hex} />
        <Box pos={[ 0.14,1.06,0]} size={[0.06,0.20,0.06]} color={hex} />
        <Box pos={[-0.05,0.78,0]} size={[0.08,0.24,0.08]} color={0x243560} />
        <Box pos={[ 0.05,0.78,0]} size={[0.08,0.24,0.08]} color={0x243560} />
      </group>
      <Sphere pos={[0,1.75,0]} r={0.045} color={dot} emissive={dot} emissiveIntensity={1.5} />
    </group>
  )
}

// ── Decor ─────────────────────────────────────────────────────────────────────
function Decor() {
  return (
    <group>
      {/* plant in front-right corner */}
      <Box pos={[4.2, 0.22, 3.2]}  size={[0.30,0.44,0.30]} color={0x7A5C1E} />
      <Sphere pos={[4.2, 0.72, 3.2]} r={0.30} color={0x2A7030} />
      <Sphere pos={[4.4, 0.95, 3.3]} r={0.20} color={0x358040} />
      <Sphere pos={[4.0, 0.90, 3.1]} r={0.16} color={0x2A7030} />

      {/* bookshelf on left wall */}
      <Box pos={[-4.9,1.1,2.2]} size={[0.14,2.2,1.4]} color={0x9B7B2A} />
      <Box pos={[-4.9,0.4,2.2]} size={[0.12,0.04,1.3]} color={0x7A6035} />
      <Box pos={[-4.9,1.1,2.2]} size={[0.12,0.04,1.3]} color={0x7A6035} />
      <Box pos={[-4.9,1.8,2.2]} size={[0.12,0.04,1.3]} color={0x7A6035} />
      {[0xE85D4A,0x4A90D9,0x7ED321,0xF5A623,0xBD10E0].map((c,i) => (
        <Box key={i} pos={[-4.9,0.65,1.6+i*0.28]} size={[0.09,0.44,0.13]} color={c} />
      ))}

      {/* sofa */}
      <Box pos={[3.5,0.17,2.5]}  size={[1.7,0.34,0.65]}  color={0x1B3D7A} roughness={0.9} />
      <Box pos={[3.5,0.42,2.18]} size={[1.7,0.46,0.13]}  color={0x1B3D7A} roughness={0.9} />
      <Box pos={[2.65,0.38,2.5]} size={[0.13,0.32,0.65]} color={0x1B3D7A} roughness={0.9} />
      <Box pos={[4.35,0.38,2.5]} size={[0.13,0.32,0.65]} color={0x1B3D7A} roughness={0.9} />

      {/* coffee table */}
      <Box pos={[3.5,0.30,3.3]}  size={[0.85,0.04,0.46]} color={0x9B7B2A} />
      <Box pos={[3.15,0.15,3.1]} size={[0.04,0.30,0.04]} color={0x7A6035} />
      <Box pos={[3.85,0.15,3.1]} size={[0.04,0.30,0.04]} color={0x7A6035} />
      <Box pos={[3.15,0.15,3.5]} size={[0.04,0.30,0.04]} color={0x7A6035} />
      <Box pos={[3.85,0.15,3.5]} size={[0.04,0.30,0.04]} color={0x7A6035} />

      {/* ceiling lights */}
      {[[-2,3.92,-1.5],[0.5,3.92,-1.5],[2.5,3.92,-1.5],
        [-2,3.92, 1.0],[0.5,3.92, 1.0],[2.5,3.92, 1.0]].map((p,i) => (
        <Box key={i} pos={p} size={[0.38,0.05,0.38]} color={0xEEEEEE} emissive={0xFFF5D0} emissiveIntensity={0.8} roughness={0.4} />
      ))}

      {/* whiteboard on left wall */}
      <Box pos={[-4.9,2.2,-2.0]} size={[0.07,1.3,1.9]}  color={0xF2F2F2} roughness={0.2} />
      <Box pos={[-4.86,2.2,-2.0]} size={[0.02,1.1,1.7]} color={0x4A90D9} emissive={0x4A90D9} emissiveIntensity={0.08} roughness={0.5} />
    </group>
  )
}

// ── Camera ────────────────────────────────────────────────────────────────────
// Fixed isometric-style camera — positioned far outside the room, looking at desk center
function SceneCamera() {
  const { camera } = useThree()

  // Set camera once on mount
  useEffect(() => {
    // Position: front-right elevated — classic isometric
    // Desk cluster center is roughly (-0.5, 1, -0.2)
    // From position (10, 10, 10) looking at (-0.5, 1, -0.2) gives a nice view
    camera.position.set(10, 10, 10)
    camera.lookAt(-0.5, 1, -0.2)
    camera.fov = 50
    camera.updateProjectionMatrix()
  }, [camera])

  return null
}

// ── Orbit controls ─────────────────────────────────────────────────────────────
function CameraController() {
  const { camera, gl } = useThree()

  // Store spherical coords matching initial position (10,10,10) → target (-0.5,1,-0.2)
  // Vector from target to cam: (10.5, 9, 10.2) → r≈16.4, theta≈PI/4, phi≈acos(9/16.4)≈0.99
  const cam = useRef({
    theta: Math.PI / 4,   // azimuth — 45° diagonal
    phi: 0.95,            // polar — ~54° from top
    radius: 16,
    tx: -0.5, ty: 1, tz: -0.2,  // look-at target
    drag: false, right: false, lx: 0, ly: 0
  })

  useEffect(() => {
    const el = gl.domElement
    const c = cam.current
    const down = e => { c.drag = true; c.right = e.button === 2; c.lx = e.clientX; c.ly = e.clientY }
    const up   = () => { c.drag = false }
    const move = e => {
      if (!c.drag) return
      const dx = e.clientX - c.lx, dy = e.clientY - c.ly
      c.lx = e.clientX; c.ly = e.clientY
      if (c.right) { c.tx -= dx * 0.012; c.tz -= dy * 0.012 }
      else {
        c.theta -= dx * 0.006
        c.phi = Math.max(0.15, Math.min(1.4, c.phi + dy * 0.006))
      }
    }
    const wheel = e => { c.radius = Math.max(5, Math.min(28, c.radius + e.deltaY * 0.03)) }
    const ctx   = e => e.preventDefault()
    el.addEventListener('mousedown', down)
    window.addEventListener('mouseup', up)
    window.addEventListener('mousemove', move)
    el.addEventListener('wheel', wheel, { passive: true })
    el.addEventListener('contextmenu', ctx)
    return () => {
      el.removeEventListener('mousedown', down)
      window.removeEventListener('mouseup', up)
      window.removeEventListener('mousemove', move)
      el.removeEventListener('wheel', wheel)
      el.removeEventListener('contextmenu', ctx)
    }
  }, [gl])

  useFrame(() => {
    const c = cam.current
    const r = c.radius
    camera.position.set(
      c.tx + r * Math.sin(c.phi) * Math.sin(c.theta),
      c.ty + r * Math.cos(c.phi),
      c.tz + r * Math.sin(c.phi) * Math.cos(c.theta)
    )
    camera.lookAt(c.tx, c.ty, c.tz)
  })

  return null
}

// ── HUD overlay ───────────────────────────────────────────────────────────────
function HUD({ agents, connected }) {
  return (
    <div style={{
      position: 'absolute', top: 56, right: 16,
      background: 'rgba(10,20,50,0.90)',
      border: '1px solid rgba(74,144,217,0.35)',
      borderRadius: 10, padding: '12px 16px',
      color: '#fff', width: 210,
      backdropFilter: 'blur(10px)', zIndex: 10,
      fontFamily: 'system-ui, sans-serif',
      boxSizing: 'border-box',
    }}>
      <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:10 }}>
        <div style={{ width:8, height:8, borderRadius:'50%', background: connected ? '#00FF88' : '#FF5555', boxShadow: `0 0 6px ${connected ? '#00FF88' : '#FF5555'}` }} />
        <span style={{ fontSize:11, opacity:0.65 }}>{connected ? 'Live backend' : 'Demo mode'}</span>
      </div>
      {agents.map(a => (
        <div key={a.id} style={{ display:'flex', alignItems:'center', gap:9, marginBottom:7 }}>
          <span style={{ fontSize:14 }}>{a.emoji}</span>
          <div style={{ flex:1 }}>
            <div style={{ fontSize:12, fontWeight:600 }}>{a.name}</div>
            <div style={{ fontSize:10, opacity:0.5, marginTop:1 }}>
              {a.status === 'working' ? `⚡ ${a.currentTask || 'Working…'}` : '○ Idle'}
            </div>
          </div>
          <div style={{ width:7, height:7, borderRadius:'50%', background: a.status === 'working' ? '#00FF88' : '#444' }} />
        </div>
      ))}
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────
export default function VirtualOffice() {
  const [agents, setAgents] = useState(AGENTS.map(a => ({ ...a, status: 'idle', currentTask: null })))
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)

  useEffect(() => {
    const token = localStorage.getItem('aibridge_token') || localStorage.getItem('token') || sessionStorage.getItem('token') || ''
    const url = `ws://localhost:8888/ws/agents${token ? '?token=' + token : ''}`
    const connect = () => {
      try {
        const ws = new WebSocket(url)
        wsRef.current = ws
        ws.onopen    = () => setConnected(true)
        ws.onclose   = () => { setConnected(false); setTimeout(connect, 3000) }
        ws.onerror   = () => setConnected(false)
        ws.onmessage = e => {
          try {
            const d = JSON.parse(e.data)
            if (d.agents) setAgents(prev => prev.map(a => {
              const live = d.agents.find(x => x.name === a.id || x.id === a.id)
              if (!live) return a
              return { ...a, status: live.status === 'busy' ? 'working' : live.status || 'idle', currentTask: live.current_task || null }
            }))
          } catch {}
        }
      } catch {}
    }
    connect()
    return () => wsRef.current?.close()
  }, [])

  useEffect(() => {
    if (connected) return
    const tasks = ['Running analysis…','Forecasting trends…','Optimising pipeline…','Validating data…','Sending brief…']
    let i = 0
    const id = setInterval(() => {
      setAgents(prev => prev.map((a, idx) => ({
        ...a,
        status: idx === i % AGENTS.length ? 'working' : 'idle',
        currentTask: idx === i % AGENTS.length ? tasks[idx] : null,
      })))
      i++
    }, 2200)
    return () => clearInterval(id)
  }, [connected])

  return (
    <div style={{ width:'100%', height:'100vh', background:'#060D1E', position:'relative', overflow:'hidden' }}>
      <div style={{
        position:'absolute', top:0, left:0, right:0, zIndex:10,
        padding:'10px 20px',
        background:'linear-gradient(to bottom,rgba(6,13,30,0.98),transparent)',
        display:'flex', alignItems:'center', gap:12,
        fontFamily:'system-ui, sans-serif',
      }}>
        <span style={{ fontSize:19, fontWeight:700, color:'#fff', letterSpacing:.5 }}>
          🏢 AIBridge <span style={{ color:'#4A90D9' }}>Data Team</span>
        </span>
        <span style={{ fontSize:11, color:'#7A9FCC', marginTop:1 }}>Virtual Office</span>
      </div>

      <HUD agents={agents} connected={connected} />

      <div style={{ position:'absolute', bottom:14, left:16, zIndex:10, color:'rgba(255,255,255,0.28)', fontSize:11, fontFamily:'system-ui' }}>
        🖱 Drag to rotate · Scroll to zoom · Right-click to pan
      </div>

      <Canvas
        shadows
        gl={{ antialias: true }}
        onCreated={({ gl, camera }) => {
          gl.shadowMap.enabled = true
          gl.shadowMap.type = THREE.PCFSoftShadowMap
          // Set initial camera explicitly here too
          camera.position.set(10, 10, 10)
          camera.lookAt(-0.5, 1, -0.2)
          camera.fov = 50
          camera.updateProjectionMatrix()
        }}
      >
        <ambientLight intensity={0.55} />
        <directionalLight
          position={[8, 12, 8]} intensity={0.9}
          castShadow
          shadow-mapSize-width={1024} shadow-mapSize-height={1024}
          shadow-camera-near={0.5} shadow-camera-far={40}
          shadow-camera-left={-8} shadow-camera-right={8}
          shadow-camera-top={8} shadow-camera-bottom={-8}
          color={0xFFF8E0}
        />
        <directionalLight position={[-6, 8, -4]} intensity={0.35} color={0xA0C0FF} />
        <pointLight position={[0, 3.8, -1]} intensity={0.8} color={0xFFF5D0} distance={12} />
        <pointLight position={[0, 3.8,  2]} intensity={0.6} color={0xFFF5D0} distance={12} />

        <CameraController />
        <Room />
        <Decor />

        {agents.map(a => (
          <group key={a.id}>
            <Desk pos={a.deskPos} hex={a.hex} status={a.status} />
            <AgentBody
              pos={[a.deskPos[0], a.deskPos[1], a.deskPos[2] + 0.50]}
              hex={a.hex}
              status={a.status}
            />
          </group>
        ))}
      </Canvas>
    </div>
  )
}
