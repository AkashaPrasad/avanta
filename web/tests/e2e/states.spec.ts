import { test, expect, type Page } from '@playwright/test'
import * as fx from './fixtures'
import {
  ALL_ROUTES,
  ROUTES,
  RUN_ID,
  type Reply,
  type RouteName,
  type StubKey,
  emptyAttribution,
  emptyCalibration,
  emptyDetections,
  expectNoRenderedJunk,
  goto,
  jobRouter,
  noAttribution,
  parseSignedNumber,
  serverError,
  stubApi,
  stubMapTiles,
  waitForRoute,
} from './fixtures'

/** The four async states, forced at the HTTP boundary.
 *
 *  A spinner alone is not a loading state, a blank panel is not an empty
 *  state, and "something went wrong" is not an error state. Each of the four
 *  is asserted for what it actually has to show the analyst, and every route
 *  in every state is scanned for the three placeholder strings that mean a
 *  value reached the screen without ever being formatted.
 */

const ROUTES_WITH_ASYNC_CONTENT: RouteName[] = [
  'watch',
  'scene',
  'attribution',
  'dossier',
  'calibration',
  'about',
]

/** Routes whose failure surface is a real error panel with a retry control. */
const ROUTES_WITH_ERROR_PANEL: RouteName[] = [
  'watch',
  'scene',
  'attribution',
  'dossier',
  'calibration',
]

test.beforeEach(async ({ page }) => {
  await stubMapTiles(page)
})

/* ------------------------------------------------------------------ */
/* 1. Loading                                                          */
/* ------------------------------------------------------------------ */

test.describe('loading state', () => {
  for (const name of ROUTES_WITH_ASYNC_CONTENT) {
    test(`${name} announces that it is loading while the API is in flight`, async ({ page }) => {
      let release!: () => void
      const held = new Promise<void>((resolve) => {
        release = resolve
      })

      await stubApi(page, holdEverything(held))

      await page.goto(ROUTES[name], { waitUntil: 'commit' })

      // A named, announced loading surface — not a bare spinner.
      const status = page.getByRole('status').first()
      await expect(status).toBeVisible()
      await expect(status).toHaveAccessibleName('Loading')
      await expect(page.locator('.skeleton').first()).toBeVisible()

      await expectNoRenderedJunk(page, `${name} (loading)`)

      release()
      await waitForRoute(page, name)
      await expectNoRenderedJunk(page, `${name} (loaded after delay)`)
    })
  }
})

/* ------------------------------------------------------------------ */
/* 2. Empty                                                            */
/* ------------------------------------------------------------------ */

test.describe('empty state', () => {
  test.beforeEach(async ({ page }) => {
    await stubApi(page, {
      job: jobRouter,
      scenarios: { json: { scenarios: [] } },
      scenes: { json: { scenes: [] } },
      detections: { json: emptyDetections() },
      attribution: { json: emptyAttribution() },
      calibration: { json: emptyCalibration() },
      dossier: { json: { run_id: RUN_ID, mmsi: '419000123', fields: {} } },
      candidates: { json: { scene_id: '', mode: 'SYNTHETIC', results: [], dark_contacts: [] } },
    })
  })

  test('the acquisition ledger explains why it is empty rather than showing a blank panel', async ({
    page,
  }) => {
    await goto(page, 'watch')

    const empty = page.getByRole('heading', { name: 'No acquisition records' })
    await expect(empty).toBeVisible()
    // Explanatory copy: what to do about it, not just that there is nothing.
    await expect(page.getByText(/Run a scenario to ingest Sentinel-1 data/)).toBeVisible()
    await expect(page.getByTestId('alert-row')).toHaveCount(0)

    await expectNoRenderedJunk(page, 'watch (empty)')
  })

  test('a scene with no detections says so, and says what that means', async ({ page }) => {
    await goto(page, 'scene')

    await expect(page.getByRole('heading', { name: 'No dark regions in this scene' })).toBeVisible()
    await expect(
      page.getByText(/That is a valid result for a clean scene\./),
    ).toBeVisible()

    // No detections means nothing to attribute, and the interface says why the
    // primary action is unavailable instead of silently disabling it.
    await expect(page.getByTestId('find-candidates')).toBeDisabled()
    await expect(
      page.getByText('Attribution needs a segmented slick to compare simulations against.'),
    ).toBeVisible()

    await expectNoRenderedJunk(page, 'scene (empty)')
  })

  test('a calibration with no populated bins says so', async ({ page }) => {
    await goto(page, 'calibration')

    await expect(page.getByRole('heading', { name: 'No populated bins' })).toBeVisible()
    await expect(
      page.getByText('The validation set produced no predictions in any bin.'),
    ).toBeVisible()

    await expectNoRenderedJunk(page, 'calibration (empty)')
  })

  test('every route survives empty payloads without leaking a placeholder', async ({ page }) => {
    for (const name of ALL_ROUTES) {
      await goto(page, name)
      await expectNoRenderedJunk(page, `${name} (empty)`)
    }
  })
})

