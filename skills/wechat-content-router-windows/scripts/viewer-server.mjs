/**
 * 微信只读查看器 —— 本地服务 + 只读聊天界面后端
 *
 * 解密 / 查询走纯 Python（viewer_query.py，替代会崩溃的 WxLens DLL）：
 *   1. 自动发现微信账号目录（Windows / macOS）
 *   2. 提取或接收 64 位 hex 数据库密钥（密钥提取仍用 key-extractor.js / wx_key.dll）
 *   3. 用纯 Python（wcdb_decrypt.py + viewer_query.py）解密并读取会话 / 消息 / 搜索
 *   4. 暴露 REST API，供 viewer.html 调用
 *
 * 纯只读：本服务只 SELECT，绝不写入、删除、发送任何微信数据。
 */
import { createRequire } from 'module'
import { fileURLToPath } from 'url'
import { dirname, join, basename, resolve } from 'path'
import { existsSync, readdirSync, statSync, readFileSync, writeFileSync, mkdirSync } from 'fs'
import { homedir } from 'os'
import { spawn, spawnSync } from 'child_process'
import http from 'http'

const require = createRequire(import.meta.url)
const __dirname = dirname(fileURLToPath(import.meta.url))

const PORT = process.env.VIEWER_PORT ? parseInt(process.env.VIEWER_PORT, 10) : 8731
const KEY_CACHE = join(__dirname, '.viewer_key.json')
const STATUS_DIR = join(__dirname, '.viewer_status')

// ────────────────────────────────────────────────────
// 解密 / 查询后端（纯 Python，替代会崩溃的 WxLens DLL）
// ────────────────────────────────────────────────────
// 仅密钥提取仍用独立 wx_key.dll（key-extractor.js）；解密与查询走 viewer_query.py。
let extractKey, ensureWeChatRunning
try {
  ;({ extractKey, ensureWeChatRunning } = require('./key-extractor.js'))
} catch (e) {
  console.warn('[viewer] 无法加载 key-extractor.js（自动取密钥将不可用）:', e.message)
}

function pythonBin() {
  if (process.env.VIEWER_PYTHON) return process.env.VIEWER_PYTHON
  // 跨平台探测：Windows 上 Python 启动器通常是 `python`，macOS/Linux 通常是 `python3`
  for (const cand of ['python3', 'python']) {
    try {
      const r = spawnSync(cand, ['--version'], { stdio: 'ignore', timeout: 5000 })
      if (r.error && r.error.code === 'ENOENT') continue
      return cand
    } catch {
      continue
    }
  }
  return 'python3' // 兜底（缺失时会给出清晰报错）
}

// 调用 viewer_query.py 子命令，解析 stdout 的 JSON
function runPy(args) {
  return new Promise((resolve, reject) => {
    const cp = spawn(pythonBin(), [join(__dirname, 'viewer_query.py'), ...args],
      { stdio: ['ignore', 'pipe', 'pipe'] })
    let out = ''
    let err = ''
    cp.stdout.on('data', (d) => { out += d.toString() })
    cp.stderr.on('data', (d) => { err += d.toString() })
    cp.on('error', (e) => reject(e))
    cp.on('close', (code) => {
      if (!out && code !== 0) return reject(new Error(err || `viewer_query.py 退出码 ${code}`))
      try {
        resolve(JSON.parse(out))
      } catch (e) {
        reject(new Error(`解析 viewer_query.py 输出失败: ${out.slice(0, 200)} | ${err.slice(0, 200)}`))
      }
    })
  })
}

