const { join, resolve } = require('path')
const { existsSync, copyFileSync, mkdirSync, readFileSync, writeFileSync, renameSync, unlinkSync } = require('fs')
const { execFile, exec } = require('child_process')
const { promisify } = require('util')
const crypto = require('crypto')
const os = require('os')

const execFileAsync = promisify(execFile)
const execAsync = promisify(exec)

const log = (msg) => console.log(`[INFO] ${msg}`)
const warn = (msg) => console.log(`[WARN] ${msg}`)
const error = (msg) => console.error(`[ERROR] ${msg}`)
const success = (msg) => console.log(`[SUCCESS] ${msg}`)

// --- Error Codes ---

const ERROR_CODES = {
  WECHAT_NOT_FOUND: 'WECHAT_NOT_FOUND',
  WECHAT_PROCESS_AMBIGUOUS: 'WECHAT_PROCESS_AMBIGUOUS',
  HOOK_INIT_FAILED: 'HOOK_INIT_FAILED',
  UAC_CANCELLED: 'UAC_CANCELLED',
  LOGIN_TIMEOUT: 'LOGIN_TIMEOUT',
  KEY_POLL_TIMEOUT: 'KEY_POLL_TIMEOUT',
  EXTRACTOR_CRASHED: 'EXTRACTOR_CRASHED',
  EXTRACTION_CANCELLED: 'EXTRACTION_CANCELLED',
}

class KeyExtractorError extends Error {
  constructor(code, message, details) {
    super(message)
    this.name = 'KeyExtractorError'
    this.code = code
    this.details = details || {}
  }
}

// --- Status File Protocol ---

function writeStatusFile(statusDir, status) {
  if (!statusDir) return
  try {
    const statusPath = join(statusDir, 'status.json')
    const tmpPath = statusPath + '.tmp'
    let previous = {}
    try {
      if (existsSync(statusPath)) previous = JSON.parse(readFileSync(statusPath, 'utf8'))
    } catch {}
    const data = { ...previous, ...status, updatedAt: new Date().toISOString() }
    writeFileSync(tmpPath, JSON.stringify(data, null, 2), 'utf8')
    try { renameSync(tmpPath, statusPath) } catch {
      writeFileSync(statusPath, JSON.stringify(data, null, 2), 'utf8')
      try { unlinkSync(tmpPath) } catch {}
    }
  } catch {}
}

function isCancellationRequested(statusDir) {
  return !!(statusDir && existsSync(join(statusDir, 'cancel.request')))
}

function writeKeyFile(statusDir, key) {
  if (!statusDir) return
  try {
    const keyPath = join(statusDir, 'key.tmp')
    writeFileSync(keyPath, key, { encoding: 'utf8', mode: 0o600 })
  } catch {}
}

// --- Path Resolution ---

function resolveProjectRoot() {
  // electron-builder extraResources location.
  if (process.resourcesPath && existsSync(join(process.resourcesPath, 'resources', 'key'))) {
    return process.resourcesPath
  }
  // Walk up from this file to find the project root (where resources/ lives)
  let dir = __dirname
  for (let i = 0; i < 5; i++) {
    if (existsSync(join(dir, 'resources', 'key'))) return dir
    dir = join(dir, '..')
  }
  // Fallback: try cwd
  const cwd = process.cwd()
  if (existsSync(join(cwd, 'resources', 'key'))) return cwd
  return null
}

function resolveDllPath(override) {
  if (override && existsSync(override)) return override
  if (process.env.WX_KEY_DLL_PATH && existsSync(process.env.WX_KEY_DLL_PATH)) return process.env.WX_KEY_DLL_PATH
  const root = resolveProjectRoot()
  if (!root) return null
  const archDir = process.arch === 'arm64' ? 'arm64' : 'x64'
  const candidates = [
    join(root, 'resources', 'key', 'win32', archDir, 'wx_key.dll'),
    join(root, 'resources', 'key', 'win32', 'x64', 'wx_key.dll'),
  ]
  return candidates.find(p => existsSync(p)) || null
}

