import { chromium } from 'playwright'
import { spawn } from 'node:child_process'
import process from 'node:process'

const ROOT = new URL('../../../', import.meta.url).pathname.replace(/\/$/, '')
const PORT = Number(process.env.UI_SMOKE_PORT || 8771)
const BASE = `http://127.0.0.1:${PORT}`

async function wait(url, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const r = await fetch(url)
      if (r.ok) return true
    } catch {
      // retry
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  return false
}

const env = {
  ...process.env,
  PYTHONPATH: `${ROOT}/src${process.env.PYTHONPATH ? `:${process.env.PYTHONPATH}` : ''}`,
  CODESENTRY_SCHEDULER_ENABLED: 'false',
}
const server = spawn(
  `${ROOT}/.venv/bin/python`,
  ['-m', 'uvicorn', 'codesentry.web.server:app', '--host', '127.0.0.1',
   '--port', String(PORT), '--log-level', 'warning'],
  { cwd: ROOT, env, stdio: ['ignore', 'ignore', 'pipe'] },
)
let serverErr = ''
server.stderr.on('data', (chunk) => { serverErr += chunk.toString() })

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage()
const consoleErrors = []
page.on('console', (msg) => {
  if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 300))
})
page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message.slice(0, 300)}`))

const results = []
try {
  if (!(await wait(`${BASE}/api/health`))) {
    console.error(JSON.stringify({ blocked: true, error: 'backend not ready', serverErr: serverErr.slice(-500) }))
    process.exit(2)
  }
  let scans = []
  try {
    scans = await (await fetch(`${BASE}/api/scans`)).json()
  } catch {
    scans = []
  }
  const routes = [
    '/ui/', '/ui/scans', '/ui/projects', '/ui/reviews', '/ui/agents',
    '/ui/agents/recon', '/ui/llm', '/ui/usage', '/ui/prompts', '/ui/skills',
    '/ui/kb', '/ui/rules', '/ui/orchestration', '/ui/audit', '/ui/settings',
    '/ui/users', '/ui/login',
  ]
  if (Array.isArray(scans) && scans.length) {
    routes.push(`/ui/scans/${scans[0].id}`, `/ui/scans/${scans[0].id}/graph`)
    try {
      const paths = await (await fetch(`${BASE}/api/scans/${scans[0].id}/paths?limit=1`)).json()
      if (paths.paths?.length) {
        routes.push(`/ui/scans/${scans[0].id}/graph?path_id=${paths.paths[0].id}`)
      }
    } catch {
      // path route is optional
    }
  }
  for (const route of routes) {
    const before = consoleErrors.length
    let ok = false
    let title = ''
    let text = ''
    try {
      await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 20000 })
      await page.waitForFunction(
        () => (document.querySelector('#app, #root')?.children.length || 0) > 0,
        undefined,
        { timeout: 15000 },
      )
      title = await page.title()
      text = (await page.locator('body').innerText()).slice(0, 200)
      ok = Boolean(title) && !text.includes('页面不存在')
      if (route === '/ui/login') ok = ok && text.includes('登录')
    } catch (e) {
      text = `ERROR: ${String(e).slice(0, 160)}`
    }
    results.push({
      route,
      ok,
      title,
      text,
      console_errors: consoleErrors.slice(before),
    })
  }
  if (Array.isArray(scans) && scans.length) {
    try {
      const sid = scans[0].id
      await page.goto(`${BASE}/ui/scans/${sid}`, { waitUntil: 'domcontentloaded' })
      await page.locator('#tab-paths').click()
      await page.waitForTimeout(600)
      const rows = page.locator('.el-tab-pane:visible .el-table__body-wrapper tbody tr')
      if (await rows.count()) {
        await rows.first().click({ force: true })
        await page.waitForSelector('.el-drawer__body', { timeout: 8000 })
        const text = (await page.locator('.el-drawer__body').innerText()).slice(0, 1200)
        results.push({
          route: `/ui/scans/${sid}#path-drawer`,
          ok: text.includes('路径节点') && text.includes('在图中高亮'),
          title: await page.title(),
          text,
          console_errors: [],
        })
      }
    } catch (e) {
      results.push({
        route: `/ui/scans/${scans[0].id}#path-drawer`,
        ok: false,
        title: '',
        text: `ERROR: ${String(e).slice(0, 200)}`,
        console_errors: [],
      })
    }
  }
  const failed = results.filter((r) => !r.ok || r.console_errors.length)
  console.log(JSON.stringify({
    passed: results.length - failed.length,
    total: results.length,
    failed,
    results,
  }, null, 2))
  process.exit(failed.length ? 1 : 0)
} finally {
  await browser.close()
  server.kill('SIGTERM')
  await new Promise((r) => setTimeout(r, 800))
  if (!server.killed) server.kill('SIGKILL')
}
