import { test, expect, type Page } from '@playwright/test'
import { ALL_ROUTES, ROUTES, gotoReady, jobRouter, settle, stubApi, stubMapTiles } from './fixtures'

/** Keyboard-only operation.
 *
 *  No mouse is used anywhere in this file. An analyst working a queue with
 *  both hands on the keyboard has to be able to skip the chrome, learn the
 *  shortcuts, move the selection, and reach every control — and every control
 *  they reach has to announce what it is.
 */

test.beforeEach(async ({ page }) => {
  await stubMapTiles(page)
  await stubApi(page, { job: jobRouter })
})

test('the first Tab reaches the skip link', async ({ page }) => {
  await gotoReady(page, 'watch')
  await page.locator('body').press('Tab')

  const focused = page.locator(':focus')
  await expect(focused).toHaveText('Skip to investigation console')
  await expect(focused).toHaveAttribute('href', '#main')
  // It has to be on screen once focused, not merely present.
  await expect(focused).toBeInViewport()

  const box = await focused.boundingBox()
  expect(box, 'the focused skip link must be laid out on screen').not.toBeNull()
  expect(box!.y).toBeGreaterThanOrEqual(0)

  // Following it moves the reading position to the console itself.
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/#main$/)
  await expect(page.locator('#main')).toBeVisible()
})

test('? opens the shortcuts dialog and Escape closes it', async ({ page }) => {
  await gotoReady(page, 'watch')

  const dialog = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  await expect(dialog).toHaveCount(0)

  await page.keyboard.press('?')
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('Command reference')
  await expect(dialog).toContainText('J / K')

  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

test('the shortcuts dialog is also reachable and dismissable without ?', async ({ page }) => {
  await gotoReady(page, 'watch')

  const trigger = page.getByRole('button', { name: 'Keyboard shortcuts' })
  await trigger.focus()
  await page.keyboard.press('Enter')

  const dialog = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  await expect(dialog).toBeVisible()

  // Focus lands inside the dialog, so a keyboard user is not stranded outside it.
  await expect(dialog.getByRole('button', { name: 'Close keyboard shortcuts' })).toBeFocused()

  await page.keyboard.press('Enter')
  await expect(dialog).toHaveCount(0)
})

test('J and K move the alert-queue selection', async ({ page }) => {
  await gotoReady(page, 'watch')

  const rows = page.getByTestId('alert-row')
  await expect(rows).toHaveCount(2)

  // The selection starts on the newest record and is exposed to assistive
  // technology, not carried only in a colour.
  await expect(rows.nth(0)).toHaveAttribute('aria-current', 'true')
  await expect(rows.nth(1)).not.toHaveAttribute('aria-current', 'true')

  await page.keyboard.press('j')
  await expect(rows.nth(1)).toHaveAttribute('aria-current', 'true')
  await expect(rows.nth(0)).not.toHaveAttribute('aria-current', 'true')
  await expect(rows.nth(1)).toHaveClass(/is-selected/)

  // J stops at the end of the queue rather than wrapping or going out of range.
  await page.keyboard.press('j')
  await expect(rows.nth(1)).toHaveAttribute('aria-current', 'true')

  await page.keyboard.press('k')
  await expect(rows.nth(0)).toHaveAttribute('aria-current', 'true')
  await expect(rows.nth(1)).not.toHaveAttribute('aria-current', 'true')

  await page.keyboard.press('k')
  await expect(rows.nth(0)).toHaveAttribute('aria-current', 'true')
})

test('Enter opens the selected record', async ({ page }) => {
  await gotoReady(page, 'watch')
  await expect(page.getByTestId('alert-row')).toHaveCount(2)

  await page.keyboard.press('j')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/scene\/e2e5cene00000002$/)
})

for (const name of ALL_ROUTES) {
  test(`every interactive control on ${name} (${ROUTES[name]}) has an accessible name`, async ({
    page,
  }) => {
    await gotoReady(page, name)
    await expectEveryControlNamed(page, name)
  })
}

test('every control in the shortcuts dialog has an accessible name', async ({ page }) => {
  await gotoReady(page, 'watch')
  await page.keyboard.press('?')
  await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeVisible()
  await settle(page)
  await expectEveryControlNamed(page, 'shortcuts dialog')
})

test('every control in the evidence drawer has an accessible name', async ({ page }) => {
  await gotoReady(page, 'attribution')
  await page.getByTestId('open-evidence').focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('evidence-drawer')).toBeVisible()
  await settle(page)
  await expectEveryControlNamed(page, 'evidence drawer')
})