function resolveHelperPath(platform, override) {
  if (override && existsSync(override)) return override
  if (process.env.WX_KEY_HELPER_PATH && existsSync(process.env.WX_KEY_HELPER_PATH)) return process.env.WX_KEY_HELPER_PATH
  const root = resolveProjectRoot()
  if (!root) return null
  const archDir = process.arch === 'arm64' ? 'arm64' : 'x64'
  const helperName = platform === 'linux' ? 'xkey_helper_linux' : 'xkey_helper'
  const candidates = [
    join(root, 'resources', 'key', platform, archDir, helperName),
    join(root, 'resources', 'key', platform, 'universal', helperName),
    join(root, 'resources', 'key', platform, 'x64', helperName),
  ]
  return candidates.find(p => existsSync(p)) || null
}

async function computeDllSha256(dllPath) {
  try {
    const content = readFileSync(dllPath)
    return crypto.createHash('sha256').update(content).digest('hex').toUpperCase()
  } catch {
    return null
  }
}

// --- Windows Process Discovery ---

async function findWeChatMainProcess() {
  // Use PowerShell Get-CimInstance for reliable process enumeration
  const psScript = `Get-CimInstance Win32_Process -Filter "Name='Weixin.exe' OR Name='WeChat.exe'" | Select-Object ProcessId, ExecutablePath, CommandLine, ParentProcessId | ConvertTo-Json -Compress`

  let stdout
  try {
    ;({ stdout } = await execFileAsync('powershell', [
      '-NoProfile', '-NonInteractive', '-Command', psScript,
    ], { windowsHide: true, timeout: 10000, encoding: 'utf8' }))
  } catch (e) {
    log(`进程枚举失败: ${e.message}`)
    return []
  }

  if (!stdout || !stdout.trim()) return []

  let raw
  try {
    raw = JSON.parse(stdout.trim())
  } catch {
    return []
  }

  // PowerShell returns a single object when there's only one result
  const processes = Array.isArray(raw) ? raw : [raw]

  return processes
    .filter(p => p && p.ProcessId > 0 && p.ExecutablePath)
    .map(p => ({
      pid: p.ProcessId,
      exePath: p.ExecutablePath,
      commandLine: p.CommandLine || '',
      parentPid: p.ParentProcessId || 0,
    }))
}

function isMainWeChatProcess(proc) {
  // Main process: no --type= argument in command line
  return !proc.commandLine.includes('--type=')
}

async function selectMainWeChatProcess(candidates) {
  const mainProcesses = candidates.filter(isMainWeChatProcess)

  if (mainProcesses.length === 0) {
    throw new KeyExtractorError(
      ERROR_CODES.WECHAT_NOT_FOUND,
      '未找到微信主进程，请先启动微信并登录'
    )
  }

  if (mainProcesses.length === 1) {
    return mainProcesses[0]
  }

  // Multiple main processes — prefer parent process (one that spawned the others)
  const childPids = new Set(mainProcesses.filter(p => p.parentPid > 0).map(p => p.parentPid))
  const parentProcess = mainProcesses.find(p => childPids.has(p.pid))
  if (parentProcess) return parentProcess

  // Cannot disambiguate — report error
  throw new KeyExtractorError(
    ERROR_CODES.WECHAT_PROCESS_AMBIGUOUS,
    `检测到 ${mainProcesses.length} 个微信主进程，无法唯一确定，请退出多余的微信实例后重试`,
    { pids: mainProcesses.map(p => p.pid) }
  )
}

async function getExeVersion(exePath) {
  // Use PowerShell to read the file version info
  try {
    const psScript = `(Get-Item '${exePath.replace(/'/g, "''")}').VersionInfo.FileVersion`
    const { stdout } = await execFileAsync('powershell', [
      '-NoProfile', '-NonInteractive', '-Command', psScript,
    ], { windowsHide: true, timeout: 10000, encoding: 'utf8' })
    const version = (stdout || '').trim()
    if (version && /^[\d.]+$/.test(version)) return version
  } catch {}

  // Fallback: wmic
  try {
    const wmiPath = exePath.replace(/\\/g, '\\\\')
    const { stdout } = await execFileAsync('wmic', [
      'datafile', 'where', `name='${wmiPath}'`, 'get', 'Version', '/format:value',
    ], { windowsHide: true, timeout: 10000, encoding: 'utf8' })
    const match = (stdout || '').match(/Version=(.+)/i)
    if (match) return match[1].trim()
  } catch {}

  return null
}

