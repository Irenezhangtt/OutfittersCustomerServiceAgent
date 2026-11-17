import { test, expect } from '@playwright/test'

async function send(page, message) {
  const field = page.getByRole('textbox', { name: 'Message Sierra' })
  await field.fill(message)
  await page.getByRole('button', { name: 'Send message', exact: true }).click()
  await expect(field).toBeEnabled()
}

test('guest can track and find grounded gear, without console errors', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('textbox', { name: 'Message Sierra' })).toBeEnabled()
  await send(page, 'Track #W001 for explorer01@example.com')
  await expect(page.getByRole('link', { name: 'Track with USPS' })).toHaveAttribute('href', /tools.usps.com/)
  await send(page, '推荐适合徒步的防雨背包')
  await expect(page.getByRole('heading', { name: "Bhavish's Backcountry Blaze Backpack" })).toBeVisible()
  await expect(page.getByText('防风雨材料', { exact: true })).toBeVisible()
  await expect(page.locator('.evidence')).toHaveCount(2)
  expect(errors).toEqual([])
})

test('demo login supports order actions and real local handoff', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'Sign in to a demo account' }).click()
  await page.getByRole('button', { name: 'Sign in & start a private chat' }).click()
  await expect(page.getByText('Demo Explorer 01', { exact: true })).toBeVisible()
  await send(page, 'Track #DEMO001')
  await expect(page.locator('.order-card')).toContainText('#DEMO001')
  await send(page, 'Cancel order #DEMO001')
  await expect(page.locator('.message.assistant').last()).toContainText(/cancelled/)
  await send(page, 'I need a human representative')
  await expect(page.locator('.ticket-card')).toContainText('SIERRA-')
  await page.reload()
  await expect(page.getByText('Demo Explorer 01', { exact: true })).toBeVisible()
  await send(page, 'Track my order')
  await expect(page.locator('.message.assistant').last()).toContainText('cancelled')
})

test('mobile layout has no horizontal overflow and the composer works', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('textbox', { name: 'Message Sierra' })).toBeEnabled()
  await send(page, 'Recommend a hiking backpack')
  await expect(page.locator('.product-card')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  expect(overflow).toBe(false)
})
