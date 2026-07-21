import { createRequire } from 'module'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const require = createRequire(import.meta.url)
const __dirname = dirname(fileURLToPath(import.meta.url))

process.env.WX_KEY_DLL_PATH = join(__dirname, 'resources', 'key', 'win32', 'x64', 'wx_key.dll')

// 说明：解密/查询已全面改为纯 Python（wcdb_decrypt.py + viewer_query.py），
// 不再依赖会崩溃的 WxLens 私有 WCDB DLL。本桥接仅保留密钥提取与账号发现。
const { extractKey } = require('./key-extractor.js')
const { execFile } = require('child_process')
const { promisify } = require('util')
const { existsSync, readdirSync, statSync, readFileSync } = require('fs')
const os = require('os')

const execFileAsync = promisify(execFile)
const [,, command, ...args] = process.argv

async function readWeChatPathsFromRegistry() {
  const results = []
  const queries = [
    ['HKCU\\Software\\Tencent\\Weixin', 'FileSavePath'],
    ['HKCU\\Software\\Tencent\\WeChat', 'FileSavePath'],
    ['HKLM\\Software\\Tencent\\Weixin', 'FileSavePath'],
    ['HKLM\\Software\\Tencent\\WeChat', 'FileSavePath'],
  ]
  for (const [key, value] of queries) {
    try {
      const { stdout } = await execFileAsync('reg.exe', ['query', key, '/v', value],
        { windowsHide: true, timeout: 5000 })
      const match = stdout.match(/REG_\w+\s+(.+)$/mi)
      if (match) {
        const p = match[1].trim()
        if (p && p.toUpperCase() !== 'MYDOCUMENT:') results.push(p)
      }
    } catch {}
  }
  return results
}

function readWeChatPathsFromIni() {
  const appdata = process.env.APPDATA || ''
  if (!appdata) return []
  const configDir = join(appdata, 'Tencent', 'xwechat', 'config')
  if (!existsSync(configDir)) return []
  const paths = []
  try {
    for (const file of readdirSync(configDir)) {
      if (!file.endsWith('.ini')) continue
      try {
        const content = readFileSync(join(configDir, file), 'utf8')
        const matches = content.match(/[A-Za-z]:[\\\/][^\r\n<>"'|?*]+/g) || []
        for (const m of matches) {
          const cleaned = m.trim()
          if (cleaned && existsSync(cleaned)) paths.push(cleaned)
        }
      } catch {}
    }
  } catch {}
  return paths
}

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
        return scanForAccounts(xwPath).forEach(a => found.push(a))
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

async function findAllAccountDirs() {
  const candidates = new Set()
  const home = os.homedir()
  const defaultRoots = [
    join(home, 'xwechat_files'),
    join(home, 'Documents', 'xwechat_files'),
    join(home, 'Documents', 'WeChat Files'),
    join(home, '文档', 'xwechat_files'),
  ]
  for (const root of defaultRoots) {
    for (const acc of scanForAccounts(root)) candidates.add(acc)
  }
  const regPaths = await readWeChatPathsFromRegistry()
  for (const p of regPaths) {
    const xw = existsSync(join(p, 'xwechat_files')) ? join(p, 'xwechat_files') : p
    for (const acc of scanForAccounts(xw)) candidates.add(acc)
  }
  const iniPaths = readWeChatPathsFromIni()
  for (const p of iniPaths) {
    for (const acc of scanForAccounts(p)) candidates.add(acc)
    const xw = join(p, 'xwechat_files')
    if (existsSync(xw)) {
      for (const acc of scanForAccounts(xw)) candidates.add(acc)
    }
  }
  for (let code = 65; code <= 90; code++) {
    const drive = String.fromCharCode(code) + ':\\'
    for (const acc of scanForAccounts(join(drive, 'xwechat_files'))) candidates.add(acc)
  }
  const valid = [...candidates].filter(d => {
    try { return existsSync(join(d, 'db_storage')) } catch { return false }
  })
  return valid
}

async function main() {
  try {
    switch (command) {
      case 'extract_key': {
        const key = await extractKey({ timeout: 30000 })
        console.log(JSON.stringify({ success: true, key }))
        break
      }
      case 'ensure_wechat_running': {
        const { ensureWeChatRunning } = require('./key-extractor.js')
        const result = await ensureWeChatRunning()
        console.log(JSON.stringify({ success: true, ...result }))
        break
      }
      case 'find_account_dir': {
        const accounts = await findAllAccountDirs()
        if (accounts.length === 0) {
          throw new Error('未找到微信账号目录，请确认微信4.x已安装并至少登录过一次')
        }
        const sorted = accounts.sort((a, b) => {
          try { return statSync(b).mtimeMs - statSync(a).mtimeMs } catch { return 0 }
        })
        console.log(JSON.stringify({
          success: true,
          accountDir: sorted[0],
          allAccounts: sorted
        }))
        break
      }
      default:
        throw new Error(`Unknown command: ${command}`)
    }
  } catch (e) {
    console.log(JSON.stringify({
      success: false,
      error: e.message,
      code: e.code || null
    }))
    process.exit(1)
  }
}

main()
