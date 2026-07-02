
with open('E:/AIBRIDGE_Claude/frontend/src/pages/EtlAgent.jsx', encoding='utf-8') as f:
    src = f.read()

BROKEN = """    // Batch updates every 500ms to prevent flickering
    const pendingLines = []
    const flushTimer = setInterval(() => {
      if (pendingLines.length > 0) {
        const batch = [...pendingLines]
        pendingLines.length = 0
        setLines(prev => [...prev, ...batch])
      }
    }, 500)

    es.onmessage = (e) => { pendingLines.push(e.data) }

    es.addEventListener('done', (e) => {
      clearInterval(flushTimer)
      if (pendingLines.length > 0) {
        setLines(prev => [...prev, ...pendingLines])
        pendingLines.length = 0
      }
      try {
        const payload = JSON.parse(e.data)
        setStatus(payload.status)
        if (onFinished) onFinished(payload)
      } catch {
        setStatus('failed')
      }
      es.close()
    })
    es.onerror = () => {
      clearInterval(flushTimer)
      if (pendingLines.length > 0) {
        setLines(prev => [...prev, ...pendingLines])
        pendingLines.length = 0
      }
      es.close()
    }

    return () => { clearInterval(flushTimer); es.close() }
    es.addEventListener('done', (e) => {
      try {
        const payload = JSON.parse(e.data)
        setStatus(payload.status)
        if (onFinished) onFinished(payload)
      } catch {
        setStatus('failed')
      }
      es.close()
    })
    es.onerror = () => {
      setLines(prev => [...prev, '\u26a0 Log stream disconnected.'])
      es.close()
    }

    return () => es.close()"""

FIXED = """    // Batch updates every 500ms to prevent flickering
    const pendingLines = []
    const flushTimer = setInterval(() => {
      if (pendingLines.length > 0) {
        const batch = [...pendingLines]
        pendingLines.length = 0
        setLines(prev => [...prev, ...batch])
      }
    }, 500)

    es.onmessage = (e) => { pendingLines.push(e.data) }

    es.addEventListener('done', (e) => {
      clearInterval(flushTimer)
      if (pendingLines.length > 0) {
        setLines(prev => [...prev, ...pendingLines])
        pendingLines.length = 0
      }
      try {
        const payload = JSON.parse(e.data)
        setStatus(payload.status)
        if (onFinished) onFinished(payload)
      } catch {
        setStatus('failed')
      }
      es.close()
    })
    es.onerror = () => {
      clearInterval(flushTimer)
      if (pendingLines.length > 0) {
        setLines(prev => [...prev, ...pendingLines])
        pendingLines.length = 0
      }
      es.close()
    }

    return () => { clearInterval(flushTimer); es.close() }"""

if BROKEN in src:
    src = src.replace(BROKEN, FIXED)
    with open('E:/AIBRIDGE_Claude/frontend/src/pages/EtlAgent.jsx', 'w', encoding='utf-8') as f:
        f.write(src)
    print("Fixed: duplicate handlers removed")
else:
    # Try finding by looking for the old handler after the new return
    import re
    # Find the pattern: new return followed by old duplicate handlers
    pattern = r"(    return \(\) => \{ clearInterval\(flushTimer\); es\.close\(\) \}
)(.*?)(    return \(\) => es\.close\(\))"
    if re.search(pattern, src, re.DOTALL):
        src = re.sub(pattern, r"\1", src, flags=re.DOTALL)
        with open('E:/AIBRIDGE_Claude/frontend/src/pages/EtlAgent.jsx', 'w', encoding='utf-8') as f:
            f.write(src)
        print("Fixed via regex")
    else:
        print("ERROR: could not find duplicate block")
        # Show what's around the return statement
        idx = src.find("return () => { clearInterval(flushTimer); es.close() }")
        if idx > 0:
            print("Context:", repr(src[idx:idx+300]))
