// Drive one scenario through the real demo UI, start to finish, as the manager who can approve.
// Shared by the screenshot script and the video recorder so both show exactly the same flow.
const INDUSTRY = { cover: 'Healthcare', care: 'Healthcare', offboarding: 'IT & security', leak: 'IT & security',
                   outage: 'Engineering', fixtures: 'Sport & clubs' }
const PLAYBOOK = { cover: 'Doctor off sick', care: 'Care follow-up', offboarding: 'Access & offboarding',
                   leak: 'Leaked credential', outage: 'Service outage', fixtures: 'Fixture cannot go ahead' }

async function pick(page, playbook, scenario) {
  await page.locator('.industries button', { hasText: INDUSTRY[playbook] }).click()
  await page.locator('.playbooks button', { hasText: PLAYBOOK[playbook] }).click()
  await page.selectOption('#scenario', scenario)
}

async function start(page) {
  await page.locator('.hero-form button.btn-dark').click()
  await page.waitForSelector('.overview h2', { timeout: 40000 })
}

/** Run, approving whatever asks, until the incident closes or escalates. `onApproval` sees the first. */
async function runToEnd(page, { onApproval, pause = 900 } = {}) {
  await page.locator('.overview button.btn-dark').click()
  let first = true
  for (let i = 0; i < 120; i++) {
    await page.waitForTimeout(pause)
    const btn = page.locator('.approval-actions button.btn-lime').first()
    if (await btn.count()) {
      if (first && onApproval) await onApproval(btn)
      first = false
      await btn.click()
      continue
    }
    const status = (await page.locator('.status-card b').innerText().catch(() => '')).trim()
    if (/Closed|Escalated/i.test(status)) return status
  }
  return 'timeout'
}

module.exports = { pick, start, runToEnd, INDUSTRY, PLAYBOOK }