/* ------------------------------------------------------------------ */
/* 3. Error                                                            */
/* ------------------------------------------------------------------ */

const REASON = 'Upstream Sentinel Hub returned 503 for product S1A_IW_GRDH_1SDV_20250528T004137.'

test.describe('error state', () => {
  test.beforeEach(async ({ page }) => {
    await stubApi(page, allFail(REASON))
  })

  for (const name of ROUTES_WITH_ERROR_PANEL) {
    test(`${name} reports the real reason and offers a retry`, async ({ page }) => {
      await page.goto(ROUTES[name])

      const alert = page.getByRole('alert').first()
      await expect(alert).toBeVisible()
      // The real reason, not a euphemism.
      await expect(alert).toContainText(REASON)
      await expect(alert.getByRole('button', { name: 'RETRY' })).toBeVisible()
      await expect(alert.getByRole('button', { name: 'RETRY' })).toBeEnabled()

      await expectNoRenderedJunk(page, `${name} (error)`)
    })
  }

  test('the retry control re-issues the request and recovers', async ({ page }) => {
    let fail = true
    await page.unroute('**/api/v1/**')
    await stubApi(page, {
      job: jobRouter,
      calibration: () => (fail ? serverError(REASON) : { json: emptyCalibration() }),
    })

    await page.goto(ROUTES.calibration)
    const alert = page.getByRole('alert').first()
    await expect(alert).toContainText(REASON)

    fail = false
    await alert.getByRole('button', { name: 'RETRY' }).click()

    await expect(page.getByRole('heading', { name: 'Calibration' })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  })

  test('the header declares the backend down rather than pretending', async ({ page }) => {
    await page.goto(ROUTES.about)
    await expect(page.getByTestId('mode-badge-DOWN').first()).toBeVisible()
    await expect(
      page.getByText('The API is unreachable, so the live capability state cannot be shown.'),
    ).toBeVisible()
    await expectNoRenderedJunk(page, 'about (error)')
  })

  test('every route survives a 500 without leaking a placeholder', async ({ page }) => {
    for (const name of ALL_ROUTES) {
      await page.goto(ROUTES[name])
      await waitForRoute(page, name)
      await expectNoRenderedJunk(page, `${name} (error)`)
    }
  })
})

/* ------------------------------------------------------------------ */
/* 4. Success                                                          */
/* ------------------------------------------------------------------ */

test.describe('success state', () => {
  test.beforeEach(async ({ page }) => {
    await stubApi(page, { job: jobRouter })
  })

  test('every route renders its data with no placeholder anywhere on screen', async ({ page }) => {
    for (const name of ALL_ROUTES) {
      await goto(page, name)
      await expectNoRenderedJunk(page, `${name} (success)`)
    }
  })

  test('the evidence drawer renders without a placeholder', async ({ page }) => {
    await goto(page, 'attribution')
    await page.getByTestId('open-evidence').click()
    await expect(page.getByTestId('evidence-drawer')).toBeVisible()
    await expectNoRenderedJunk(page, 'evidence drawer')
  })

  test('the OOSA handoff renders without a placeholder', async ({ page }) => {
    await goto(page, 'dossier')
    await page.getByRole('button', { name: 'OOSA HANDOFF' }).click()
    await expect(page.getByTestId('oosa-handoff')).toBeVisible()
    await expectNoRenderedJunk(page, 'oosa handoff')
  })
})

/* ------------------------------------------------------------------ */
/* 5. No attribution                                                   */
/* ------------------------------------------------------------------ */

test.describe('no-attribution', () => {
  test('when p(H0) exceeds the threshold the console names nobody', async ({ page }) => {
    await stubApi(page, { job: jobRouter, attribution: { json: noAttribution() } })
    await goto(page, 'attribution')

    const nullVerdict = page.getByTestId('no-attribution')
    await expect(nullVerdict).toBeVisible()
    await expect(nullVerdict).toContainText('NO ATTRIBUTION — insufficient evidence')
    await expect(nullVerdict).toContainText('p(unknown source) = 0.634')
    // It says what would resolve the ambiguity, not just that it failed.
    await expect(nullVerdict).toContainText(/wider AIS window/)

    // No vessel is named as the source.
    await expect(page.getByTestId('attribution-headline')).toHaveCount(0)

    // And no route to a dossier is offered for a vessel nobody was named as.
    await expect(page.getByTestId('generate-dossier')).toHaveCount(0)
  })

  test('no vessel is ranked above H0 when the null hypothesis wins', async ({ page }) => {
    await stubApi(page, { job: jobRouter, attribution: { json: noAttribution() } })
    await goto(page, 'attribution')

    const payload = noAttribution()
    expect(payload.posterior.no_attribution).toBe(true)
    expect(payload.posterior.p_null).toBeGreaterThan(0.5)

    const rows = page.locator('[data-testid="candidate-ranking"] > li button')
    await expect(rows).toHaveCount(payload.posterior.entries.length)

    // H0 is the first row on screen: nothing is ranked above it.
    await expect(rows.first()).toHaveAttribute('data-testid', 'h0-row')

    const order = await rows.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute('data-testid')),
    )
    expect(order.indexOf('h0-row')).toBe(0)
    expect(order.slice(1).every((id) => id === 'candidate-row')).toBe(true)

    // And its probability really is the largest one displayed.
    const probabilities = await readProbabilities(page)
    expect(probabilities[0]).toBeGreaterThan(0.5)
    for (const p of probabilities.slice(1)) {
      expect(p).toBeLessThan(probabilities[0])
    }
  })
})

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