// 纯 Python 客户端：解密一次（缓存），之后查询均读缓存
const py = {
  connected: false,
  accountDir: null,
  cacheDir: null,
  selfWxid: null,
  myWxid: null,
  async open(accountDir, key) {
    this.accountDir = accountDir
    this.selfWxid = basename(accountDir)
    this.myWxid = this.selfWxid
    this.cacheDir = join(__dirname, '.viewer_cache', this.selfWxid)
    const res = await runPy(['decrypt', '--account-dir', accountDir, '--key', key, '--cache-dir', this.cacheDir])
    if (!res.success) throw new Error(res.error || '解密失败')
    this.connected = true
    return accountDir
  },
  isConnected() { return this.connected },
  async getSessions(kind = 'all') {
    const res = await runPy(['sessions', '--cache-dir', this.cacheDir, '--self', this.selfWxid, '--kind', kind])
    if (!res.success) throw new Error(res.error)
    return res.sessions
  },
  async getMessages(sessionId, limit = 50, offset = 0) {
    const res = await runPy(['messages', '--cache-dir', this.cacheDir, '--self', this.selfWxid,
      '--session-id', sessionId, '--limit', String(limit), '--offset', String(offset)])
    if (!res.success) throw new Error(res.error)
    return res.messages
  },
  async searchMessages(keyword, sessionId = '', limit = 30) {
    const args = ['search', '--cache-dir', this.cacheDir, '--self', this.selfWxid,
      '--keyword', keyword, '--limit', String(limit)]
    if (sessionId) args.push('--session-id', sessionId)
    const res = await runPy(args)
    if (!res.success) throw new Error(res.error)
    return res.messages
  },
  async getDisplayNames(ids) {
    if (!ids || ids.length === 0) return {}
    const res = await runPy(['display-names', '--cache-dir', this.cacheDir, '--self', this.selfWxid, '--ids', ids.join(',')])
    if (!res.success) return {}
    return res.names || {}
  },
  async getContact(username) {
    const res = await runPy(['contact', '--cache-dir', this.cacheDir, '--username', username])
    if (!res.success) return null
    return res.contact
  },
}

// ────────────────────────────────────────────────────
// 账号目录发现（Windows + macOS）
// ────────────────────────────────────────────────────
function scanForAccounts(rootPath) {
  const found = []
  if (!existsSync(rootPath)) return found
  const tryDir = (dir) => {
    try {
      if (!statSync(dir).isDirectory()) return
      if (dir.toLowerCase().endsWith('db_storage')) {
        found.push(dirname(dir))
        return
      }
      const xwPath = join(dir, 'xwechat_files')
      if (existsSync(xwPath)) {
        for (const a of scanForAccounts(xwPath)) found.push(a)
        return
      }
      for (const entry of readdirSync(dir)) {
        const sub = join(dir, entry)
        try {
          if (!statSync(sub).isDirectory()) continue
          if (existsSync(join(sub, 'db_storage'))) found.push(sub)
        } catch {}
      }
    } catch {}
  }
  tryDir(rootPath)
  return found
}

function findAllAccountDirs() {
  const candidates = new Set()
  const home = homedir()
  let roots = []
  if (process.platform === 'win32') {
    roots = [
      join(home, 'xwechat_files'),
      join(home, 'Documents', 'xwechat_files'),
      join(home, 'Documents', 'WeChat Files'),
      join(home, '文档', 'xwechat_files'),
    ]
    const appdata = process.env.APPDATA || ''
    if (appdata) roots.push(join(appdata, 'Tencent', 'xwechat', 'xwechat_files'))
  } else if (process.platform === 'darwin') {
    roots = [
      join(home, 'Library', 'Containers', 'com.tencent.xinWeChat', 'Data', 'Documents', 'xwechat_files'),
      join(home, 'Library', 'Containers', 'com.tencent.xinWeChat', 'Data', 'Library', 'Application Support', 'com.tencent.xinWeChat'),
      join(home, 'Documents', 'xwechat_files'),
      join(home, 'Library', 'Application Support', 'com.tencent.xinWeChat'),
    ]
  } else {
    roots = [
      join(home, 'xwechat_files'),
      join(home, '.xwechat_files'),
    ]
  }
  for (const root of roots) {
    for (const acc of scanForAccounts(root)) candidates.add(acc)
  }
  // 扫描常见盘符（Windows）
  if (process.platform === 'win32') {
    for (let code = 65; code <= 90; code++) {
      const drive = String.fromCharCode(code) + ':\\'
      for (const acc of scanForAccounts(join(drive, 'xwechat_files'))) candidates.add(acc)
    }
  }
  return [...candidates].filter(d => {
    try { return existsSync(join(d, 'db_storage')) } catch { return false }
  })
}

