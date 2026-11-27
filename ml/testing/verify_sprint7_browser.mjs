import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { createServer as createTcpServer } from 'node:net'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { randomBytes, randomUUID } from 'node:crypto'
import { relative, resolve } from 'node:path'
import { build, createServer as createViteServer, preview } from 'vite'

const root = resolve('ml/runtime', 'sprint7/browser-' + randomUUID().slice(0, 8))
const py = resolve(process.env.SIKEMBANG_TEST_PYTHON ?? 'ml/.venv/Scripts/python.exe')
const chrome = process.env.SIKEMBANG_TEST_CHROME ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const artifact = resolve(process.env.SIKEMBANG_TEST_ARTIFACT ?? 'ml/artifacts/xgb-v1-f9a770b940f71fc8')
const delay = (ms) => new Promise((resolveDelay) => setTimeout(resolveDelay, ms))
const secretNames = ['JWT_SECRET', 'MARKETING_PASSWORD', 'PPIC_PASSWORD', 'PFA_PASSWORD',
  'DEVICE_RICE_KEY', 'DEVICE_CHICKEN_KEY']
const credentials = Object.fromEntries(secretNames.map((name) =>
  ['SIKEMBANG_' + name, randomBytes(32).toString('base64url')]))
const roles = ['marketing', 'ppic', 'pfa']
const password = (role) => credentials['SIKEMBANG_' + role.toUpperCase() + '_PASSWORD']
const customer = 'Pesanan uji integrasi Sprint 7'
const note = 'Cek fisik simulasi Sprint 7'
const evidence = { browser: {}, http: {}, databases: {} }
let browser, page, vite, backend
const browserErrors = []
const browserWarnings = []
const loadingFailures = []
const records = []

async function poll(label, fn, timeout = 90000) {
  const end = Date.now() + timeout
  let error
  while (Date.now() < end) {
    try {
      const result = await fn()
      if (result) return result
    } catch (cause) {
      error = cause
    }
    await delay(180)
  }
  throw new Error('Timeout: ' + label + (error ? ' (' + error.message + ')' : ''))
}

async function port() {
  const server = createTcpServer()
  await new Promise((ready) => server.listen(0, '127.0.0.1', ready))
  const value = server.address().port
  await new Promise((closed) => server.close(closed))
  return value
}

function python(args, env) {
  return execFileSync(py, ['-X', 'utf8', ...args], {
    cwd: process.cwd(), env, encoding: 'utf8', windowsHide: true, timeout: 360000,
  })
}

function scenario(name, withForecast) {
  const path = resolve(root, name + '.sqlite3')
  const env = { ...process.env, ...credentials, SIKEMBANG_DB_PATH: path }
  delete env.SIKEMBANG_DEMO_CUTOFF
  delete env.SIKEMBANG_SYSTEM_KEY
  if (withForecast) env.SIKEMBANG_ARTIFACT = artifact
  else delete env.SIKEMBANG_ARTIFACT
  python(['-m', 'sikembang_backend.manage', 'init-db'], env)
  const seed = JSON.parse(python(['-m', 'sikembang_backend.manage', 'seed'], env))
  return { env, path, seed }
}

const backendCode = [
  'import sys, threading, uvicorn',
  'from sikembang_backend.app import create_app',
  'server=uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning"))',
  'def wait_for_stop():',
  ' sys.stdin.readline()',
  ' server.should_exit=True',
  'threading.Thread(target=wait_for_stop, daemon=True).start()',
  'server.run()',
].join('\n')

async function startBackend(fixture, apiPort) {
  let log = ''
  const child = spawn(py, ['-X', 'utf8', '-c', backendCode, String(apiPort)], {
    env: fixture.env, windowsHide: true, stdio: ['pipe', 'ignore', 'pipe'],
  })
  child.stderr.on('data', (chunk) => { log += chunk })
  child.on('error', (err) => { log += err.message })
  backend = child
  const origin = 'http://127.0.0.1:' + apiPort
  try {
    await poll('backend health', async () => (await fetch(origin + '/api/health')).ok, 120000)
  } catch (err) {
    throw new Error(err.message + '\n' + log)
  }
  return origin
}

