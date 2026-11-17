import { useEffect, useRef, useState } from 'react'
import { consumeStream, safeTrackingUrl } from './stream.js'

function Icon({ name = 'mountain', size = 22, ...props }) {
  const paths = {
    mountain: <><path d="m2 20 7-13 4 7 3-5 6 11H2Z"/><path d="m6 13 3 2 2-4m3 2 2 2 2-2"/></>,
    box: <><path d="m3 7 9-5 9 5v11l-9 4-9-4V7Z"/><path d="m3 7 9 5 9-5M12 12v10M8 4l9 5"/></>,
    compass: <><circle cx="12" cy="12" r="9"/><path d="m16 8-3 5-5 3 3-5 5-3Z"/></>,
    sun: <><circle cx="12" cy="12" r="4"/><path d="M12 1v2m0 18v2M1 12h2m18 0h2M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2"/></>,
    arrow: <><path d="M4 12h15m-6-6 6 6-6 6"/></>,
    send: <><path d="m12 4 7 8-7-3-7 3 7-8Zm0 5v11"/></>,
    shield: <><path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4Z"/><path d="m8 12 3 3 5-6"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    check: <path d="m5 12 4 4 10-10"/>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/></>,
    chat: <path d="M21 11a9 9 0 0 1-9 9 10 10 0 0 1-4-1l-5 2 1-5a10 10 0 0 1-1-4 9 9 0 0 1 18-1Z"/>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>
}

const quickActions = [
  { icon: 'box', title: 'Track an order', note: 'Follow your gear’s journey', message: 'Help me track my order' },
  { icon: 'compass', title: 'Find my next essential', note: 'Gear for wherever you’re headed', message: 'Recommend a weatherproof backpack for hiking' },
  { icon: 'sun', title: 'Early birds, better trails', note: 'Check the 10% Early Risers offer', message: 'I want to claim the Early Risers Promotion' },
]

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers } })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The request could not be completed.')
  return data
}

function Evidence({ results }) {
  const rows = [...new Map(results.flatMap(r => r.evidence).map(e => [e.id, e])).values()]
  if (!rows.length) return null
  return <details className="evidence"><summary><Icon name="shield" size={13}/> Grounded in {rows.length} source{rows.length > 1 ? 's' : ''}</summary>
    <div className="source-list">{rows.map(row => <div key={row.id}><strong>{row.label}</strong><pre>{JSON.stringify(row.facts, null, 2)}</pre></div>)}</div>
  </details>
}

function BusinessCards({ results, send, busy }) {
  return results.map((result, index) => <div key={`${result.workflow}-${index}`}>
    {result.data?.order_number && <div className="order-card">
      <div className="order-top"><span><Icon name="box" size={18}/> {result.data.order_number}</span><span className={`state state-${result.data.state}`}>{result.data.status_label}</span></div>
      {result.data.demo_fixture && <small>Synthetic fixture · demo order</small>}
      <div className="order-items">{result.data.product_skus?.join(' · ')}</div>
      {safeTrackingUrl(result.data.tracking_url) && <a className="tracking-link" href={safeTrackingUrl(result.data.tracking_url)} target="_blank" rel="noopener noreferrer">Track with USPS <Icon name="arrow" size={16}/></a>}
    </div>}
    {result.data?.products?.map(product => <article className="product-card" key={product.sku}>
      <div className="product-illustration"><Icon name={product.tags.includes('Backpack') ? 'box' : 'compass'} size={36}/><span>SIERRA / GEAR</span></div>
      <div className="product-content"><div className="product-meta">{product.sku}<span>{product.inventory} in stock</span></div><h3>{product.name}</h3><p>{product.description}</p>
      <div className="feature-tags">{(product.features.length ? product.features : product.tags.slice(0, 3)).map(tag => <span key={tag}>{tag}</span>)}</div></div>
    </article>)}
    {result.data?.code && <div className="coupon-card"><Icon name="sun" size={28}/><div><span>EARLY RISERS · 10% OFF</span><code>{result.data.code}</code><small>Saved to your demo account · checkout not connected</small></div></div>}
    {result.data?.reference && <div className="ticket-card"><Icon name="chat" size={20}/><div><strong>{result.data.reference}</strong><span>Saved locally · awaiting human review</span></div></div>}
    {!!result.actions?.length && <div className="inline-actions">{result.actions.map(action => <button disabled={busy} key={action.message} onClick={() => send(action.message)}>{action.label}<Icon name="arrow" size={15}/></button>)}</div>}
  </div>)
}

