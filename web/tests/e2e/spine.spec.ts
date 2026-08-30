import { test, expect, type Page } from '@playwright/test'
import {
  SCENE_ID,
  RUN_ID,
  TOP_MMSI,
  jobRouter,
  parseSignedNumber,
  stubApi,
  stubMapTiles,
  expectNoRenderedJunk,
} from './fixtures'

/** The narrative path: Watch → Detect → Attribute → Evidence → Dossier.
 *
 *  The API is stubbed at the HTTP boundary so the run is deterministic and
 *  never opens a satellite, AIS or reanalysis connection. Everything above
 *  that boundary — routing, rendering, state, the arithmetic the evidence
 *  panel claims to show — is the real application.
 */

test.beforeEach(async ({ page }) => {
  await stubMapTiles(page)
  await stubApi(page, { job: jobRouter })
})

test.describe('spine', () => {
  test('Watch renders the scenario deck, its provenance badges and the alert queue', async ({ page }) => {
    await page.goto('/')

    const deck = page.getByTestId('scenario-list')
    await expect(deck).toBeVisible()
    await expect(deck.getByRole('heading', { name: 'Run demo scenario' })).toBeVisible()

    // Three scenarios, each addressable by its own id.
    await expect(page.getByTestId('run-scenario-elsa3')).toBeVisible()
    await expect(page.getByTestId('run-scenario-live')).toBeVisible()
    await expect(page.getByTestId('run-scenario-synthetic-discharge')).toBeVisible()
    await expect(deck.locator('button.scenario-trigger')).toHaveCount(3)

    // Every scenario declares where its data comes from. A validation replay is
    // CACHED, the live pass is LIVE, the generated case is SYNTHETIC — the
    // analyst never has to guess whether a number is an observation.
    await expect(
      page.getByTestId('run-scenario-elsa3').getByTestId('mode-badge-CACHED'),
    ).toBeVisible()
    await expect(page.getByTestId('run-scenario-live').getByTestId('mode-badge-LIVE')).toBeVisible()
    await expect(
      page.getByTestId('run-scenario-synthetic-discharge').getByTestId('mode-badge-SYNTHETIC'),
    ).toBeVisible()
    await expect(deck.locator('[data-testid^="mode-badge-"]')).toHaveCount(3)

    // The alert queue.
    const rows = page.getByTestId('alert-row')
    await expect(rows).toHaveCount(2)
    await expect(rows.first()).toContainText('synthetic-discharge')
    await expect(rows.first()).toContainText('slick')

    await expectNoRenderedJunk(page, 'watch')
  })

  test('running a scenario drives Watch → Scene with a wind gate, regions and the primary action', async ({
    page,
  }) => {
    await page.goto('/')
    await expect(page.getByTestId('scenario-list')).toBeVisible()

    await page.getByTestId('run-scenario-synthetic-discharge').click()

    await expect(page).toHaveURL(new RegExp(`/scene/${SCENE_ID}$`))
    await expectSceneDetail(page)

    await expectNoRenderedJunk(page, 'scene')
  })

  test('the Scene wind gate reports a numeric wind speed and a verdict sentence', async ({ page }) => {
    await page.goto(`/scene/${SCENE_ID}`)
    const gate = page.getByTestId('wind-gate')
    await expect(gate).toBeVisible()

    // A number in m/s, not a word.
    const speed = (await gate.locator('.num').first().innerText()).replace(/\s+/g, ' ').trim()
    expect(speed).toMatch(/^\d+\.\d ?m\/s$/)
    expect(Number(speed.replace(/ ?m\/s$/, ''))).toBeGreaterThan(0)

    // A verdict that says what the number means for the detection.
    const verdict = gate.locator('p').first()
    await expect(verdict).toBeVisible()
    const sentence = (await verdict.innerText()).trim()
    expect(sentence.length).toBeGreaterThan(40)
    expect(sentence).toMatch(/[.!]$/)
    expect(sentence).toContain('m/s')

    // The band it was judged against, and the verdict token.
    await expect(gate).toContainText('3–10')
    await expect(gate).toContainText('PASSED')
  })

  test('Scene explains every detected region and offers the candidate search', async ({ page }) => {
    await page.goto(`/scene/${SCENE_ID}`)
    await expectSceneDetail(page)

    const panel = page.getByTestId('lookalike-panel')
    await expect(panel).toBeVisible()
    await expect(panel.getByRole('button', { expanded: true })).toHaveCount(1)

    // The first region is expanded by default and shows each discriminating
    // feature with its value, threshold and weight.
    await expect(panel).toContainText('Elongation')
    await expect(panel).toContainText('≥')
    await expect(panel).toContainText('×')

    // Collapsing and re-expanding is driven from the accessible expanded state.
    const oilRegion = panel.getByRole('button', { expanded: true })
    await oilRegion.click()
    await expect(panel.getByRole('button', { expanded: true })).toHaveCount(0)

    const find = page.getByTestId('find-candidates')
    await expect(find).toBeVisible()
    await expect(find).toBeEnabled()
    await expect(find).toHaveText(/FIND CANDIDATE VESSELS/)
  })

  test('the candidate search hands off to the attribution run', async ({ page }) => {
    await page.goto(`/scene/${SCENE_ID}`)
    await expectSceneDetail(page)

    await page.getByTestId('find-candidates').click()
    await expect(page).toHaveURL(new RegExp(`/attribution/${RUN_ID}$`))
    await expect(page.getByTestId('candidate-ranking')).toBeVisible()
  })

  test('Attribution ranks the hypotheses and always keeps H0 as a row', async ({ page }) => {
    await page.goto(`/attribution/${RUN_ID}`)

    const ranking = page.getByTestId('candidate-ranking')
    await expect(ranking).toBeVisible()

    await expect(page.getByTestId('candidate-row')).toHaveCount(3)
    const h0 = page.getByTestId('h0-row')
    await expect(h0).toHaveCount(1)
    await expect(h0).toContainText('H0')

    // The headline answer is one sentence with a named vessel and a number.
    const headline = page.getByTestId('attribution-headline')
    await expect(headline).toBeVisible()
    await expect(headline).toContainText('MT ANJALI')
    await expect(headline).toContainText('most probable source')
    await expect(page.getByTestId('no-attribution')).toHaveCount(0)

    // Probabilities are monotonically non-increasing down the list, and H0 is
    // in the list rather than hidden behind the named vessels.
    const probabilities = await readProbabilities(page)
    expect(probabilities.length).toBe(4)
    for (let i = 1; i < probabilities.length; i += 1) {
      expect(probabilities[i]).toBeLessThanOrEqual(probabilities[i - 1] + 1e-9)
    }
    await expect(page.locator('.ranking-console')).toContainText('posterior sums to 1.0000')

    await expectNoRenderedJunk(page, 'attribution')
  })

  test('the evidence drawer opens and its terms sum to the reported score', async ({ page }) => {
    await page.goto(`/attribution/${RUN_ID}`)
    await expect(page.getByTestId('candidate-ranking')).toBeVisible()

    await page.getByTestId('open-evidence').click()

    const drawer = page.getByTestId('evidence-drawer')
    await expect(drawer).toBeVisible()
    await expect(page.getByRole('dialog', { name: /Evidence breakdown for/ })).toBeVisible()
    await expect(drawer).toContainText(`MMSI ${TOP_MMSI}`)

    // The audit-trail invariant: the displayed sum of the terms is the
    // displayed score. If these ever diverge, the panel is decoration.
    const footer = drawer.locator('section', { hasText: 'Contributions to the log score' })
    const numbers = footer.locator('.border-t .num')
    await expect(numbers).toHaveCount(2)
    const shownSum = (await numbers.nth(0).innerText()).trim()
    const shownScore = (await numbers.nth(1).innerText()).trim()
    expect(shownSum).toBe(shownScore)

    // And the individual rows really do add up to it, to their own precision.
    const termValues = (await footer.locator('ul > li .num').allInnerTexts()).map(parseSignedNumber)
    expect(termValues.length).toBeGreaterThanOrEqual(4)
    const total = termValues.reduce((a, b) => a + b, 0)
    expect(Math.abs(total - parseSignedNumber(shownScore))).toBeLessThanOrEqual(
      0.0005 * termValues.length,
    )

    // Escape closes it.
    await page.keyboard.press('Escape')
    await expect(drawer).toHaveCount(0)
  })

  test('an attributed candidate leads to the MARPOL dossier', async ({ page }) => {
    await page.goto(`/attribution/${RUN_ID}`)
    await expect(page.getByTestId('candidate-ranking')).toBeVisible()

    await page.getByTestId('generate-dossier').click()
    await expect(page).toHaveURL(new RegExp(`/dossier/${RUN_ID}/${TOP_MMSI}$`))

    await expect(page.getByRole('heading', { name: /MARPOL Annex I/ })).toBeVisible()
    await expect(page.getByTestId('download-pdf')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Vessel' })).toBeVisible()
    await expect(page.getByText('MT ANJALI').first()).toBeVisible()

    // Fields the analysis could not establish are printed, not omitted.
    await expect(page.getByText('NOT AVAILABLE').first()).toBeVisible()

    await page.getByRole('button', { name: 'OOSA HANDOFF' }).click()
    await expect(page.getByTestId('oosa-handoff')).toBeVisible()
    await expect(page.getByTestId('oosa-handoff')).toContainText('OOSA v4.0 domain')

    await expectNoRenderedJunk(page, 'dossier')
  })

  test('the timeline surface is present on an attribution run', async ({ page }) => {
    await page.goto(`/attribution/${RUN_ID}`)
    const timeline = page.getByTestId('timeline')
    await expect(timeline).toBeVisible()
    await expect(timeline.getByRole('slider', { name: 'Simulation time' })).toBeVisible()
    await expect(timeline.getByRole('button', { name: 'Play' })).toBeEnabled()
    await expect(timeline).toContainText('particles')
  })
})

async function expectSceneDetail(page: Page) {
  await expect(page.getByTestId('wind-gate')).toBeVisible()
  await expect(page.getByText('Detected regions')).toBeVisible()
  await expect(page.getByTestId('lookalike-panel')).toBeVisible()
  await expect(page.getByTestId('find-candidates')).toBeVisible()
}

async function readProbabilities(page: Page): Promise<number[]> {
  const rows = page.locator('[data-testid="candidate-ranking"] > li')
  const count = await rows.count()
  const out: number[] = []
  for (let i = 0; i < count; i += 1) {
    const text = await rows.nth(i).locator('.num.text-sm').first().innerText()
    out.push(parseSignedNumber(text))
  }
  return out
}