// ────────────────────────────────────────────────────
// 消息标准化（对齐 WxLens message-normalizer 字段）
// ────────────────────────────────────────────────────
const TYPE_LABELS = {
  3: '[图片]', 34: '[语音]', 43: '[视频]', 47: '[表情]',
  48: '[位置]', 49: '[链接/文件]', 50: '[通话]',
  10000: '[系统消息]', 10002: '[系统消息]',
}
const ALWAYS_LABEL = new Set([3, 34, 43, 47])
const CONDITIONAL_LABEL = new Set([48, 49, 50, 10000, 10002])
const HEX_RE = /^[0-9a-fA-F\s]{40,}$/

function firstValue(src, keys, fallback = '') {
  for (const k of keys) {
    const v = src?.[k]
    if (v !== undefined && v !== null && v !== '') return v
  }
  return fallback
}

function normalizeMessage(m) {
  const ts = Number(firstValue(m, ['timestamp', 'createTime', 'create_time', 'msgTime', 'msg_time', 'timeStamp'], 0)) || 0
  const content = String(firstValue(m, ['content', 'parsedContent', 'parsed_content', 'messageContent', 'message_content', 'msgContent', 'msg_content', 'rawContent', 'raw_content'], ''))
  const sender = String(firstValue(m, ['sender', 'senderUsername', 'sender_username', 'fromUser', 'from_user', 'talker', 'realSender', 'real_sender'], ''))
  const sessionId = String(firstValue(m, ['sessionId', 'session_id', '_session_id', 'talker', 'username'], ''))
  const isSend = Number(firstValue(m, ['isSend', 'is_send'], 0)) || 0
  const type = Number(firstValue(m, ['type', 'localType', 'local_type', 'msgType', 'msg_type'], 0)) || 0
  return {
    sender,
    content,
    time: ts > 0 ? formatChinaTime(ts) : String(firstValue(m, ['time'], '')),
    timestamp: ts,
    type,
    sessionId,
    localId: Number(firstValue(m, ['localId', 'local_id'], 0)) || 0,
    serverId: String(firstValue(m, ['serverId', 'server_id', 'svrId', 'svr_id'], '')),
    isSend,
    senderId: sender,
    sessionType: sessionId.endsWith('@chatroom') ? 'group' : 'private',
  }
}

function isHexBinary(content) {
  if (!content || content.length < 40) return false
  const s = content.replace(/\s/g, '')
  return s.length >= 40 && HEX_RE.test(s)
}

function sanitize(m) {
  const content = String(m.content || '')
  if (ALWAYS_LABEL.has(m.type)) {
    m.content = TYPE_LABELS[m.type] || '[多媒体]'
    return m
  }
  if (CONDITIONAL_LABEL.has(m.type)) {
    if (!content || isHexBinary(content)) m.content = TYPE_LABELS[m.type] || '[多媒体]'
    return m
  }
  if (m.type !== 1 && isHexBinary(content)) {
    m.content = TYPE_LABELS[m.type] || '[多媒体]'
    return m
  }
  if (content.length > 2000) {
    m.content = content.slice(0, 2000)
    m.truncated = true
  }
  return m
}

