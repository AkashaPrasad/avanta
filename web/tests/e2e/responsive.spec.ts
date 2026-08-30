import { test, expect, type Page } from '@playwright/test'
import { ALL_ROUTES, ROUTES, gotoReady, jobRouter, settle, stubApi, stubMapTiles } from './fixtures'

/** Layout integrity at every viewport the suite runs.
 *
 *  The three projects in playwright.config.ts run this file at 1440x900,
 *  1024x768 and 768x1024, so each assertion below is made three times. Two
 *  things are checked: the page must not scroll sideways, and nothing laid out
 *  on it may stick out past the right edge unless a container is deliberately
 *  clipping or scrolling it.
 */

test.beforeEach(async ({ page }) => {
  await stubMapTiles(page)
  await stubApi(page, { job: jobRouter })
})

for (const name of ALL_ROUTES) {
  test(`${name} (${ROUTES[name]}) fits the viewport`, async ({ page }, testInfo) => {
    await gotoReady(page, name)
    await expectNoHorizontalScroll(page, `${name} @ ${describeViewport(testInfo.project.use)}`)
    await expectNothingOverflowsWidth(page, `${name} @ ${describeViewport(testInfo.project.use)}`)
  })
}

test('the evidence drawer fits the viewport', async ({ page }, testInfo) => {
  await gotoReady(page, 'attribution')
  await page.getByTestId('open-evidence').click()
  await expect(page.getByTestId('evidence-drawer')).toBeVisible()
  await settle(page)

  const label = `evidence drawer @ ${describeViewport(testInfo.project.use)}`
  await expectNoHorizontalScroll(page, label)
  await expectNothingOverflowsWidth(page, label)
})

test('the shortcuts dialog fits the viewport', async ({ page }, testInfo) => {
  await gotoReady(page, 'watch')
  await page.getByRole('button', { name: 'Keyboard shortcuts' }).click()
  await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeVisible()
  await settle(page)

  const label = `shortcuts dialog @ ${describeViewport(testInfo.project.use)}`
  await expectNoHorizontalScroll(page, label)
  await expectNothingOverflowsWidth(page, label)
})

test('the OOSA handoff panel fits the viewport', async ({ page }, testInfo) => {
  await gotoReady(page, 'dossier')
  await page.getByRole('button', { name: 'OOSA HANDOFF' }).click()
  await expect(page.getByTestId('oosa-handoff')).toBeVisible()
  await settle(page)

  const label = `oosa handoff @ ${describeViewport(testInfo.project.use)}`
  await expectNoHorizontalScroll(page, label)
  await expectNothingOverflowsWidth(page, label)
})

function describeViewport(use: { viewport?: { width: number; height: number } | null }): string {
  const viewport = use.viewport
  return viewport ? `${viewport.width}x${viewport.height}` : 'default viewport'
}

async function expectNoHorizontalScroll(page: Page, where: string) {
  const measurement = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement
    return {
      scrollWidth: root.scrollWidth,
      clientWidth: root.clientWidth,
      bodyScrollWidth: document.body.scrollWidth,
      bodyClientWidth: document.body.clientWidth,
    }
  })

  expect(
    measurement.scrollWidth,
    `${where}: the document scrolls sideways ` +
      `(scrollWidth ${measurement.scrollWidth} > clientWidth ${measurement.clientWidth})`,
  ).toBeLessThanOrEqual(measurement.clientWidth + 1)

  expect(
    measurement.bodyScrollWidth,
    `${where}: the body scrolls sideways ` +
      `(scrollWidth ${measurement.bodyScrollWidth} > clientWidth ${measurement.bodyClientWidth})`,
  ).toBeLessThanOrEqual(measurement.bodyClientWidth + 1)
}

async function expectNothingOverflowsWidth(page: Page, where: string) {
  const offenders = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth
    const clipped = (element: Element): boolean => {
      const overflowX = window.getComputedStyle(element).overflowX
      return overflowX === 'hidden' || overflowX === 'clip' || overflowX === 'auto' ||
        overflowX === 'scroll'
    }

    const out: { html: string; left: number; right: number; width: number; viewportWidth: number }[] = []
    for (const element of Array.from(document.body.querySelectorAll('*'))) {
      const style = window.getComputedStyle(element)
      if (style.display === 'none' || style.visibility === 'hidden') continue
      const rect = element.getBoundingClientRect()
      if (rect.width === 0 && rect.height === 0) continue
      if (rect.right <= viewportWidth + 1 && rect.left >= -1) continue

      // An element wider than its container is only a layout break when
      // nothing between it and the page is clipping or scrolling it.
      let contained = false
      for (let parent = element.parentElement; parent !== null && parent !== document.body;
           parent = parent.parentElement) {
        if (clipped(parent)) {
          contained = true
          break
        }
      }
      if (contained) continue

      const attributes = Array.from(element.attributes)
        .filter((a) => ['class', 'id', 'data-testid', 'role'].includes(a.name))
        .map((a) => `${a.name}="${a.value.slice(0, 90)}"`)
        .join(' ')
      out.push({
        html: `<${element.tagName.toLowerCase()} ${attributes}>`,
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
        viewportWidth,
      })
    }
    return out
  })

  expect(
    offenders,
    `${where}: ${offenders.length} element(s) extend past the viewport:\n` +
      offenders
        .map((o) => `  ${o.html}\n    left ${o.left}, right ${o.right}, width ${o.width}, viewport ${o.viewportWidth}`)
        .join('\n'),
  ).toEqual([])
}
