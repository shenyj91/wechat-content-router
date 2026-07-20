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
import { existsSync } from 'fs'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = dirname(__dirname) // skills/wechat-content-router-<platform>/
const PORT = process.env.VIEWER_PORT || 8731
const BASE = `http://127.0.0.1:${PORT}`

function depsPresent() {
  return (
    existsSync(join(ROOT, 'node_modules', 'koffi')) &&
    existsSync(join(ROOT, 'node_modules', '@vscode', 'sudo-prompt'))
  )
}

async function ensureDeps() {
  if (depsPresent()) return
  console.log('[launch] 首次运行，正在安装依赖 (koffi, @vscode/sudo-prompt)…')
  await new Promise((resolve) => {
    const cp = spawn('npm', ['install'], {
      cwd: ROOT,
      stdio: 'inherit',
      shell: process.platform === 'win32',
    })
    cp.on('close', () => resolve())
    cp.on('error', () => {
      console.warn(`[launch] 自动安装失败，请手动在 ${ROOT} 运行: npm install`)
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
  const child = spawn(process.execPath, ['viewer-server.mjs'], {
    cwd: __dirname,
    detached: true,
    stdio: 'ignore',
    env: process.env,
  })
  child.unref()

  let up = false
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 500))
    if (await isUp()) { up = true; break }
  }
  if (up) {
    console.log(`[launch] 查看器已就绪: ${BASE}`)
    openBrowser(BASE)
  } else {
    console.log('[launch] 服务启动超时，请手动检查 viewer-server.mjs 运行日志。')
    console.log(`[launch] 也可直接运行: node ${__dirname}/viewer-server.mjs`)
  }
}

main()