async function stopBackend() {
  const child = backend
  backend = undefined
  if (!child || child.exitCode !== null) return
  const exited = new Promise((finish) => child.once('close', finish))
  child.stdin.end('stop\n')
  await Promise.race([exited, delay(8000)])
  if (child.exitCode === null) child.kill()
}

async function startVite(mode, uiPort, apiOrigin) {
  process.env.VITE_API_MODE = mode
  process.env.VITE_API_BASE_URL = '/api'
  process.env.VITE_DEV_PROXY_TARGET = apiOrigin ?? ''
  const origin = 'http://127.0.0.1:' + uiPort
  if (process.argv.includes('--preview')) {
    const outDir = resolve(root, 'bundle-' + mode)
    await build({ build: { outDir, emptyOutDir: true }, logLevel: 'warn' })
    const builtServer = await preview({
      build: { outDir },
      preview: { host: '127.0.0.1', port: uiPort, strictPort: true },
      logLevel: 'warn',
    })
    vite = { close: () => new Promise((finish) => builtServer.httpServer.close(finish)) }
  } else {
    vite = await createViteServer({
      cacheDir: resolve(root, 'vite-' + mode),
      server: { port: uiPort, host: '127.0.0.1', strictPort: true },
      clearScreen: false, logLevel: 'warn',
    })
    await vite.listen()
  }
  if (apiOrigin) assert((await fetch(origin + '/api/health')).ok)
  console.log('Vite ' + mode + ' siap di loopback')
  return origin
}

class Cdp {
  next = 0
  pending = new Map()
  constructor(socket) {
    this.socket = socket
    socket.addEventListener('message', ({ data }) => {
      const event = JSON.parse(data)
      if (event.id) {
        const pair = this.pending.get(event.id)
        this.pending.delete(event.id)
        if (!pair) return
        if (event.error) pair.reject(new Error(event.error.message))
        else pair.resolve(event.result)
      }
      if (event.method === 'Network.responseReceived') {
        const { response, requestId } = event.params
        const url = new URL(response.url)
        if (url.pathname.startsWith('/api/')) {
          records.push({ requestId, path: url.pathname, status: response.status,
            worker: response.fromServiceWorker === true })
        }
      }
      if (event.method === 'Runtime.exceptionThrown') {
        const details = event.params.exceptionDetails
        browserErrors.push(details.exception?.description ?? details.text)
      }
      if (event.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(event.params.type)) {
        browserWarnings.push(event.params.args.map((arg) => arg.value ?? arg.description).join(' '))
      }
      if (event.method === 'Network.loadingFailed' && !event.params.canceled) {
        loadingFailures.push(event.params.errorText)
      }
    })
  }
  call(method, params = {}) {
    const id = ++this.next
    return new Promise((resolveCall, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error('Chrome DevTools timeout for ' + method))
      }, 12000)
      this.pending.set(id, {
        resolve: (value) => { clearTimeout(timer); resolveCall(value) },
        reject: (err) => { clearTimeout(timer); reject(err) },
      })
      this.socket.send(JSON.stringify({ id, method, params }))
    })
  }
  async eval(expression) {
    const data = await this.call('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true,
    })
    if (data.exceptionDetails) throw new Error(data.exceptionDetails.exception?.description ?? data.exceptionDetails.text)
    return data.result.value
  }
}

async function openChrome() {
  const profile = resolve(root, 'chrome-profile')
  browser = spawn(chrome, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-sync', '--disable-extensions',
    '--remote-debugging-port=0', '--user-data-dir=' + profile, '--window-size=1440,1000', 'about:blank',
  ], { windowsHide: true, stdio: 'ignore' })
  let error
  browser.on('error', (err) => { error = err })
  const target = await poll('Chrome DevTools target', async () => {
    if (error) throw error
    const active = (await readFile(resolve(profile, 'DevToolsActivePort'), 'utf8')).split(/\r?\n/)[0]
    const listed = await fetch('http://127.0.0.1:' + active + '/json/list')
    return (await listed.json()).find((item) => item.type === 'page')
  }, 25000)
  const socket = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((ready, reject) => {
    socket.once ? socket.once('open', ready) : socket.addEventListener('open', ready, { once: true })
    socket.addEventListener('error', reject, { once: true })
  })
  page = new Cdp(socket)
  await page.call('Page.enable')
  await page.call('Runtime.enable')
  await page.call('Network.enable')
}