// --- Windows Implementation ---

async function extractKeyWindows(options = {}) {
  const dllPath = resolveDllPath(options.dllPath)
  if (!dllPath) {
    throw new Error('wx_key.dll not found. Set --dll-path or WX_KEY_DLL_PATH, or run from the project root.')
  }
  log(`DLL path: ${dllPath}`)

  let koffi
  try {
    koffi = require('koffi')
  } catch {
    try { koffi = require(join(__dirname, '..', 'wx-mcp-server', 'node_modules', 'koffi')) }
    catch { throw new Error('koffi not installed. Run: npm install') }
  }

  // Handle network paths
  let actualDllPath = dllPath
  if (dllPath.startsWith('\\\\')) {
    const tempDir = join(os.tmpdir(), 'wxlens_dll_cache')
    if (!existsSync(tempDir)) mkdirSync(tempDir, { recursive: true })
    const localPath = join(tempDir, 'wx_key.dll')
    if (!existsSync(localPath)) copyFileSync(dllPath, localPath)
    actualDllPath = localPath
  }

  const lib = koffi.load(actualDllPath)
  const initHook = lib.func('bool InitializeHook(uint32 targetPid)')
  const pollKeyData = lib.func('bool PollKeyData(_Out_ char *keyBuffer, int bufferSize)')
  const getStatusMessage = lib.func('bool GetStatusMessage(_Out_ char *msgBuffer, int bufferSize, _Out_ int *outLevel)')
  const cleanupHook = lib.func('bool CleanupHook()')

  const decodeUtf8 = (buf) => {
    const nullIdx = buf.indexOf(0)
    return buf.toString('utf8', 0, nullIdx > -1 ? nullIdx : undefined).trim()
  }

  // Load kernel32 for process management
  const kernel32 = koffi.load('kernel32.dll')

  // Load user32 for window enumeration
  const user32 = koffi.load('user32.dll')
  const WNDENUMPROC = koffi.proto('bool __stdcall (void *hWnd, intptr_t lParam)')
  const WNDENUMPROC_PTR = koffi.pointer(WNDENUMPROC)
  const EnumWindows = user32.func('EnumWindows', 'bool', [WNDENUMPROC_PTR, 'intptr_t'])
  const GetWindowTextW = user32.func('GetWindowTextW', 'int', ['void*', koffi.out('uint16*'), 'int'])
  const GetWindowTextLengthW = user32.func('GetWindowTextLengthW', 'int', ['void*'])
  const GetClassNameW = user32.func('GetClassNameW', 'int', ['void*', koffi.out('uint16*'), 'int'])
  const GetWindowThreadProcessId = user32.func('GetWindowThreadProcessId', 'uint32', ['void*', koffi.out('uint32*')])
  const IsWindowVisible = user32.func('IsWindowVisible', 'bool', ['void*'])
  const EnumChildWindows = user32.func('EnumChildWindows', 'bool', ['void*', WNDENUMPROC_PTR, 'intptr_t'])

  const WECHAT_WINDOW_TITLES = ['微信', 'WeChat', 'Weixin']
  const LOGIN_KEYWORDS = ['登录', '扫码', '二维码', 'qrcode', 'scan', 'login']
  const WECHAT_CLASS_NAMES = ['TXGuiFoundation', 'Qt5', 'Chrome_WidgetWin_0', 'WeChatMainWndForPC']

  const getWindowText = (hWnd) => {
    const len = GetWindowTextLengthW(hWnd)
    if (len <= 0) return ''
    const buf = Buffer.alloc((len + 1) * 2)
    GetWindowTextW(hWnd, buf, len + 1)
    return buf.toString('ucs2', 0, len * 2).replace(/\0+$/, '')
  }

  const getClassName = (hWnd) => {
    const buf = Buffer.alloc(512)
    const len = GetClassNameW(hWnd, buf, 256)
    if (len <= 0) return ''
    return buf.toString('ucs2', 0, len * 2).replace(/\0+$/, '')
  }

  const isLoginRelatedText = (text) => {
    const lower = text.toLowerCase()
    return LOGIN_KEYWORDS.some(k => lower.includes(k))
  }

  // Find window by PID using koffi (used after process is already identified)
  const findWindowForPid = (targetPid) => {
    let result = null
    const callback = koffi.register((hWnd, _lParam) => {
      if (!IsWindowVisible(hWnd)) return true
      const pidBuf = Buffer.alloc(4)
      GetWindowThreadProcessId(hWnd, pidBuf)
      const pid = pidBuf.readUInt32LE(0)
      if (pid !== targetPid) return true
      const title = getWindowText(hWnd)
      const className = getClassName(hWnd)
      result = { hWnd, pid, title, className }
      return false
    }, WNDENUMPROC_PTR)
    EnumWindows(callback, 0)
    koffi.unregister(callback)
    return result
  }

  const isLoginState = (hWnd) => {
    let childCount = 0
    let loginDetected = false
    const childCallback = koffi.register((childHWnd, _lParam) => {
      childCount++
      const title = getWindowText(childHWnd)
      const cls = getClassName(childHWnd)
      if (isLoginRelatedText(title) || isLoginRelatedText(cls)) loginDetected = true
      return true
    }, WNDENUMPROC_PTR)
    EnumChildWindows(hWnd, childCallback, 0)
    koffi.unregister(childCallback)
    return { childCount, loginDetected }
  }

  const waitForReady = async (hWnd, timeoutMs) => {
    const start = Date.now()
    while (Date.now() - start < timeoutMs) {
      const { childCount, loginDetected } = isLoginState(hWnd)
      if (loginDetected) return { ready: true, loginDetected: true }
      if (childCount >= 14) return { ready: true, loginDetected: false }
      let hasKnownClass = false
      const classCheckCallback = koffi.register((childHWnd, _lParam) => {
        const cls = getClassName(childHWnd)
        if (WECHAT_CLASS_NAMES.some(c => cls.includes(c))) { hasKnownClass = true; return false }
        return true
      }, WNDENUMPROC_PTR)
      EnumChildWindows(hWnd, classCheckCallback, 0)
      koffi.unregister(classCheckCallback)
      if (hasKnownClass) return { ready: true, loginDetected: false }
      await new Promise(r => setTimeout(r, 500))
    }
    return { ready: false, loginDetected: false }
  }

  // Main flow — new process-based discovery
  const timeout = options.timeout || 180000
  const deadline = Date.now() + timeout
  const statusDir = options.statusDir || null

  // Step 1: Find WeChat main process via PowerShell (no window-class guessing)
  log('正在通过进程列表查找微信...')
  writeStatusFile(statusDir, {
    attemptId: options.attemptId || null,
    state: 'locating_wechat',
  })

  let candidates = await findWeChatMainProcess()
  if (candidates.length === 0) {
    // Try to auto-start WeChat
    const executable = await findWeChatExecutable()
    if (executable) {
      log(`正在启动微信: ${executable}`)
      writeStatusFile(statusDir, {
        attemptId: options.attemptId || null,
        state: 'launching_wechat',
        wechatPath: executable,
      })
      const child = require('child_process').spawn(executable, [], {
        detached: true,
        stdio: 'ignore',
        windowsHide: false,
      })
      child.unref()
    } else {
      warn('未自动找到微信安装位置，请手动启动微信')
    }

    log('等待微信启动...')
    const waitStart = Date.now()
    while (candidates.length === 0 && Date.now() - waitStart < timeout) {
      if (isCancellationRequested(statusDir)) {
        throw new KeyExtractorError(ERROR_CODES.EXTRACTION_CANCELLED, '用户取消了提取')
      }
      await new Promise(r => setTimeout(r, 2000))
      candidates = await findWeChatMainProcess()
    }
    if (candidates.length === 0) {
      throw new KeyExtractorError(
        ERROR_CODES.WECHAT_NOT_FOUND,
        '未找到微信进程，请先启动微信并登录'
      )
    }
  }

  // Step 2: Select the main process (exclude --type= subprocesses)
  const selectedProc = await selectMainWeChatProcess(candidates)
  const wechatPid = selectedProc.pid
  const wechatPath = selectedProc.exePath

  // Step 3: Read file version
  log(`正在读取微信版本 (${wechatPath})...`)
  let wechatVersion = await getExeVersion(wechatPath)
  if (!wechatVersion) {
    wechatVersion = 'unknown'
    warn(`无法读取微信版本信息，将继续使用 WeFlow 原生提取流程: ${wechatPath}`)
  }

  // Step 4: Record DLL identity for diagnostics. The WeFlow extractor is not
  // gated by a hard-coded WeChat version list; version changes alone are not
  // evidence that the hook is incompatible.
  const dllSha256 = await computeDllSha256(dllPath)
  log(`DLL SHA-256: ${dllSha256 || 'N/A'}`)

  // Safety logs (no key, no private data)
  log(`[Key] selected_wechat_pid=${wechatPid}`)
  log(`[Key] selected_wechat_path=${wechatPath}`)
  log(`[Key] selected_wechat_version=${wechatVersion}`)
  log(`[Key] selected_wechat_command=${selectedProc.commandLine.includes('--type=') ? '(subprocess)' : '(main)'}`)

  writeStatusFile(statusDir, {
    attemptId: options.attemptId || null,
    state: 'checking_version',
    workerPid: process.pid,
    wechatPid,
    wechatPath,
    wechatVersion,
    dllSha256: dllSha256 || null,
  })

  // Step 5: Find window for already-identified PID
  log(`正在查找微信窗口 (PID: ${wechatPid})...`)
  let wechat = findWindowForPid(wechatPid)

  if (!wechat) {
    // Window might not be ready yet — wait briefly
    log('等待微信窗口出现...')
    const windowWaitStart = Date.now()
    while (!wechat && Date.now() - windowWaitStart < 15000) {
      if (isCancellationRequested(statusDir)) {
        throw new KeyExtractorError(ERROR_CODES.EXTRACTION_CANCELLED, '用户取消了提取')
      }
      await new Promise(r => setTimeout(r, 1000))
      wechat = findWindowForPid(wechatPid)
    }
    if (!wechat) {
      warn('未找到微信窗口句柄，将直接尝试 hook')
      wechat = { hWnd: null, pid: wechatPid, title: '', className: '' }
    }
  }

  log(`[Key] selected_window_title=${wechat.title || '(none)'}`)
  log(`[Key] selected_window_class=${wechat.className || '(none)'}`)
  log(`检测到微信窗口 (PID: ${wechat.pid}): "${wechat.title}"`)

  // Check login state (only if we have a window handle)
  if (wechat.hWnd) {
    const { loginDetected } = isLoginState(wechat.hWnd)
    if (loginDetected) {
      log('检测到微信处于登录/扫码界面，请先登录微信')
      writeStatusFile(statusDir, {
        attemptId: options.attemptId || null,
        state: 'waiting_for_login',
        wechatPid, wechatPath, wechatVersion,
      })
    }

    // Wait for UI readiness
    log('正在等待微信界面就绪...')
    const ready = await waitForReady(wechat.hWnd, Math.min(15000, deadline - Date.now()))
    if (!ready.ready) {
      warn('等待界面就绪超时，继续尝试...')
    }
    if (ready.loginDetected) {
      log('检测到登录界面，将保持提取器运行；请现在登录微信')
      writeStatusFile(statusDir, {
        attemptId: options.attemptId || null,
        state: 'waiting_for_login',
        wechatPid, wechatPath, wechatVersion,
      })
    }
  }

  // Step 6: Hook
  if (isCancellationRequested(statusDir)) {
    throw new KeyExtractorError(ERROR_CODES.EXTRACTION_CANCELLED, '用户取消了提取')
  }
  log('正在初始化 hook...')
  writeStatusFile(statusDir, {
    attemptId: options.attemptId || null,
    state: 'initializing_hook',
    wechatPid, wechatPath, wechatVersion,
  })

  const hookOk = initHook(wechat.pid)
  if (!hookOk) {
    const lastErr = lib.func('const char* GetLastErrorMsg()')
    const errMsg = lastErr ? decodeUtf8(lastErr()) : 'unknown'
    throw new KeyExtractorError(
      ERROR_CODES.HOOK_INIT_FAILED,
      `hook 初始化失败: ${errMsg}`,
      { pid: wechatPid, path: wechatPath, version: wechatVersion, dllError: errMsg }
    )
  }
  log('hook 已安装，正在轮询密钥...')
  writeStatusFile(statusDir, {
    attemptId: options.attemptId || null,
    state: 'polling_key',
    wechatPid, wechatPath, wechatVersion,
  })

  // Step 7: Poll
  try {
    const keyBuffer = Buffer.alloc(128)
    while (Date.now() < deadline) {
      if (isCancellationRequested(statusDir)) {
        throw new KeyExtractorError(ERROR_CODES.EXTRACTION_CANCELLED, '用户取消了提取')
      }
      if (pollKeyData(keyBuffer, keyBuffer.length)) {
        const key = decodeUtf8(keyBuffer)
        if (key.length === 64 && /^[0-9a-fA-F]{64}$/.test(key)) {
          log('密钥获取成功！')
          writeStatusFile(statusDir, {
            attemptId: options.attemptId || null,
            state: 'success',
            wechatPid, wechatPath, wechatVersion,
            keyPresent: true,
          })
          writeKeyFile(statusDir, key)
          return key
        }
      }

      // Read status messages
      for (let i = 0; i < 3; i++) {
        const statusBuffer = Buffer.alloc(256)
        const levelOut = [0]
        if (!getStatusMessage(statusBuffer, statusBuffer.length, levelOut)) break
        const msg = decodeUtf8(statusBuffer)
        if (msg) log(`  ${msg}`)
      }

      await new Promise(r => setTimeout(r, 120))
    }

    throw new KeyExtractorError(
      ERROR_CODES.KEY_POLL_TIMEOUT,
      `获取超时 (${timeout / 1000}s)，请确保微信已登录并处于正常使用状态`,
      { pid: wechatPid, path: wechatPath, version: wechatVersion }
    )
  } finally {
    try { cleanupHook() } catch {}
  }
}

