import { test } from 'node:test'
import assert from 'node:assert/strict'
import { consumeStream, safeTrackingUrl } from '../src/stream.js'

test('stream handles arbitrary chunks and split UTF-8', async () => {
  const bytes = new TextEncoder().encode('{"type":"phase"}\n{"type":"result","text":"山峰🏔️"}\n')
  let offset = 0
  const body = new ReadableStream({ pull(controller) {
    if (offset >= bytes.length) return controller.close()
    controller.enqueue(bytes.slice(offset, offset += 3))
  } })
  const events = []
  await consumeStream(new Response(body), event => events.push(event))
  assert.equal(events[1].text, '山峰🏔️')
})

test('unterminated stream without a final result is a retryable error', async () => {
  await assert.rejects(consumeStream(new Response('{"type":"phase"}\n'), () => {}), /before a result/)
})

test('tracking links restrict protocol, host, and path', () => {
  assert.ok(safeTrackingUrl('https://tools.usps.com/go/TrackConfirmAction?tLabels=TRK123'))
  for (const url of ['javascript:alert(1)', 'https://evil.example', 'https://tools.usps.com.evil.example/go/TrackConfirmAction', 'http://tools.usps.com/go/TrackConfirmAction', 'https://tools.usps.com/admin']) assert.equal(safeTrackingUrl(url), null)
})
