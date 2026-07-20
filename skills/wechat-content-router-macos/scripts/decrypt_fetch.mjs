#!/usr/bin/env node
/**
 * decrypt_fetch.mjs
 * ───────────────────────────────────────────────────────────────────────────
 * macOS 一键解密桥的「取数」环节（Node 侧）。
 *
 * 复用 WxLens 自带工具链，不修改任何解密算法：
 *   1. key-extractor.js  → extractKey({ platform: 'darwin' }) 取 64hex 密钥
 *      （内部调 xkey_helper，需 SIP 关闭 + 管理员授权）
 *   2. wcdb-client.js    → WcdbClient.open(accountDir, hexKey) 打开微信账号
 *      → getMessages(chatUsername, limit, offset) 拉取指定聊天最近消息
 *
 * 输出：纯 JSON 到 stdout（供 decrypt_wechat_db.py 消费写成扫描器期望的 schema）。
 *       所有日志/进度一律打到 stderr，避免污染 stdout 的 JSON。
 *
 * 用法：
 *   node decrypt_fetch.mjs [--config PATH] [--username filehelper]
 *                          [--account-dir DIR] [--data-dir DIR]
 *                          [--limit N] [--pretty]
 */

const { join, dirname, resolve, homedir } = require('path')
const { existsSync, readdirSync, statSync, readFileSync, writeFileSync } = require('fs')
const { extractKey } = require('./key-extractor.js')
const { WcdbClient } = require('./wcdb-client.js')

// 关键：把第三方库（key-extractor）打到 stdout 的 [INFO]/[WARN] 之类日志
// 全部重定向到 stderr，保证 stdout 只剩我们的 JSON。
const _origLog = console.log
console.log = (...args) => { process.stderr.write(args.map(String).join(' ') + '\n') }

function logErr(...args) { process.stderr.write('[decrypt_fetch] ' + args.map(String).join(' ') + '\n') }

// ───────────────────────────────────────────────────────────────────────────
// 参数解析
// ───────────────────────────────────────────────────────────────────────────
function parseArgs(argv) {
  const out = {
    config: null,
    username: null,
    accountDir: null,
    dataDir: null,
    limit: 1000,
    pretty: false,
    keyFile: null,
  }
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--config') out.config = argv[++i]
    else if (a === '--username') out.username = argv[++i]
    else if (a === '--account-dir') out.accountDir = argv[++i]
    else if (a === '--data-dir') out.dataDir = argv[++i]
    else if (a === '--limit') out.limit = parseInt(argv[++i], 10) || out.limit
    else if (a === '--pretty') out.pretty = true
    else if (a === '--key-file') out.keyFile = argv[++i]
  }
  return out
}

// 读取缓存密钥（若有效且能打开 DB 则免重复管理员授权）
function readCachedKey(keyFile) {
  if (!keyFile || !existsSync(keyFile)) return null
  try {
    const k = readFileSync(keyFile, 'utf-8').trim()
    if (/^[0-9a-fA-F]{64}$/.test(k)) return k
  } catch {}
  return null
}

function writeCachedKey(keyFile, key) {
  if (!keyFile) return
  try {
    writeFileSync(keyFile, key, { encoding: 'utf-8', mode: 0o600 })
  } catch (e) {
    logErr(`警告：无法写入密钥缓存 (${keyFile}): ${e.message}`)
  }
}

// ───────────────────────────────────────────────────────────────────────────
// 读取 config（仅取 wechat.* 中与取数相关的字段）
// ───────────────────────────────────────────────────────────────────────────
function loadConfigCli(path) {
  if (!path) return {}
  try {
    const cfg = JSON.parse(require('fs').readFileSync(resolve(path), 'utf-8'))
    return cfg.wechat || {}
  } catch {
    logErr(`警告：无法读取 config (${path})，使用默认值`)
    return {}
  }
}

// ───────────────────────────────────────────────────────────────────────────
// 账号目录发现（macOS）— 对齐 viewer-server.mjs 的 findAllAccountDirs
// ───────────────────────────────────────────────────────────────────────────
function isAccountDir(d) {
  try { return existsSync(join(d, 'db_storage')) } catch { return false }
}