async function findWeChatExecutable() {
  const candidates = []
  const addInstallDir = (dir) => {
    if (!dir) return
    candidates.push(join(dir, 'Weixin.exe'), join(dir, 'WeChat.exe'))
  }

  // 微信官方安装程序常用的注册表位置。
  const registryQueries = [
    ['HKCU\\Software\\Tencent\\Weixin', 'InstallPath'],
    ['HKCU\\Software\\Tencent\\WeChat', 'InstallPath'],
    ['HKLM\\Software\\Tencent\\Weixin', 'InstallPath'],
    ['HKLM\\Software\\Tencent\\WeChat', 'InstallPath'],
    ['HKLM\\Software\\WOW6432Node\\Tencent\\WeChat', 'InstallPath'],
  ]
  for (const [key, value] of registryQueries) {
    try {
      const { stdout } = await execFileAsync('reg.exe', ['query', key, '/v', value], { windowsHide: true })
      const match = stdout.match(/REG_\w+\s+(.+)$/mi)
      if (match) addInstallDir(match[1].trim())
    } catch {}
  }

  const roots = [process.env.ProgramFiles, process.env['ProgramFiles(x86)']].filter(Boolean)
  for (const root of roots) {
    candidates.push(
      join(root, 'Tencent', 'Weixin', 'Weixin.exe'),
      join(root, 'Tencent', 'WeChat', 'WeChat.exe')
    )
  }

  // Portable/custom installations are common. Check a small set of known
  // layouts on existing drive letters, including A:\WeChat\Weixin.
  for (let code = 65; code <= 90; code++) {
    const drive = String.fromCharCode(code) + ':\\'
    candidates.push(
      join(drive, 'WeChat', 'Weixin', 'Weixin.exe'),
      join(drive, 'WeChat', 'WeChat.exe'),
      join(drive, 'Tencent', 'Weixin', 'Weixin.exe'),
      join(drive, 'Tencent', 'WeChat', 'WeChat.exe')
    )
  }

  return candidates.find(existsSync) || null
}