function evaluate(callback, ...args) {
  return page.eval('(' + callback.toString() + ')(...' + JSON.stringify(args) + ')')
}

function contains(value) {
  return evaluate((text) => document.body?.innerText?.includes(text), value)
}

async function waitText(value) {
  await poll('UI text ' + value, () => contains(value))
}

async function navigate(target) {
  await page.call('Page.navigate', { url: target })
}

async function reload() {
  await page.call('Page.reload', { ignoreCache: true })
}

async function fill(label, value) {
  await poll('field ' + label, () => evaluate((text, next) => {
    const explicit = [...document.querySelectorAll('input, select, textarea')]
      .find((input) => input.getAttribute('aria-label') === text)
    const wrapper = [...document.querySelectorAll('label')]
      .find((el) => el.querySelector('span')?.textContent?.trim() === text)
    const field = explicit ?? (wrapper?.htmlFor ? document.getElementById(wrapper.htmlFor) : null)
      ?? wrapper?.querySelector('input, select, textarea')
    if (!field || typeof field === 'string') return false
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), 'value').set.call(field, next)
    field.dispatchEvent(new Event('input', { bubbles: true }))
    field.dispatchEvent(new Event('change', { bubbles: true }))
    return true
  }, label, value))
}

async function click(label, scope = 'body') {
  await poll('button ' + label, () => evaluate((text, selector) => {
    const button = [...(document.querySelector(selector)?.querySelectorAll('button, a') ?? [])]
      .find((item) => item.textContent.trim().replace(/\s+/g, ' ') === text && !item.disabled)
    button?.click()
    return !!button
  }, label, scope))
}

async function fillStaleNotes() {
  const labels = await evaluate(() => [...document.querySelectorAll('input[placeholder="Wajib diisi"]')]
    .map((input) => input.getAttribute('aria-label')))
  assert(labels.length > 0)
  for (const label of labels) await fill(label, note)
  return labels.length
}

async function response(path, after, status = 200) {
  return poll('browser API ' + path + ' ' + status, async () => {
    const item = records.slice(after).find((row) => row.path === path && row.status === status)
    if (!item) return false
    const payload = await page.call('Network.getResponseBody', { requestId: item.requestId })
    const body = payload.base64Encoded ? Buffer.from(payload.body, 'base64').toString() : payload.body
    return { path: item.path, status: item.status, worker: item.worker, body: JSON.parse(body) }
  })
}

async function screenshot(name) {
  const image = await page.call('Page.captureScreenshot', { format: 'png' })
  const target = resolve(root, name + '.png')
  await writeFile(target, Buffer.from(image.data, 'base64'))
  return relative(process.cwd(), target).replaceAll('\\', '/')
}

async function uiLogin(role, heading) {
  await fill('Nama pengguna', role)
  await fill('Kata sandi', password(role))
  await click('Masuk')
  await waitText(heading)
}
async function uiLogout() {
  await click('Keluar')
  await waitText('Nama pengguna')
}