/** Every control that can be operated must say what it does.
 *
 *  The name is computed the way a screen reader computes it, in the page:
 *  aria-labelledby, then aria-label, then the element's own text (with image
 *  alternatives folded in), then a label element, then title/value. */
async function expectEveryControlNamed(page: Page, where: string) {
  const unnamed = await page.evaluate(() => {
    const SELECTOR = [
      'a[href]',
      'button',
      'input:not([type="hidden"])',
      'select',
      'textarea',
      'summary',
      '[role="button"]',
      '[role="link"]',
      '[role="checkbox"]',
      '[role="tab"]',
      '[tabindex]:not([tabindex="-1"])',
    ].join(',')

    const visible = (element: Element): boolean => {
      const style = window.getComputedStyle(element)
      if (style.display === 'none' || style.visibility === 'hidden') return false
      if (element.closest('[aria-hidden="true"]') !== null) return false
      const rect = element.getBoundingClientRect()
      return rect.width > 0 || rect.height > 0
    }

    const textOf = (element: Element): string => {
      let out = ''
      for (const node of Array.from(element.childNodes)) {
        if (node.nodeType === Node.TEXT_NODE) {
          out += node.textContent ?? ''
        } else if (node.nodeType === Node.ELEMENT_NODE) {
          const child = node as Element
          if (child.getAttribute('aria-hidden') === 'true') continue
          const label = child.getAttribute('aria-label')
          if (label) {
            out += ` ${label} `
            continue
          }
          if (child.tagName === 'IMG') {
            out += ` ${child.getAttribute('alt') ?? ''} `
            continue
          }
          if (child.tagName === 'SVG' || child.tagName === 'svg') {
            const title = child.querySelector('title')
            out += title ? ` ${title.textContent ?? ''} ` : ''
            continue
          }
          out += textOf(child)
        }
      }
      return out
    }

    const accessibleName = (element: Element): string => {
      const labelledBy = element.getAttribute('aria-labelledby')
      if (labelledBy) {
        const named = labelledBy
          .split(/\s+/)
          .map((id) => document.getElementById(id)?.textContent ?? '')
          .join(' ')
          .trim()
        if (named) return named
      }
      const label = element.getAttribute('aria-label')
      if (label && label.trim()) return label.trim()

      const own = textOf(element).replace(/\s+/g, ' ').trim()
      if (own) return own

      if (element instanceof HTMLInputElement || element instanceof HTMLSelectElement ||
          element instanceof HTMLTextAreaElement) {
        const id = element.getAttribute('id')
        const explicit = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null
        const wrapping = element.closest('label')
        const labelText = (explicit?.textContent ?? wrapping?.textContent ?? '').trim()
        if (labelText) return labelText
        if (element instanceof HTMLInputElement) {
          if ((element.type === 'button' || element.type === 'submit') && element.value.trim()) {
            return element.value.trim()
          }
          if (element.placeholder?.trim()) return element.placeholder.trim()
        }
      }

      const title = element.getAttribute('title')
      if (title && title.trim()) return title.trim()
      return ''
    }

    const describe = (element: Element): string => {
      const attrs = Array.from(element.attributes)
        .filter((a) => ['class', 'id', 'data-testid', 'type', 'href', 'role'].includes(a.name))
        .map((a) => `${a.name}="${a.value.slice(0, 80)}"`)
        .join(' ')
      return `<${element.tagName.toLowerCase()} ${attrs}>`
    }

    return Array.from(document.querySelectorAll(SELECTOR))
      .filter(visible)
      .filter((element) => accessibleName(element) === '')
      .map(describe)
  })

  expect(
    unnamed,
    `${where}: ${unnamed.length} interactive control(s) with no accessible name:\n` +
      unnamed.map((html) => `  ${html}`).join('\n'),
  ).toEqual([])
}