async function ensureWeChatRunning() {
  const candidates = await findWeChatMainProcess()
  const mainProcesses = candidates.filter(isMainWeChatProcess)
  if (mainProcesses.length > 0) {
    return { launched: false, executable: mainProcesses[0].exePath || null }
  }

  const executable = await findWeChatExecutable()
  if (!executable) {
    throw new Error('未找到微信安装位置，请先手动启动微信')
  }

  log(`正在启动微信: ${executable}`)
  const child = require('child_process').spawn(executable, [], {
    detached: true,
    stdio: 'ignore',
    windowsHide: false,
  })
  child.unref()

  return { launched: true, executable }
}

// --- macOS Implementation ---

async function extractKeyMac(options = {}) {
  const helperPath = resolveHelperPath('macos', options.helperPath)
  if (!helperPath) {
    throw new Error('xkey_helper not found. Set --helper-path or WX_KEY_HELPER_PATH.')
  }
  log(`Helper path: ${helperPath}`)

  // Check SIP
  try {
    const { stdout } = await execFileAsync('/usr/bin/csrutil', ['status'])
    if (stdout.includes('enabled') && !stdout.includes('disabled')) {
      warn('SIP (System Integrity Protection) 已启用')
      warn('macOS 密钥提取需要关闭 SIP：重启进入恢复模式 → 终端 → csrutil disable')
      warn('继续尝试，但可能会失败...')
    }
  } catch { }

  // Find WeChat PID
  log('正在查找微信进程...')
  let pid = null
  try {
    const { stdout } = await execFileAsync('pgrep', ['-x', 'WeChat'])
    pid = parseInt(stdout.trim().split('\n')[0], 10)
  } catch {
    try {
      const { stdout } = await execAsync("ps -A | grep -i '[W]eChat' | head -1")
      const match = stdout.trim().match(/\s*(\d+)/)
      if (match) pid = parseInt(match[1], 10)
    } catch { }
  }

  if (!pid) throw new Error('未找到微信进程，请先启动微信')
  log(`检测到微信进程 (PID: ${pid})`)

  // Run xkey_helper with admin privileges
  const timeout = options.timeout || 60000
  log('正在以管理员权限运行密钥提取（需要输入密码）...')

  const script = `do shell script "\\"${helperPath}\\" ${pid} ${timeout}" with administrator privileges with prompt "本 skill 需要管理员权限来提取微信数据库密钥"`

  try {
    const { stdout, stderr } = await execFileAsync('osascript', ['-e', script], { timeout: timeout + 30000 })

    // Parse output - xkey_helper outputs JSON or key=value lines
    const output = stdout + '\n' + stderr

    // Try JSON output
    try {
      const json = JSON.parse(stdout.trim())
      if (json.success && json.key) return json.key
      if (json.key) return json.key
    } catch { }

    // Try hex64 pattern
    const hex64Match = output.match(/hex64=([0-9a-fA-F]{64})/)
    if (hex64Match) return hex64Match[1]

    // Try key= pattern
    const keyMatch = output.match(/key[=:]\s*([0-9a-fA-F]{64})/i)
    if (keyMatch) return keyMatch[1]

    // Try any 64-char hex
    const anyHex = output.match(/\b([0-9a-fA-F]{64})\b/)
    if (anyHex) return anyHex[1]

    throw new Error(`密钥提取失败。输出:\n${output}`)
  } catch (e) {
    if (e.message.includes('User canceled')) throw new Error('用户取消了管理员授权')
    throw e
  }
}

