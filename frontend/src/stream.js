export async function consumeStream(response, onEvent) {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail || 'The trail desk is temporarily unavailable. Please retry.')
  }
  if (!response.body) throw new Error('Streaming is unavailable in this browser.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let received = false
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (line.trim()) {
          const event = JSON.parse(line)
          onEvent(event)
          if (event.type === 'result' || event.type === 'error') received = true
        }
      }
      if (done) break
    }
    if (buffer.trim()) {
      const event = JSON.parse(buffer)
      onEvent(event)
      if (event.type === 'result' || event.type === 'error') received = true
    }
    if (!received) throw new Error('The connection ended before a result was confirmed. Retry this request.')
  } finally {
    reader.releaseLock()
  }
}

export function safeTrackingUrl(value) {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && url.hostname === 'tools.usps.com' && url.pathname === '/go/TrackConfirmAction' ? url.href : null
  } catch { return null }
}