const ALL_KEYS: StubKey[] = [
  'health',
  'scenarios',
  'scenes',
  'scene',
  'detections',
  'candidates',
  'attribution',
  'simulation',
  'dossier',
  'calibration',
]

/** Hold every data endpoint open until the test lets it go. */
function holdEverything(held: Promise<void>) {
  const overrides: Record<string, (context: { key: StubKey }) => Promise<Reply>> = {}
  for (const key of ALL_KEYS) {
    overrides[key] = async () => {
      await held
      return { status: 200, json: defaultFor(key) }
    }
  }
  return overrides as Parameters<typeof stubApi>[1]
}

function defaultFor(key: StubKey): unknown {
  switch (key) {
    case 'health':
      return fx.health()
    case 'scenarios':
      return fx.scenarios()
    case 'scenes':
      return fx.scenes()
    case 'scene':
      return fx.scene()
    case 'detections':
      return fx.detections()
    case 'candidates':
      return fx.candidates()
    case 'attribution':
      return fx.attribution()
    case 'simulation':
      return fx.simulation()
    case 'dossier':
      return fx.dossier()
    case 'calibration':
      return fx.calibration()
    default:
      return {}
  }
}

/** Every endpoint fails with the same honest reason. */
function allFail(detail: string) {
  const overrides: Record<string, Reply> = {}
  for (const key of ALL_KEYS) overrides[key] = serverError(detail)
  return overrides as Parameters<typeof stubApi>[1]
}

async function readProbabilities(page: Page): Promise<number[]> {
  const rows = page.locator('[data-testid="candidate-ranking"] > li')
  const count = await rows.count()
  const out: number[] = []
  for (let i = 0; i < count; i += 1) {
    out.push(parseSignedNumber(await rows.nth(i).locator('.num.text-sm').first().innerText()))
  }
  return out
}