// --- Linux Implementation ---

async function extractKeyLinux(options = {}) {
  const helperPath = resolveHelperPath('linux', options.helperPath)
  if (!helperPath) {
    throw new Error('xkey_helper_linux not found. Set --helper-path or WX_KEY_HELPER_PATH.')
  }
  log(`Helper path: ${helperPath}`)

  // Find WeChat PID
  log('正在查找微信进程...')
  let pid = null
  try {
    const { stdout } = await execFileAsync('pidof', ['wechat', 'wechat-bin', 'xwechat'])
    pid = parseInt(stdout.trim().split(/\s+/)[0], 10)
  } catch {
    try {
      const { stdout } = await execFileAsync('pgrep', ['-f', '[w]echat'])
      pid = parseInt(stdout.trim().split('\n')[0], 10)
    } catch { }
  }

  if (!pid) throw new Error('未找到微信进程，请先启动微信')
  log(`检测到微信进程 (PID: ${pid})`)

  const timeout = options.timeout || 60000

  // Phase 1: Scan
  log('正在扫描目标地址...')
  let targetAddr = null
  try {
    const { stdout } = await execFileAsync(helperPath, ['db_scan', String(pid)], { timeout: 30000 })
    const addrMatch = stdout.match(/target[_-]?addr[=:]\s*(0x[0-9a-fA-F]+)/i) || stdout.match(/address[=:]\s*(0x[0-9a-fA-F]+)/i)
    if (addrMatch) targetAddr = addrMatch[1]
  } catch { }

  // Phase 2: Hook (needs sudo)
  log('正在以管理员权限 hook（需要输入密码）...')
  const hookArgs = targetAddr
    ? ['db_hook', String(pid), targetAddr, String(timeout)]
    : ['db_hook', String(pid), String(timeout)]

  const hookCmd = `"${helperPath}" ${hookArgs.join(' ')}`

  try {
    const sudo = require('@vscode/sudo-prompt')
    const result = await new Promise((resolve, reject) => {
      sudo.exec(hookCmd, { name: 'Wechat Content Router Key Extractor' }, (error, stdout, stderr) => {
        if (error) reject(error)
        else resolve(stdout + '\n' + stderr)
      })
    })

    const hex64Match = result.match(/hex64=([0-9a-fA-F]{64})/)
    if (hex64Match) return hex64Match[1]

    const keyMatch = result.match(/key[=:]\s*([0-9a-fA-F]{64})/i)
    if (keyMatch) return keyMatch[1]

    const anyHex = result.match(/\b([0-9a-fA-F]{64})\b/)
    if (anyHex) return anyHex[1]

    throw new Error(`密钥提取失败。输出:\n${result}`)
  } catch (e) {
    if (e.message && e.message.includes('cancelled')) throw new Error('用户取消了管理员授权')
    throw new Error(`sudo 执行失败: ${e.message}`)
  }
}