function formatChinaTime(ts) {
  if (!ts) return ''
  // 微信时间戳为秒；若数值过大（毫秒）则转换
  const sec = ts > 1e12 ? Math.floor(ts / 1000) : ts
  const d = new Date(sec * 1000)
  if (isNaN(d.getTime())) return String(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// 批量解析发送者显示名
async function resolveNames(client, ids) {
  const unique = [...new Set(ids.filter(Boolean))]
  if (unique.length === 0) return {}
  try {
    return (await client.getDisplayNames(unique)) || {}
  } catch {
    return {}
  }
}

// 处理消息数组：标准化 + 身份解析 + 内容清理
async function processMessages(client, raw, sessionId) {
  const list = Array.isArray(raw) ? raw : (Array.isArray(raw?.messages) ? raw.messages : (Array.isArray(raw?.data) ? raw.data : []))
  const norm = list.map(m => {
    const n = normalizeMessage(m)
    n.sessionId = n.sessionId || sessionId || ''
    return n
  })
  const ids = norm.map(m => m.senderId).filter(Boolean)
  const names = await resolveNames(client, ids)
  const out = norm.map(m => {
    const n = sanitize(m)
    n.senderName = names[m.senderId] || m.senderId || '[未知]'
    n.isSelf = m.isSend === 1 || Boolean(m.senderId && client.myWxid && m.senderId === client.myWxid)
    return n
  })
  return out
}

// ────────────────────────────────────────────────────
// 全局客户端状态
// ────────────────────────────────────────────────────
let client = null
let accountDir = null
let needKey = false
let lastError = null

function loadCachedKey() {
  try {
    if (existsSync(KEY_CACHE)) {
      const c = JSON.parse(readFileSync(KEY_CACHE, 'utf8'))
      if (c.key && /^[0-9a-fA-F]{64}$/.test(c.key)) {
        accountDir = c.accountDir || null
        return c.key
      }
    }
  } catch {}
  return null
}

function saveCachedKey(key, dir) {
  try {
    writeFileSync(KEY_CACHE, JSON.stringify({ key, accountDir: dir || accountDir }, null, 2), 'utf8')
  } catch {}
}

// 仅检测微信进程是否正在运行（只读，绝不启动微信）
// 注意：不要用 key-extractor 的 ensureWeChatRunning()（它会顺带拉起微信）
function isWeChatRunning() {
  return new Promise((resolve) => {
    let cp
    try {
      if (process.platform === 'win32') {
        cp = spawn('tasklist', [], { stdio: ['ignore', 'pipe', 'ignore'] })
      } else {
        cp = spawn('pgrep', ['-f', 'WeChat'], { stdio: ['ignore', 'pipe', 'ignore'] })
      }
    } catch {
      return resolve(false)
    }
    let out = ''
    cp.stdout.on('data', (d) => { out += d.toString() })
    cp.on('error', () => resolve(false))
    cp.on('close', (code) => {
      if (process.platform === 'win32') resolve(/WeChat/i.test(out))
      else resolve(code === 0 && out.trim().length > 0)
    })
  })
}

function withTimeout(promise, ms, fallback = false) {
  return Promise.race([promise, new Promise((resolve) => setTimeout(() => resolve(fallback), ms))])
}

async function tryAutoExtract(timeoutMs = 30000) {
  if (!extractKey) return null
  mkdirSync(STATUS_DIR, { recursive: true })
  // 用 Promise.race 防止 osascript/提权挂死导致服务端卡死 → 前端 Failed to fetch
  const timer = new Promise((_, reject) =>
    setTimeout(() => reject(new Error('自动提取超时（可能需要关闭 SIP 或手动粘贴密钥）')), timeoutMs)
  )
  try {
    return await Promise.race([extractKey({ statusDir: STATUS_DIR, timeout: Math.min(timeoutMs, 60000) }), timer])
  } catch (e) {
    console.warn('[viewer] 自动取密钥失败:', e.message)
    return null
  }
}

async function connect(key, dir) {
  const dirs = dir ? [dir] : findAllAccountDirs()
  if (dirs.length === 0) throw new Error('未找到微信账号目录（请确认微信已登录且存在 db_storage）')
  dirs.sort((a, b) => {
    try { return statSync(b).mtimeMs - statSync(a).mtimeMs } catch { return 0 }
  })
  const target = dirs[0]
  await py.open(target, key)
  client = py
  accountDir = target
  needKey = false
  lastError = null
  return target
}

async function ensureConnected() {
  if (client && client.isConnected()) return true
  const cached = loadCachedKey()
  if (!cached) {
    // 尝试自动提取
    const auto = await tryAutoExtract()
    if (auto) {
      saveCachedKey(auto, accountDir)
      try { await connect(auto, accountDir); return true } catch (e) { lastError = e.message }
    }
    needKey = true
    return false
  }
  try {
    await connect(cached, accountDir)
    return true
  } catch (e) {
    lastError = e.message
    needKey = true
    return false
  }
}

// ────────────────────────────────────────────────────
// HTTP 服务
// ────────────────────────────────────────────────────
function sendJson(res, data, status = 200) {
  const body = JSON.stringify(data)
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
  res.end(body)
}

function parseBody(req) {
  return new Promise((resolve) => {
    let b = ''
    req.on('data', (c) => { b += c })
    req.on('end', () => {
      try { resolve(b ? JSON.parse(b) : {}) } catch { resolve({}) }
    })
  })
}

async function handleApi(req, res, url) {
  const p = Object.fromEntries(url.searchParams)
  if (req.method === 'POST') Object.assign(p, await parseBody(req))
  const path = url.pathname

  try {
    switch (path) {
      case '/api/health':
        return sendJson(res, { status: 'ok' })

      case '/api/status': {
        const connected = !!(client && client.isConnected())
        // wechatRunning 与 connected 是两个独立维度：
        //   connected    = 数据库已解密连接（能读消息）
        //   wechatRunning = 微信进程是否存在（取密钥的前提）
        let wechatRunning = false
        try { wechatRunning = await withTimeout(isWeChatRunning(), 1500, false) } catch { wechatRunning = false }
        return sendJson(res, {
          ok: true,
          data: {
            connected,
            needKey,
            accountDir: accountDir || null,
            platform: process.platform,
            lastError,
            wechatRunning,
          },
        })
      }

      case '/api/accounts': {
        const dirs = findAllAccountDirs()
        return sendJson(res, { ok: true, data: dirs.map(d => ({ dir: d, wxid: basename(d) })) })
      }

      case '/api/set-key': {
        const key = (p.key || '').trim()
        if (!/^[0-9a-fA-F]{64}$/.test(key)) {
          return sendJson(res, { ok: false, error: '密钥格式不正确，应为 64 位十六进制' }, 400)
        }
        const dir = p.accountDir || accountDir || null
        try {
          const used = await connect(key, dir)
          saveCachedKey(key, used)
          return sendJson(res, { ok: true, accountDir: used })
        } catch (e) {
          return sendJson(res, { ok: false, error: e.message }, 400)
        }
      }

      case '/api/auto-extract': {
        // 用 try/catch + finally 确保永远返回 JSON（防止前端 Failed to fetch）
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
        let result
        try {
          const key = await tryAutoExtract(25000)
          if (!key) {
            result = JSON.stringify({ ok: false, error: '自动取密钥不可用。可能原因：①微信未运行/未登录 ②macOS 需关闭 SIP（重启进恢复模式 → csrutil disable）③xkey_helper 缺失或无管理员授权。请手动粘贴 64 位 hex 密钥。' })
          } else {
            saveCachedKey(key, accountDir)
            try {
              await connect(key, accountDir)
              result = JSON.stringify({ ok: true, accountDir })
            } catch (e) {
              result = JSON.stringify({ ok: false, error: `密钥已获取但连接数据库失败: ${e.message}` })
            }
          }
        } catch (e) {
          console.error('[viewer] /api/auto-extract 异常:', e.message || e)
          result = JSON.stringify({ ok: false, error: `提取过程异常: ${e.message || '未知错误'}` })
        }
        res.end(result)
        return
      }

      case '/api/sessions': {
        await ensureConnected()
        if (!client || !client.isConnected()) return sendJson(res, { ok: false, error: needKey ? '需要密钥' : (lastError || '未连接'), accountDir }, 503)
        let sessions = await client.getSessions()
        if (!Array.isArray(sessions)) sessions = []
        const ids = sessions.map(s => s.username || s.user_name || '').filter(Boolean)
        let names = {}
        try { names = await client.getDisplayNames(ids) || {} } catch {}
        const kind = p.kind || 'all'
        if (kind === 'private') sessions = sessions.filter(s => !(s.username || '').endsWith('@chatroom') && !(s.username || '').startsWith('gh_'))
        else if (kind === 'group') sessions = sessions.filter(s => (s.username || '').endsWith('@chatroom'))
        sessions.sort((a, b) => (b.lastTimestamp || b.last_timestamp || 0) - (a.lastTimestamp || a.last_timestamp || 0))
        const limit = Math.min(parseInt(p.limit) || 200, 200)
        const data = sessions.slice(0, limit).map(s => {
          const sid = s.username || s.user_name || ''
          const ts = s.lastTimestamp || s.last_timestamp || 0
          const resolved = names[sid] || s.display_name || s.displayName || ''
          return {
            username: sid,
            displayName: resolved || sid,
            lastTime: ts ? formatChinaTime(ts) : '',
            lastTimestamp: ts,
            unreadCount: s.unreadCount || s.unread_count || 0,
            sessionId: sid,
            sessionName: resolved || sid,
            sessionType: sid.endsWith('@chatroom') ? 'group' : 'private',
          }
        })
        return sendJson(res, { ok: true, data })
      }

      case '/api/messages': {
        await ensureConnected()
        if (!client || !client.isConnected()) return sendJson(res, { ok: false, error: needKey ? '需要密钥' : (lastError || '未连接') }, 503)
        if (!p.session_id) return sendJson(res, { ok: false, error: '缺少 session_id' }, 400)
        const limit = Math.min(parseInt(p.limit) || 50, 200)
        const raw = await client.getMessages(p.session_id, limit, parseInt(p.offset) || 0)
        const data = await processMessages(client, raw, p.session_id)
        return sendJson(res, { ok: true, data })
      }

      case '/api/search': {
        await ensureConnected()
        if (!client || !client.isConnected()) return sendJson(res, { ok: false, error: needKey ? '需要密钥' : (lastError || '未连接') }, 503)
        if (!p.keyword) return sendJson(res, { ok: false, error: '缺少 keyword' }, 400)
        const limit = Math.min(parseInt(p.limit) || 30, 200)
        const raw = await client.searchMessages(p.keyword, p.session_id || '', limit, 0, 0, 0)
        let hydrated = raw
        if (typeof client.getMessageById === 'function') {
          try { hydrated = await hydrateSearch(client, raw) } catch {}
        }
        const data = await processMessages(client, hydrated, p.session_id || '')
        return sendJson(res, { ok: true, data })
      }

      case '/api/contact': {
        await ensureConnected()
        if (!client || !client.isConnected()) return sendJson(res, { ok: false, error: needKey ? '需要密钥' : (lastError || '未连接') }, 503)
        if (!p.username) return sendJson(res, { ok: false, error: '缺少 username' }, 400)
        const contact = await client.getContact(p.username)
        return sendJson(res, { ok: true, data: contact })
      }

      default:
        return sendJson(res, { ok: false, error: 'Not Found' }, 404)
    }
  } catch (e) {
    return sendJson(res, { ok: false, error: e.message }, 500)
  }
}

async function hydrateSearch(client, raw) {
  const results = Array.isArray(raw) ? raw : (raw?.data || [])
  const out = []
  for (const r of results) {
    if (r.sender && r.type && r.serverId) { out.push(r); continue }
    const sid = r.sessionId || r.session_id || r._session_id || ''
    const lid = r.localId || r.local_id || r.message_local_id || 0
    try {
      const full = await client.getMessageById(sid, lid)
      if (full) { out.push({ ...full, content: r.content || full.content, sessionId: sid || full.sessionId }); continue }
    } catch {}
    out.push({ ...r, sessionId: sid })
  }
  return out
}

// 静态页面
function serveViewer(req, res) {
  const htmlPath = join(__dirname, 'viewer.html')
  if (!existsSync(htmlPath)) {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
    res.end('viewer.html 未找到')
    return
  }
  const html = readFileSync(htmlPath, 'utf8')
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
  res.end(html)
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || '127.0.0.1'}`)
  if (url.pathname.startsWith('/api/')) {
    return handleApi(req, res, url)
  }
  if (url.pathname === '/' || url.pathname === '/index.html') {
    return serveViewer(req, res)
  }
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
  res.end('Not Found')
})

server.listen(PORT, '127.0.0.1', async () => {
  console.log('\n=============================================')
  console.log('  微信只读查看器 (WeChat Read-Only Viewer)')
  console.log('=============================================')
  console.log(`  平台: ${process.platform} / ${process.arch}`)
  console.log(`  地址: http://127.0.0.1:${PORT}`)
  console.log('  说明: 纯只读，仅解密并展示，绝不写入/发送。')
  console.log('---------------------------------------------')
  // 启动时尝试自动连接
  try {
    const ok = await ensureConnected()
    if (ok) console.log(`  ✓ 已连接: ${accountDir}`)
    else if (needKey) console.log('  • 需要密钥：打开页面后粘贴 64 位 hex 密钥，或点击“自动提取”。')
    else console.log('  • 未连接:', lastError)
  } catch (e) {
    console.log('  • 初始化:', e.message)
  }
  console.log('=============================================\n')
})