function scanForAccounts(rootPath) {
  const found = []
  if (!existsSync(rootPath)) return found
  const tryDir = (dir) => {
    try {
      if (!statSync(dir).isDirectory()) return
      if (dir.toLowerCase().endsWith('db_storage')) { found.push(dirname(dir)); return }
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
  const roots = [
    join(home, 'Library', 'Containers', 'com.tencent.xinWeChat', 'Data', 'Documents', 'xwechat_files'),
    join(home, 'Library', 'Containers', 'com.tencent.xinWeChat', 'Data', 'Library', 'Application Support', 'com.tencent.xinWeChat'),
    join(home, 'Documents', 'xwechat_files'),
    join(home, 'Library', 'Application Support', 'com.tencent.xinWeChat'),
  ]
  for (const root of roots) {
    for (const acc of scanForAccounts(root)) candidates.add(acc)
  }
  return [...candidates].filter(isAccountDir)
}

// ───────────────────────────────────────────────────────────────────────────
// 消息归一化（对齐 viewer-server normalizeMessage 的字段优先级）
// ───────────────────────────────────────────────────────────────────────────
function firstValue(src, keys, fallback = '') {
  for (const k of keys) {
    const v = src?.[k]
    if (v !== undefined && v !== null && v !== '') return v
  }
  return fallback
}

function normalizeMessage(m, sessionId) {
  const createTime = Number(firstValue(m, ['timestamp', 'createTime', 'create_time', 'msgTime', 'msg_time', 'timeStamp'], 0)) || 0
  const content = String(firstValue(m, ['content', 'parsedContent', 'messageContent', 'msg_content', 'rawContent'], ''))
  const localType = Number(firstValue(m, ['type', 'localType', 'local_type', 'msgType', 'msg_type'], 0)) || 0
  const localId = Number(firstValue(m, ['localId', 'local_id'], 0)) || 0
  const sid = String(firstValue(m, ['sessionId', 'session_id', '_session_id', 'talker', 'username'], '')) || sessionId
  return {
    local_id: localId,
    create_time: createTime,
    local_type: localType,
    content,
    session_id: sid,
  }
}

// ───────────────────────────────────────────────────────────────────────────
// 拉取全部消息（分页）
// ───────────────────────────────────────────────────────────────────────────
async function fetchAllMessages(client, sessionId, limitTotal) {
  const page = 200
  const collected = []
  let offset = 0
  while (collected.length < limitTotal) {
    const raw = await client.getMessages(sessionId, page, offset)
    const list = Array.isArray(raw)
      ? raw
      : (Array.isArray(raw?.messages) ? raw.messages : (Array.isArray(raw?.data) ? raw.data : []))
    if (!list.length) break
    for (const m of list) {
      const n = normalizeMessage(m, sessionId)
      if (n.create_time > 0) collected.push(n)
    }
    if (list.length < page) break
    offset += page
  }
  // 去重（按 local_id，保留较晚出现的，避免分页重复）
  const byId = new Map()
  for (const m of collected) byId.set(m.local_id, m)
  return [...byId.values()].sort((a, b) => a.create_time - b.create_time)
}

// ───────────────────────────────────────────────────────────────────────────
// 主流程
// ───────────────────────────────────────────────────────────────────────────
async function main() {
  const args = parseArgs(process.argv)
  const cliWechat = loadConfigCli(args.config)

  const chatUsername = args.username || cliWechat.chat_username || 'filehelper'
  logErr(`目标聊天: ${chatUsername}`)

  // 1) 定位账号目录
  let accountDir = args.accountDir || cliWechat.account_dir || null
  if (!accountDir || !isAccountDir(accountDir)) {
    const dirs = findAllAccountDirs()
    if (accountDir && !isAccountDir(accountDir)) {
      logErr(`指定的 account_dir 无效（无 db_storage）: ${accountDir}`)
    }
    if (dirs.length === 0) {
      logErr('未找到任何微信账号目录（请确认微信已登录且存在 db_storage）')
      process.exit(4)
    }
    accountDir = dirs[0]
    if (dirs.length > 1) {
      logErr(`发现多个账号目录，使用第一个: ${accountDir}`)
      for (const d of dirs) logErr(`  - ${d}`)
    }
  }
  logErr(`账号目录: ${accountDir}`)

  // 2) 取密钥（优先尝试缓存密钥，避免重复管理员授权）
  let key = null
  const cached = args.keyFile ? readCachedKey(args.keyFile) : null
  if (cached) {
    logErr('尝试使用缓存密钥…')
    const probe = new WcdbClient()
    probe.setResourcesPath(join(__dirname, 'resources'))
    try {
      await probe.open(accountDir, cached)
      await probe.close()
      key = cached
      logErr('缓存密钥有效')
    } catch {
      logErr('缓存密钥失效，重新提取')
      key = null
    }
  }
  if (!key) {
    logErr('正在提取微信数据库密钥…')
    try {
      key = await extractKey({ platform: 'darwin' })
    } catch (e) {
      logErr(`密钥提取失败: ${e.message}`)
      process.exit(2)
    }
    if (!key || !/^[0-9a-fA-F]{64}$/.test(key)) {
      logErr('密钥格式异常（非 64 位十六进制）')
      process.exit(3)
    }
    if (args.keyFile) writeCachedKey(args.keyFile, key)
    logErr('密钥提取成功')
  }

  // 3) 打开数据库 + 拉消息
  const client = new WcdbClient()
  client.setResourcesPath(join(__dirname, 'resources'))
  try {
    await client.open(accountDir, key)
    logErr('数据库已打开')
    const messages = await fetchAllMessages(client, chatUsername, args.limit)
    logErr(`拉取到 ${messages.length} 条消息`)

    const out = {
      account_dir: accountDir,
      username: chatUsername,
      key,
      count: messages.length,
      messages,
    }
    const text = args.pretty
      ? JSON.stringify(out, null, 2)
      : JSON.stringify(out)
    process.stdout.write(text + '\n')
  } catch (e) {
    logErr(`读取失败: ${e.message}`)
    process.exit(5)
  } finally {
    try { client.close() } catch {}
  }
}

main().catch((e) => {
  logErr(`未捕获异常: ${e && e.stack ? e.stack : e}`)
  process.exit(99)
})