// --- Main Entry ---

async function extractKey(options = {}) {
  const platform = options.platform || process.platform

  log(`平台: ${platform}`)
  log(`架构: ${process.arch}`)

  try {
    switch (platform) {
      case 'win32':
        return await extractKeyWindows(options)
      case 'darwin':
        return await extractKeyMac(options)
      case 'linux':
        return await extractKeyLinux(options)
      default:
        throw new Error(`不支持的平台: ${platform}`)
    }
  } catch (e) {
    const errorCode = e && e.code ? e.code : ERROR_CODES.EXTRACTOR_CRASHED
    const cancelled = errorCode === ERROR_CODES.EXTRACTION_CANCELLED
    let existingStatus = null
    try {
      if (options.statusDir) {
        existingStatus = JSON.parse(readFileSync(join(options.statusDir, 'status.json'), 'utf8'))
      }
    } catch {}
    const terminalStates = ['success', 'failed', 'cancelled', 'timed_out']
    if (!existingStatus || !terminalStates.includes(existingStatus.state)) {
      writeStatusFile(options.statusDir, {
        attemptId: options.attemptId || null,
        state: cancelled ? 'cancelled' : 'failed',
        errorCode,
        errorMessage: e && e.message ? e.message : String(e),
        keyPresent: false,
      })
    }
    throw e
  }
}

module.exports = { extractKey, ensureWeChatRunning, findWeChatExecutable, ERROR_CODES, KeyExtractorError }
