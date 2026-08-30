import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import type { Result } from 'axe-core'
import { ALL_ROUTES, ROUTES, gotoReady, jobRouter, settle, stubApi, stubMapTiles } from './fixtures'

/** Automated accessibility audit.
 *
 *  axe-core over every route in the console. Nothing of impact 'critical' or
 *  'serious' is tolerated; a failure prints the rule id, its help URL and the
 *  exact selector of every offending node, so the report is actionable rather
 *  than a count.
 */

const BLOCKING_IMPACTS = new Set(['critical', 'serious'])

test.beforeEach(async ({ page }) => {
  await stubMapTiles(page)
  await stubApi(page, { job: jobRouter })
})

for (const name of ALL_ROUTES) {
  test(`${name} (${ROUTES[name]}) has no critical or serious accessibility violations`, async ({
    page,
  }) => {
    await gotoReady(page, name)
    await auditPage(page, name)
  })
}

test('the keyboard shortcuts dialog has no critical or serious violations', async ({ page }) => {
  await gotoReady(page, 'watch')
  await page.getByRole('button', { name: 'Keyboard shortcuts' }).click()
  await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeVisible()
  await auditPage(page, 'shortcuts dialog')
})

test('the evidence drawer has no critical or serious violations', async ({ page }) => {
  await gotoReady(page, 'attribution')
  await page.getByTestId('open-evidence').click()
  await expect(page.getByTestId('evidence-drawer')).toBeVisible()
  await auditPage(page, 'evidence drawer')
})

test('the OOSA handoff panel has no critical or serious violations', async ({ page }) => {
  await gotoReady(page, 'dossier')
  await page.getByRole('button', { name: 'OOSA HANDOFF' }).click()
  await expect(page.getByTestId('oosa-handoff')).toBeVisible()
  await auditPage(page, 'oosa handoff')
})

async function auditPage(page: Page, where: string) {
  // Audit the settled interface, not a frame part-way through a fade.
  await settle(page)
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    .analyze()

  const blocking = results.violations.filter((v) => BLOCKING_IMPACTS.has(String(v.impact)))
  // Compare a compact summary so the failure message is the readable report
  // below rather than a thousand lines of serialised axe output.
  const summary = blocking.map((v) => `${v.impact}:${v.id} (${v.nodes.length} node(s))`)
  expect(summary, report(where, blocking)).toEqual([])
}

function report(where: string, violations: Result[]): string {
  if (violations.length === 0) return `${where}: no blocking accessibility violations`
  const lines = [`${where}: ${violations.length} critical/serious accessibility violation(s)`]
  for (const violation of violations) {
    lines.push('')
    lines.push(`  [${violation.impact}] ${violation.id} — ${violation.help}`)
    lines.push(`  ${violation.helpUrl}`)
    for (const node of violation.nodes) {
      lines.push(`    selector: ${JSON.stringify(node.target)}`)
      const summary = (node.failureSummary ?? '').split('\n').filter(Boolean)
      for (const line of summary) lines.push(`      ${line}`)
      lines.push(`      html: ${node.html.slice(0, 220)}`)
    }
  }
  return lines.join('\n')
}