export default function App() {
  const [session, setSession] = useState(null)
  const [health, setHealth] = useState(null)
  const [accounts, setAccounts] = useState([])
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [phase, setPhase] = useState('')
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(null)
  const [showLogin, setShowLogin] = useState(false)
  const [email, setEmail] = useState('explorer01@example.com')
  const [password, setPassword] = useState('trail-demo')
  const [tickets, setTickets] = useState([])
  const [memory, setMemory] = useState(null)
  const end = useRef(null)
  const sending = useRef(false)
  const inputRef = useRef(null)

  useEffect(() => {
    let live = true
    async function initialize() {
      try {
        const s = await api('/api/session')
        if (!live) return
        setSession(s)
        setMessages(s.messages.map((m, i) => ({ ...m, id: `restored-${i}` })))
        if (s.demo_mode) setAccounts(await api('/api/demo/accounts'))
        setHealth(await api('/api/health'))
        setTickets(await api('/api/tickets'))
      } catch (e) { if (live) setError(e.message) }
    }
    initialize()
    return () => { live = false }
  }, [])

  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages, busy])

  async function send(text, existingRequest) {
    const content = text.trim()
    if (!content || sending.current || !session) return
    sending.current = true
    const request = existingRequest || { message: content, request_id: crypto.randomUUID() }
    setBusy(true); setError(''); setRetry(null); setInput(''); setPhase('Checking records and permissions…')
    if (!existingRequest) setMessages(current => [...current, { role: 'user', content, id: request.request_id }])
    let failure = null
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15000)
    try {
      const response = await fetch('/api/chat/stream', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request), signal: controller.signal })
      await consumeStream(response, event => {
        if (event.type === 'phase') setPhase(event.detail)
        if (event.type === 'error') failure = new Error(event.detail)
        if (event.type === 'result') {
          setMessages(current => [...current.filter(m => m.id !== `reply-${request.request_id}`), { role: 'assistant', content: event.data.text, reply: event.data, id: `reply-${request.request_id}` }])
          setMemory(event.data.memory)
        }
      })
      if (failure) throw failure
      setTickets(await api('/api/tickets'))
      setHealth(await api('/api/health'))
    } catch (e) {
      setError(e.name === 'AbortError' ? 'The connection timed out. Retry the same request to check its result safely.' : e.message)
      setRetry(request)
    } finally { clearTimeout(timeout); setBusy(false); sending.current = false; setPhase(''); inputRef.current?.focus() }
  }

  async function login(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError('')
    try {
      const s = await api('/api/auth/demo', { method: 'POST', body: JSON.stringify({ email, password }) })
      setSession(s); setMessages([]); setTickets([]); setMemory(null); setRetry(null); setShowLogin(false)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function reset(logout = false) {
    if (busy || !session) return
    setBusy(true); setError('')
    try {
      const s = await api(logout ? '/api/auth/logout' : '/api/session/reset', { method: 'POST' })
      setSession(s); setMessages([]); setTickets([]); setMemory(null); setRetry(null)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const pacific = health?.pacific_time ? new Intl.DateTimeFormat('en-US', { timeZone: 'America/Los_Angeles', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(new Date(health.pacific_time)) : 'Pacific Time'

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Sierra Outfitters home"><div className="brand-mark"><Icon size={31}/></div><div>SIERRA<span>OUTFITTERS</span></div></a>
      <div className="sidebar-section-label">YOUR BASECAMP</div>
      <button className="nav-item active"><Icon name="chat" size={19}/> Trail desk <span className="nav-dot"/></button>
      <button className="nav-item" onClick={() => send('Help me track my order')} disabled={busy || !session}><Icon name="box" size={19}/> Orders & returns</button>
      <button className="nav-item" onClick={() => send('Recommend a weatherproof backpack for hiking')} disabled={busy || !session}><Icon name="compass" size={19}/> Discover your gear</button>
      <button className="new-chat" onClick={() => reset()} disabled={busy || !session}><Icon name="plus" size={16}/> Start a new conversation</button>
      <div className="sidebar-bottom"><div className="topo"><svg viewBox="0 0 220 110" fill="none" aria-hidden="true"><path d="M-20 100C30 20 60 130 100 60S180 20 250 90M-20 85C30 5 60 115 100 45S180 5 250 75M-20 70C30-10 60 100 100 30S180-10 250 60M-20 55C30-25 60 85 100 15S180-25 250 45M-20 40C30-40 60 70 100 0S180-40 250 30"/></svg><Icon size={27}/><p>Good gear. Open skies.<br/>A little help along the way.</p></div>
      <div className="account"><div className="avatar"><Icon name="user" size={18}/></div><div><strong>{session?.customer?.name || 'Guest explorer'}</strong><span>{session?.authenticated ? 'Demo account verified' : 'Browsing as a guest'}</span></div></div>
      {session?.demo_mode && <button className="account-button" disabled={busy} onClick={() => session.authenticated ? reset(true) : setShowLogin(v => !v)}>{session.authenticated ? 'Sign out' : 'Sign in to a demo account'} <Icon name="arrow" size={15}/></button>}</div>
    </aside>

    <main className="main">
      <header className="topbar"><div className="breadcrumb">Sierra support <span>/</span> <strong>Your trail desk</strong></div><div className="topbar-status"><span className={health ? 'online-dot' : 'offline-dot'}/>{health ? 'Here to help' : 'Connecting…'}<span className="demo-badge">{session?.demo_mode ? 'DEMO' : 'MVP'}</span></div></header>
      <div className="workspace">
        <section className="conversation-area">
          <div className="intro"><div className="eyebrow"><span/> YOUR NEXT ADVENTURE STARTS HERE</div><h1>A little help for<br/>the great outdoors<span>.</span></h1><p>Track your gear, find your next essential, or sort out the details.<br className="desktop-break"/> We’re here to keep your adventure moving.</p></div>
          <div className="quick-actions">{quickActions.map(action => <button key={action.title} onClick={() => send(action.message)} disabled={busy || !session}><span className="quick-icon"><Icon name={action.icon}/></span><strong>{action.title}</strong><span>{action.note}</span><Icon name="arrow" size={17}/></button>)}</div>
          <section className="chat-panel" aria-label="Customer service conversation">
            <div className="chat-heading"><div className="assistant-mark"><Icon size={22}/></div><div><strong>Sierra adventure assistant</strong><span>Your guide to the details</span></div><span className="chat-heading-tag">English / 中文</span></div>
            <div className="messages" role="log" aria-live="polite" aria-relevant="additions">
              <div className="message assistant welcome"><div className="message-avatar"><Icon size={17}/></div><div className="message-body"><div className="message-author">SIERRA</div><p>Hey, explorer. 🏔️ What can I help you with today?</p><p className="muted">Share an order number and email, tell me what you’re looking for, or ask about our Early Risers offer.</p></div></div>
              {messages.map(message => <div className={`message ${message.role}`} key={message.id}>{message.role === 'assistant' && <div className="message-avatar"><Icon size={17}/></div>}<div className="message-body"><div className="message-author">{message.role === 'user' ? 'YOU' : 'SIERRA'}</div><p>{message.content}</p>{message.reply && <><BusinessCards results={message.reply.results} send={send} busy={busy}/><div className="reply-meta"><Icon name="check" size={12}/> Verified against records <span>·</span> {message.reply.latency_ms.toFixed(0)} ms</div><Evidence results={message.reply.results}/></>}</div></div>)}
              {busy && phase && <div className="working"><span/><span/><span/><p>{phase}</p></div>}
              <div ref={end}/>
            </div>
            {error && <div className="error" role="alert">{error}{retry && <button onClick={() => send(retry.message, retry)} disabled={busy}>Retry safely</button>}</div>}
            <form className="composer" onSubmit={event => { event.preventDefault(); send(input) }}><textarea ref={inputRef} value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(input) } }} placeholder="Ask away. Where are we headed? / 请输入你的问题" aria-label="Message Sierra" maxLength={3000} rows={2} disabled={busy || !session}/><button aria-label="Send message" disabled={busy || !input.trim() || !session}><Icon name="send" size={20}/></button></form>
            <div className="composer-note"><Icon name="shield" size={12}/> Your account stays private. Answers stay grounded.</div>
          </section>
          <footer className="main-footer">Built for the journey. <Icon size={13}/> Sierra Outfitters <span>Simulated order actions · no payments processed</span></footer>
        </section>

        <aside className="context-panel">
          <div className="field-note"><div className="field-note-label">A NOTE FROM BASECAMP</div><Icon size={42}/><h2>Less planning.<br/>More exploring.</h2><p>We’ll take care of the small details, so you can focus on the big views.</p><div className="field-note-line"/></div>
          <div className="context-block"><div className="context-title"><Icon name="sun" size={18}/><h3>Early Risers</h3></div><p>A little reward for an early start.</p><div className="offer-number">10<span>% OFF</span></div><p>8–10 AM Pacific · once per account</p><div className="time-chip"><span/> {pacific}</div></div>
          <div className="context-block"><div className="context-title"><Icon name="shield" size={17}/><h3>On this trail</h3></div><ul className="trail-list"><li><span>01</span> Order status & tracking</li><li><span>02</span> Cancellation & return requests</li><li><span>03</span> Catalogue-based gear advice</li><li><span>04</span> Early Risers promotion</li></ul></div>
          <div className="context-block demo-guide"><h3>Try the demo</h3><p>Sign in as Demo Explorer 01, then try:</p><button disabled={busy || !session} onClick={() => send('Track order #W001 for explorer01@example.com')}>#W001 · delivered <Icon name="arrow" size={13}/></button><button disabled={busy || !session} onClick={() => send('Track order #DEMO001 for explorer01@example.com')}>#DEMO001 · placed fixture <Icon name="arrow" size={13}/></button><small>Demo password: trail-demo<br/>Signing in starts a private conversation.</small></div>
          {!!tickets.length && <div className="context-block"><h3>Support tickets</h3>{tickets.map(ticket => <div className="ticket-mini" key={ticket.reference}><strong>{ticket.reference}</strong><span>{ticket.status} · saved locally</span></div>)}</div>}
          {memory && <div className="memory-note"><Icon name="check" size={13}/>{memory.recent_messages} recent messages · {memory.compacted_messages} compacted</div>}
        </aside>
      </div>
    </main>

    {showLogin && <div className="modal-backdrop" onClick={() => !busy && setShowLogin(false)}><section role="dialog" aria-modal="true" aria-labelledby="login-title" className="login-modal" onClick={event => event.stopPropagation()}><div className="assistant-mark"><Icon size={26}/></div><h2 id="login-title">Welcome to basecamp.</h2><p>Use a synthetic demo account to test order actions and promotion claims. This is not production authentication.</p><form onSubmit={login}><label>Demo account<select value={email} onChange={event => setEmail(event.target.value)}>{accounts.map(account => <option value={account.email} key={account.email}>{account.name} · {account.email}</option>)}</select></label><label>Demo password<input type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="off"/></label><button className="primary-button" disabled={busy}>Sign in & start a private chat<Icon name="arrow" size={18}/></button><button type="button" className="text-button" onClick={() => setShowLogin(false)}>Keep exploring as a guest</button></form></section></div>}
  </div>
}
