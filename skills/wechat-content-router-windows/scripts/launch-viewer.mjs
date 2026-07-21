/**
 * 微信只读查看器 —— 一键自动拉起（无需用户手动双击）
 *
 * 用法（由 skill 调用，或用户手动运行）:
 *   node launch-viewer.mjs
 *
 * 行为:
 *   1. 若依赖缺失（koffi / @vscode/sudo-prompt）→ 自动 npm install（node_modules 不进仓库）
 *   2. 若查看器服务已在 127.0.0.1:8731 运行 → 直接打开浏览器
 *   3. 否则后台启动 viewer-server.mjs（detached，退出后常驻）
 *   4. 轮询 /api/health 等待就绪
 *   5. 自动打开默认浏览器访问 http://127.0.0.1:8731
 *
 * 纯只读：本脚本只负责启动与打开页面，绝不写入/发送任何微信数据。
 */
import { spawn } from 'child_process'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'
import { existsSync, mkdirSync, openSync, readFileSync } from 'fs'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PORT = process.env.VIEWER_PORT || 8731
const BASE = `http://127.0.0.1:${PORT}`
const LOG_DIR = join(__dirname, '.viewer_status')
const LOG_FILE = join(LOG_DIR, 'viewer.log')

// 依赖统一安装在 scripts/（与文档 `cd scripts && npm install`、key-extractor.js 的 require 解析一致）
function depsPresent() {
  if (!existsSync(join(__dirname, 'node_modules', 'koffi'))) return false
  // @vscode/sudo-prompt 仅 macOS/Linux 提权用；Windows 只需 koffi
  if (process.platform !== 'win32' && !existsSync(join(__dirname, 'node_modules', '@vscode', 'sudo-prompt'))) return false
  return true
}

async function ensureDeps() {
  if (depsPresent()) return
  console.log('[launch] 首次运行，正在安装依赖 (koffi' + (process.platform === 'win32' ? '' : ', @vscode/sudo-prompt') + ')…')
  await new Promise((resolve) => {
    const cp = spawn('npm', ['install'], {
      cwd: __dirname,
      stdio: 'inherit',
      shell: process.platform === 'win32',
    })
    cp.on('close', () => resolve())
    cp.on('error', () => {
      console.warn(`[launch] 自动安装失败，请手动在 ${__dirname} 运行: npm install`)
      resolve()
    })
  })
}

function openBrowser(u) {
  const p = process.platform
  let cmd, args
  if (p === 'darwin') { cmd = 'open'; args = [u] }
  else if (p === 'win32') { cmd = 'cmd'; args = ['/c', 'start', '', u] }
  else { cmd = 'xdg-open'; args = [u] }
  try { spawn(cmd, args, { stdio: 'ignore' }) } catch {}
}

async function isUp() {
  try {
    const r = await fetch(BASE + '/api/health', { signal: AbortSignal.timeout(1500) })
    return r.ok
  } catch {
    return false
  }
}

async function main() {
  await ensureDeps()
  if (await isUp()) {
    console.log(`[launch] 查看器已在运行: ${BASE}`)
    openBrowser(BASE)
    return
  }
  console.log('[launch] 正在后台启动查看器服务…')
  // 把子进程的 stdout/stderr 写入日志文件，而不是丢弃（否则崩溃/报错完全不可见）
  mkdirSync(LOG_DIR, { recursive: true })
  const logFd = openSync(LOG_FILE, 'a')
  const child = spawn(process.execPath, ['viewer-server.mjs'], {
    cwd: __dirname,
    detached: true,
    stdio: ['ignore', logFd, logFd],
    env: process.env,
  })
  // 若进程一启动就失败（如 node 找不到、脚本语法错误）立即暴露
  child.on('error', (e) => {
    console.error(`[launch] 无法启动 viewer-server.mjs: ${e.message}`)
  })
  child.unref()

  let up = false
  let exitedEarly = false
  child.on('exit', (code) => { if (!up) exitedEarly = code })

  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 500))
    if (await isUp()) { up = true; break }
    if (exitedEarly !== false) break
  }
  if (up) {
    console.log(`[launch] 查看器已就绪: ${BASE}`)
    openBrowser(BASE)
  } else {
    if (exitedEarly !== false) {
      console.log(`[launch] 查看器进程已退出（退出码 ${exitedEarly}），未能就绪。`)
    } else {
      console.log('[launch] 服务启动超时，未能就绪。')
    }
    console.log(`[launch] 启动日志: ${LOG_FILE}`)
    // 直接把日志末尾打印出来，方便用户/我快速定位
    try {
      const tail = readFileSync(LOG_FILE, 'utf8').split('\n').slice(-25).join('\n')
      if (tail.trim()) {
        console.log('[launch] ---- viewer-server 最近日志 ----')
        console.log(tail)
        console.log('[launch] --------------------------------')
      }
    } catch {}
    console.log(`[launch] 也可前台调试运行: node ${join(__dirname, 'viewer-server.mjs')}`)
  }
}

main()