async function request(origin, method, path, { body, token, headers = {}, expected = 200 } = {}) {
  const result = await fetch(origin + path, {
    method,
    headers: {
      ...(token && { Authorization: 'Bearer ' + token }), ...headers,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const json = await result.json()
  assert.equal(result.status, expected, path + ' ' + JSON.stringify(json))
  return { status: result.status, response: json }
}
async function token(origin, role) {
  assert(roles.includes(role))
  const result = await request(origin, 'POST', '/api/auth/login', {
    body: { username: role, password: password(role) },
  })
  return result.response.access_token
}

function inspectDatabase(fixture, ids = {}) {
  const code = [
    'import json, sqlite3, sys',
    'from pathlib import Path',
    'path=Path(sys.argv[1]); ids=json.loads(sys.argv[2]); out={}',
    'with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True) as db:',
    ' db.row_factory=sqlite3.Row',
    ' out["integrity"]=db.execute("PRAGMA integrity_check").fetchone()[0]',
    ' out["foreign_key_violations"]=len(db.execute("PRAGMA foreign_key_check").fetchall())',
    ' out["forecast_runs"]=db.execute("select count(*) from forecast_runs").fetchone()[0]',
    ' out["accepted_telemetry_sources"]=[row[0] for row in db.execute("select distinct device_source from iot_telemetry_logs where validation_status=? order by device_source",("ACCEPTED",))]',
    ' if ids.get("order"):',
    '  out["order_versions"]=[row[0] for row in db.execute("select version from order_revisions where order_id=? order by version",(ids["order"],))]',
    ' if ids.get("list"):',
    '  out["list"]=dict(db.execute("select list_id,status,validated_by,validated_at,sent_at,procurement_required,forecast_run_id from shopping_lists where list_id=?",(ids["list"],)).fetchone())',
    '  out["items"]=[dict(row) for row in db.execute("select ingredient_id,system_net_recommendation,ppic_final_qty,ppic_notes,base_unit from shopping_list_items where list_id=? order by ingredient_id",(ids["list"],))]',
    '  run=out["list"]["forecast_run_id"]',
    '  if run: out["model_version"]=db.execute("select model_version from forecast_runs where forecast_run_id=?",(run,)).fetchone()[0]',
    ' print(json.dumps(out))',
  ].join('\n')
  const checked = JSON.parse(python(['-c', code, fixture.path, JSON.stringify(ids)], fixture.env))
  assert.equal(checked.integrity, 'ok')
  assert.equal(checked.foreign_key_violations, 0)
  return { path: relative(process.cwd(), fixture.path).replaceAll('\\', '/'), ...checked }
}

async function probe() {
  const ua = await page.eval('navigator.userAgent')
  assert(ua.includes('HeadlessChrome'))
  console.log('Chrome DevTools tersedia')
}

async function liveWorkflow(uiPort, apiPort) {
  const fixture = scenario('live', true)
  const api = await startBackend(fixture, apiPort)
  const specification = await (await fetch(api + '/openapi.json')).json()
  const expected = [
    ['post', '/api/orders'], ['put', '/api/orders/{order_id}'], ['get', '/api/orders'],
    ['post', '/api/iot/telemetry'], ['get', '/api/inventory/stock'], ['post', '/api/ai/predict'],
    ['post', '/api/procurement/calculate'], ['post', '/api/shopping-lists'], ['get', '/api/shopping-lists'],
    ['patch', '/api/shopping-lists/{list_id}/approve'], ['post', '/api/shopping-lists/{list_id}/send'],
  ]
  for (const [method, path] of expected) assert(specification.paths[path]?.[method], method + ' ' + path)
  evidence.http.d2_endpoints = expected.map(([method, path]) => method.toUpperCase() + ' ' + path)
  const liveUrl = await startVite('live', uiPort, api)
  const liveStart = records.length
  await navigate(liveUrl + '/ppic')
  await waitText('Nama pengguna')
  await uiLogin('marketing', 'Catat Pesanan Terkonfirmasi')

  const eventDate = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Jakarta', year: 'numeric',
    month: '2-digit', day: '2-digit' }).format(new Date())
  await fill('Nama pelanggan', customer)
  await fill('Tanggal acara', eventDate)
  await fill('Lokasi acara', 'Lokasi uji nonproduksi')
  for (const n of [1, 2, 3]) await fill('Porsi menu ' + n, '200')
  const orderStart = records.length
  await click('Simpan pesanan')
  await waitText('Pesanan tersimpan')
  console.log('Marketing: form Chrome tersimpan')
  const order = await response('/api/orders', orderStart, 201)
  evidence.browser.order_created = order
  const orderId = order.body.order_id
  assert.equal(order.body.version, 1)
  const marketingToken = await token(api, 'marketing')
  const revision = { version: 1, event_date: eventDate, event_location: 'Lokasi revisi uji',
    items: [{ menu_id: 'MNU-N01', confirmed_portions: 240 }, { menu_id: 'MNU-A01', confirmed_portions: 240 },
      { menu_id: 'MNU-S01', confirmed_portions: 240 }] }
  evidence.http.revised_order = await request(api, 'PUT', '/api/orders/' + orderId, {
    token: marketingToken, body: revision,
  })
  evidence.http.stale_order = await request(api, 'PUT', '/api/orders/' + orderId, {
    token: marketingToken, body: revision, expected: 409,
  })
  assert.equal(evidence.http.stale_order.response.error.code, 'VERSION_CONFLICT')

  evidence.http.telemetry = await request(api, 'POST', '/api/iot/telemetry', {
    headers: { 'X-Device-Key': credentials.SIKEMBANG_DEVICE_RICE_KEY },
    body: { sensor_id: 'SNS-GDG-01', ingredient_id: 'ING-001', measured_weight: 21500, unit: 'g',
      recorded_at: new Date(Date.now() - 1000).toISOString() },
    expected: 201,
  })
  assert.equal(evidence.http.telemetry.response.current_stock, 21.5)

  await uiLogout()
  const ppicStart = records.length
  await uiLogin('ppic', 'Perencanaan minggu ini')
  await waitText(customer)
  await waitText('Direvisi v2')
  await waitText('Segar')
  const orders = await response('/api/orders', ppicStart)
  const stock = await response('/api/inventory/stock', ppicStart)
  assert(orders.body.orders.some((row) => row.order_id === orderId && row.version === 2))
  assert(stock.body.items.some((row) => row.ingredient_id === 'ING-001' && row.current_stock === 21.5 && row.stock_status === 'FRESH'))
  evidence.browser.ppic_orders = { status: orders.status, order_id: orderId, found_version: 2 }
  evidence.browser.ppic_stock = { status: stock.status, items: stock.body.items }
  evidence.browser.planning_screenshot = await screenshot('planning-live')

  const calcStart = records.length
  await click('Hitung kebutuhan minggu ini')
  await waitText('Tinjau rekomendasi belanja')
  console.log('PPIC: Chrome memuat review dari draf FastAPI')
  const calc = await response('/api/procurement/calculate', calcStart, 201)
  const draft = calc.body
  assert(draft.forecast_run_id && draft.model_version === 'xgb-v1-f9a770b940f71fc8')
  assert(draft.items.some((line) => line.ai_additional_forecast > 0))
  evidence.browser.calculation = calc
  await waitText('Prediksi AI')
  evidence.browser.review_screenshot = await screenshot('review-live')

  const staleLines = await fillStaleNotes()
  const rice = draft.items.find((line) => line.ingredient_id === 'ING-001')
  const chicken = draft.items.find((line) => line.ingredient_id === 'ING-003')
  await fill('Qty final Beras', '42.25')
  await fill('Qty final Ayam', '0')
  await click('Tolak AI', 'tr:has(input[aria-label="Qty final Minyak goreng"])')
  await waitText('Alasan menolak')
  await fill('Alasan menolak', 'Prediksi tidak realistis')
  await click('Tolak prediksi AI', 'dialog')
  await waitText('AI ditolak: Prediksi tidak realistis')
  const oil = draft.items.find((line) => line.ingredient_id === 'ING-012')
  const expectedOil = Math.max(0, Math.round((oil.bom_confirmed_need + oil.safety_stock - oil.iot_available_stock) * 1000) / 1000)
  const oilQty = await evaluate(() => document.querySelector('input[aria-label="Qty final Minyak goreng"]').valueAsNumber)
  assert.equal(oilQty, expectedOil)

  const approveStart = records.length
  await click('Setujui dan kirim ke PFA')
  await waitText('Terkirim ke PFA')
  console.log('PPIC: persetujuan dan pengiriman berhasil')
  const approve = await response('/api/shopping-lists/' + draft.list_id + '/approve', approveStart)
  const sent = await response('/api/shopping-lists/' + draft.list_id + '/send', approveStart)
  const riceEdited = approve.body.items.find((item) => item.ingredient_id === 'ING-001')
  assert.equal(riceEdited.system_net_recommendation, rice.system_net_recommendation)
  assert.equal(riceEdited.ppic_final_qty, 42.25)
  assert.equal(approve.body.items.find((item) => item.ingredient_id === 'ING-003').ppic_final_qty, 0)
  assert.equal(chicken.base_unit, 'kg')
  evidence.browser.approval = approve
  evidence.browser.sent = sent
  evidence.browser.review_metadata = { stale_notes_filled: staleLines, rejected_ai_ingredient: 'ING-012',
    rejected_ai_final_quantity: oilQty }
  await uiLogout()

  const pfaStart = records.length
  await uiLogin('pfa', 'Permintaan bahan masuk')
  await waitText(draft.list_id)
  await waitText('42,25')
  await response('/api/shopping-lists', pfaStart)
  assert(!records.slice(pfaStart).some((row) => row.path === '/api/inventory/stock'))
  evidence.browser.pfa = { list_id: draft.list_id, confirmed_quantity_visible: 42.25 }
  evidence.browser.pfa_screenshot = await screenshot('pfa-live')

  const pfaToken = await token(api, 'pfa')
  const pfa = await request(api, 'GET', '/api/shopping-lists?status=SENT_TO_PFA', {
    token: pfaToken, expected: 200,
  })
  const published = pfa.response.lists.find((list) => list.list_id === draft.list_id)
  assert(published && published.items.every((row) => row.ppic_final_qty > 0))
  assert(!published.items.some((row) => row.ingredient_id === 'ING-003'))
  assert(!published.items.some((row) => 'ai_additional_forecast' in row))
  evidence.http.pfa_published = pfa
  evidence.http.pfa_drafts_denied = await request(api, 'GET', '/api/shopping-lists?status=DRAFT', {
    token: pfaToken, expected: 403,
  })
  evidence.http.pfa_send_denied = await request(api, 'POST', '/api/shopping-lists/' + draft.list_id + '/send', {
    token: pfaToken, expected: 403,
  })
  await stopBackend()
  evidence.databases.live = inspectDatabase(fixture, { order: orderId, list: draft.list_id })
  assert.equal(evidence.databases.live.list.status, 'SENT_TO_PFA')
  assert.equal(evidence.databases.live.list.forecast_run_id, draft.forecast_run_id)
  assert.equal(evidence.databases.live.model_version, draft.model_version)
  assert.deepEqual(evidence.databases.live.order_versions, [1, 2])
  assert.deepEqual(evidence.databases.live.accepted_telemetry_sources, ['synthetic'])
  evidence.browser.live_api_requests = records.slice(liveStart).filter((row) => row.path !== '/api/auth/login')
    .map(({ path, status, worker }) => ({ path, status, worker }))
  assert(evidence.browser.live_api_requests.length > 5)
  assert(evidence.browser.live_api_requests.every((row) => !row.worker))
}


try {
  await mkdir(root, { recursive: true })
  await openChrome()
  await probe()
  if (!process.argv.includes('--probe')) {
    const [uiPort, apiPort] = await Promise.all([port(), port()])
    const mockUrl = await startVite('mock', uiPort)
    await navigate(mockUrl + '/ppic')
    await waitText('Perencanaan minggu ini')
    const mocked = await response('/api/inventory/stock', 0)
    assert(mocked.worker && mocked.body.items.length > 0)
    assert(await evaluate(() => !!document.querySelector('[aria-label="Ganti peran (mode mock)"]')))
    console.log('Mock: Chrome menerima stok dari service worker tanpa backend')
    evidence.browser.mock = { pick_role: true, stock_http: mocked.status, from_service_worker: mocked.worker }
    await vite.close()
    vite = undefined

    await liveWorkflow(uiPort, apiPort)
    await vite.close()
    vite = undefined
    evidence.browser.unhandled_exceptions = browserErrors
    evidence.browser.vite_host = process.argv.includes('--preview') ? 'preview' : 'dev'
    assert.deepEqual(browserErrors, [])
    const evidencePath = process.argv.includes('--preview')
      ? resolve(root, 'browser-evidence.json') : resolve(root, 'browser-evidence-dev.json')
    await writeFile(evidencePath, JSON.stringify(evidence, null, 2) + '\n')
    console.log(JSON.stringify({
      root, source: evidence.databases.live.model_version,
      sent: evidence.databases.live.list.status, order: evidence.databases.live.order_versions,
      captured: evidence.browser.live_api_requests.length,
    }))
  }
} catch (err) {
  if (page) {
    const diagnostic = await Promise.race([
      evaluate(() => ({ path: location.pathname, heading: document.querySelector('h1')?.textContent,
        alerts: [...document.querySelectorAll('[role="alert"]')].map((item) => item.textContent) })),
      delay(1500),
    ]).catch(() => undefined)
    console.error(JSON.stringify({ diagnostic, browserErrors, browserWarnings: browserWarnings.slice(-8),
      loadingFailures: loadingFailures.slice(-8),
      recent_requests: records.slice(-12).map(({ path, status, worker }) => ({ path, status, worker })) }))
  }
  throw err
} finally {
  await stopBackend()
  if (vite) await vite.close()
  if (page) {
    await Promise.race([page.call('Browser.close').catch(() => {}), delay(2000)])
    page.socket.close()
  }
  if (browser && browser.exitCode === null) browser.kill()
}
