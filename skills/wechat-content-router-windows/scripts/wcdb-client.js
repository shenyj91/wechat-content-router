/**
 * WCDB 原生数据库客户端
 * 通过 koffi FFI 调用 wcdb_api.dll，直接读取微信加密数据库
 */

const { join, dirname, basename } = require('path')
const { existsSync, readdirSync, statSync } = require('fs')

/**
 * 归一化名称查询返回值
 * 兼容 { wxid: "name" } 和 { success: true, map: { wxid: "name" } } 两种格式
 * @param {*} raw
 * @returns {Record<string, string>}
 */
function normalizeNameMap(raw) {
  if (!raw || typeof raw !== 'object') return {}
  // 直接是 { wxid: name } 的平面对象
  if (!Array.isArray(raw) && !raw.success && !raw.map) return raw
  // 带 success/map 的结构
  if (raw.map && typeof raw.map === 'object') return raw.map
  return {}
}

class WcdbClient {
  constructor() {
    this.lib = null
    this.koffi = null
    this.handle = null
    this.initialized = false
    this.resourcesPath = null

    // DLL 函数引用
    this._initProtection = null
    this._wcdbInit = null
    this._wcdbShutdown = null
    this._wcdbOpenAccount = null
    this._wcdbSetMyWxid = null
    this._wcdbFreeString = null
    this._wcdbGetSessions = null
    this._wcdbGetMessages = null
    this._wcdbGetNewMessages = null
    this._wcdbGetMessageCount = null
    this._wcdbSearchMessages = null
    this._wcdbGetContact = null
    this._wcdbGetContactsCompact = null
    this._wcdbGetDisplayNames = null
    this._wcdbGetAvatarUrls = null
    this._wcdbGetGroupMembers = null
    this._wcdbGetGroupNicknames = null
    this._wcdbGetMessageById = null
    this._wcdbExecQuery = null
    this._wcdbGetLogs = null
    this._wcdbGetAggregateStats = null
    this._wcdbStartMonitorPipe = null
    this._wcdbStopMonitorPipe = null
    this._wcdbGetMonitorPipeName = null
  }

  /**
   * 设置资源路径（DLL 所在的根目录）
   */
  setResourcesPath(resourcesPath) {
    this.resourcesPath = resourcesPath
  }

  /**
   * 查找 WCDB DLL 目录
   */
  _findDllDir() {
    // 优先使用环境变量
    if (process.env.WCDB_DLL_PATH && existsSync(process.env.WCDB_DLL_PATH)) {
      return process.env.WCDB_DLL_PATH
    }

    const roots = [
      this.resourcesPath,
      join(process.cwd(), 'resources'),
    ].filter(Boolean)

    const isArm64 = process.arch === 'arm64'
    const platformDir = 'win32'
    const archDir = isArm64 ? 'arm64' : 'x64'

    for (const root of roots) {
      const candidate = join(root, 'wcdb', platformDir, archDir)
      if (existsSync(join(candidate, 'wcdb_api.dll'))) return candidate
      const fallback = join(root, 'wcdb', platformDir, 'x64')
      if (existsSync(join(fallback, 'wcdb_api.dll'))) return fallback
    }
    return null
  }

  /**
   * 递归查找 session.db
   */
  _findSessionDb(dir, depth = 0) {
    if (depth > 5) return null
    try {
      const entries = readdirSync(dir)
      for (const entry of entries) {
        if (entry.toLowerCase() === 'session.db') {
          const full = join(dir, entry)
          if (statSync(full).isFile()) return full
        }
      }
      for (const entry of entries) {
        const full = join(dir, entry)
        try {
          if (statSync(full).isDirectory()) {
            const found = this._findSessionDb(full, depth + 1)
            if (found) return found
          }
        } catch {}
      }
    } catch {}
    return null
  }

  /**
   * 从 koffi 指针解码 UTF-8 字符串
   */
  _decodeJsonPtr(ptr) {
    if (!ptr) return null
    try {
      // 标准 koffi 写法：'char*' 按 null 结尾解码 C 字符串（UTF-8 JSON）
      return this.koffi.decode(ptr, 'char*')
    } catch {
      return null
    }
  }

  /**
   * 解析 JSON 并释放内存
   */
  _parseAndFree(ptr) {
    const str = this._decodeJsonPtr(ptr)
    if (!str) return null
    try {
      return JSON.parse(str)
    } catch {
      return str
    } finally {
      if (ptr) {
        try { this._wcdbFreeString(ptr) } catch {}
      }
    }
  }

  /**
   * 初始化 DLL 和 WCDB 运行时
   */
  async initialize() {
    if (this.initialized) return true

    this.koffi = require('koffi')
    const dllDir = this._findDllDir()
    if (!dllDir) throw new Error('wcdb_api.dll not found. Set WX_MCP_RESOURCES env or run from WxLens project root.')

    // 预加载 MSVC 运行时 DLL
    const runtimeDir = join(this.resourcesPath || '', 'runtime', 'win32')
    for (const dll of ['vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'msvcp140_1.dll']) {
      const p = join(runtimeDir, dll)
      if (existsSync(p)) try { this.koffi.load(p) } catch {}
    }

    // 预加载 WCDB 核心 DLL
    const wcdbCorePath = join(dllDir, 'WCDB.dll')
    if (existsSync(wcdbCorePath)) try { this.koffi.load(wcdbCorePath) } catch {}

    const sdl2Path = join(dllDir, 'SDL2.dll')
    if (existsSync(sdl2Path)) try { this.koffi.load(sdl2Path) } catch {}

    // 加载主 DLL
    const dllPath = join(dllDir, 'wcdb_api.dll')
    this.lib = this.koffi.load(dllPath)

    // 绑定函数
    this._initProtection = this.lib.func('int32 InitProtection(const char* resourcePath)')
    this._wcdbInit = this.lib.func('int32 wcdb_init()')
    this._wcdbShutdown = this.lib.func('int32 wcdb_shutdown()')
    this._wcdbOpenAccount = this.lib.func('int32 wcdb_open_account(const char* path, const char* key, _Out_ int64* handle)')
    this._wcdbFreeString = this.lib.func('void wcdb_free_string(void* ptr)')
    this._wcdbGetSessions = this.lib.func('int32 wcdb_get_sessions(int64 handle, _Out_ void** outJson)')
    this._wcdbGetMessages = this.lib.func('int32 wcdb_get_messages(int64 handle, const char* username, int32 limit, int32 offset, _Out_ void** outJson)')
    this._wcdbGetMessageCount = this.lib.func('int32 wcdb_get_message_count(int64 handle, const char* username, _Out_ int32* outCount)')
    this._wcdbSearchMessages = this.lib.func('int32 wcdb_search_messages(int64 handle, const char* sessionId, const char* keyword, int32 limit, int32 offset, int64 beginTimestamp, int64 endTimestamp, _Out_ void** outJson)')
    this._wcdbGetContact = this.lib.func('int32 wcdb_get_contact(int64 handle, const char* username, _Out_ void** outJson)')
    this._wcdbGetDisplayNames = this.lib.func('int32 wcdb_get_display_names(int64 handle, const char* usernamesJson, _Out_ void** outJson)')
    this._wcdbExecQuery = this.lib.func('int32 wcdb_exec_query(int64 handle, const char* kind, const char* dbPath, const char* sql, _Out_ void** outJson)')
    this._wcdbGetLogs = this.lib.func('int32 wcdb_get_logs(_Out_ void** outJson)')

    // 可选函数
    try { this._wcdbSetMyWxid = this.lib.func('int32 wcdb_set_my_wxid(int64 handle, const char* wxid)') } catch {}
    try { this._wcdbGetNewMessages = this.lib.func('int32 wcdb_get_new_messages(int64 handle, const char* sessionId, int32 minTime, int32 limit, _Out_ void** outJson)') } catch {}
    try { this._wcdbGetContactsCompact = this.lib.func('int32 wcdb_get_contacts_compact(int64 handle, const char* usernamesJson, _Out_ void** outJson)') } catch {}
    try { this._wcdbGetAvatarUrls = this.lib.func('int32 wcdb_get_avatar_urls(int64 handle, const char* usernamesJson, _Out_ void** outJson)') } catch {}
    try { this._wcdbGetGroupMembers = this.lib.func('int32 wcdb_get_group_members(int64 handle, const char* chatroomId, _Out_ void** outJson)') } catch {}
    try { this._wcdbGetGroupNicknames = this.lib.func('int32 wcdb_get_group_nicknames(int64 handle, const char* chatroomId, _Out_ void** outJson)') } catch {}
    try { this._wcdbGetAggregateStats = this.lib.func('int32 wcdb_get_aggregate_stats(int64 handle, const char* sessionIdsJson, int32 begin, int32 end, _Out_ void** outJson)') } catch {}
    try { this._wcdbGetMessageById = this.lib.func('int32 wcdb_get_message_by_id(int64 handle, const char* sessionId, int32 localId, _Out_ void** outJson)') } catch {}
    try { this._wcdbStartMonitorPipe = this.lib.func('int32 wcdb_start_monitor_pipe()') } catch {}
    try { this._wcdbStopMonitorPipe = this.lib.func('void wcdb_stop_monitor_pipe()') } catch {}
    try { this._wcdbGetMonitorPipeName = this.lib.func('int32 wcdb_get_monitor_pipe_name(_Out_ void** outName)') } catch {}

    // InitProtection
    const resourcePaths = [dllDir, dirname(dllDir), join(dllDir, '..', '..'), this.resourcesPath].filter(Boolean)
    let protectionOk = false
    for (const rp of resourcePaths) {
      if (this._initProtection(rp) === 0) { protectionOk = true; break }
    }
    if (!protectionOk) throw new Error('InitProtection failed')

    // wcdb_init
    const initCode = this._wcdbInit()
    if (initCode !== 0) {
      const logs = this._readLogs()
      throw new Error(`wcdb_init failed: ${initCode}. Logs: ${logs}`)
    }

    this.initialized = true
    return true
  }

  /**
   * 打开数据库
   */
  async open(accountDir, hexKey) {
    if (!this.initialized) await this.initialize()
    if (this.handle !== null) this.close()

    const dbStoragePath = join(accountDir, 'db_storage')
    if (!existsSync(dbStoragePath)) {
      throw new Error(`db_storage not found: ${dbStoragePath}`)
    }

    const sessionDbPath = this._findSessionDb(dbStoragePath)
    if (!sessionDbPath) throw new Error('session.db not found')

    const handleOut = [0]
    const code = this._wcdbOpenAccount(sessionDbPath, hexKey, handleOut)
    if (code !== 0 || handleOut[0] <= 0) {
      const logs = this._readLogs()
      throw new Error(`wcdb_open_account failed: ${code}. Logs: ${logs}`)
    }

    this.handle = handleOut[0]

    // 设置 wxid
    const wxid = basename(accountDir).replace(/_[a-zA-Z0-9]{4}$/, '')
    this.myWxid = wxid || ''
    if (this._wcdbSetMyWxid && wxid) {
      try { this._wcdbSetMyWxid(this.handle, wxid) } catch {}
    }

    return true
  }

  /**
   * 关闭数据库
   */
  close() {
    if (this.handle !== null || this.initialized) {
      try { this._wcdbShutdown() } catch {}
      this.handle = null
      this.initialized = false
    }
  }

  /**
   * 是否已连接
   */
  isConnected() {
    return this.handle !== null
  }

  _readLogs() {
    try {
      if (!this._wcdbGetLogs) return null
      const outPtr = [null]
      const rc = this._wcdbGetLogs(outPtr)
      if (rc === 0 && outPtr[0]) {
        const s = this._decodeJsonPtr(outPtr[0])
        this._wcdbFreeString(outPtr[0])
        return s
      }
    } catch {}
    return null
  }

  /**
   * 获取所有会话列表
   */
  async getSessions() {
    if (!this.handle) throw new Error('Database not connected')
    const outPtr = [null]
    const code = this._wcdbGetSessions(this.handle, outPtr)
    if (code !== 0 || !outPtr[0]) throw new Error(`getSessions failed: ${code}`)
    return this._parseAndFree(outPtr[0])
  }

  /**
   * 获取某会话的消息
   */
  async getMessages(sessionId, limit = 20, offset = 0) {
    if (!this.handle) throw new Error('Database not connected')
    const outPtr = [null]
    const code = this._wcdbGetMessages(this.handle, sessionId, limit, offset, outPtr)
    if (code !== 0 || !outPtr[0]) throw new Error(`getMessages failed: ${code}`)
    return this._parseAndFree(outPtr[0])
  }

  /**
   * 获取新消息（指定时间之后）
   */
  async getNewMessages(sessionId, minTime, limit = 50) {
    if (!this.handle) throw new Error('Database not connected')
    if (!this._wcdbGetNewMessages) throw new Error('getNewMessages not supported')
    const outPtr = [null]
    const code = this._wcdbGetNewMessages(this.handle, sessionId, minTime, limit, outPtr)
    if (code !== 0 || !outPtr[0]) throw new Error(`getNewMessages failed: ${code}`)
    return this._parseAndFree(outPtr[0])
  }

  /**
   * 获取消息数量
   */
  async getMessageCount(sessionId) {
    if (!this.handle) throw new Error('Database not connected')
    const countOut = [0]
    const code = this._wcdbGetMessageCount(this.handle, sessionId, countOut)
    if (code !== 0) throw new Error(`getMessageCount failed: ${code}`)
    return countOut[0]
  }

  /**
   * 搜索消息
   */
  async searchMessages(keyword, sessionId, limit = 20, offset = 0, beginTimestamp = 0, endTimestamp = 0) {
    if (!this.handle) throw new Error('Database not connected')
    if (!this._wcdbSearchMessages) throw new Error('searchMessages not supported')
    const outPtr = [null]
    const code = this._wcdbSearchMessages(
      this.handle, sessionId || '', keyword, limit, offset,
      BigInt(beginTimestamp), BigInt(endTimestamp), outPtr
    )
    if (code !== 0 || !outPtr[0]) throw new Error(`searchMessages failed: ${code}`)
    return this._parseAndFree(outPtr[0])
  }

  /**
   * 获取联系人信息
   */
  async getContact(username) {
    if (!this.handle) throw new Error('Database not connected')
    const outPtr = [null]
    const code = this._wcdbGetContact(this.handle, username, outPtr)
    if (code !== 0 || !outPtr[0]) throw new Error(`getContact failed: ${code}`)
    return this._parseAndFree(outPtr[0])
  }

  /**
   * 批量获取显示名
   */
  async getDisplayNames(usernames) {
    if (!this.handle) throw new Error('Database not connected')
    const outPtr = [null]
    const code = this._wcdbGetDisplayNames(this.handle, JSON.stringify(usernames), outPtr)
    if (code !== 0 || !outPtr[0]) throw new Error(`getDisplayNames failed: ${code}`)
    const raw = this._parseAndFree(outPtr[0])
    return normalizeNameMap(raw)
  }

  /**
   * 获取群聊成员群昵称
   * @param {string} chatroomId
   * @returns {Promise<Record<string, string>>} { wxid: groupNickname }
   */
  async getGroupNicknames(chatroomId) {
    if (!this.handle) throw new Error('Database not connected')
    if (!this._wcdbGetGroupNicknames) return {}
    const outPtr = [null]
    const code = this._wcdbGetGroupNicknames(this.handle, chatroomId, outPtr)
    if (code !== 0 || !outPtr[0]) return {}
    const raw = this._parseAndFree(outPtr[0])
    return normalizeNameMap(raw)
  }

  /**
   * 通过 sessionId + localId 获取完整消息
   * 用于补全搜索轻量结果缺少的 sender/type/serverId 等字段
   */
  async getMessageById(sessionId, localId) {
    if (!this.handle) throw new Error('Database not connected')
    if (!this._wcdbGetMessageById) return null
    if (!sessionId || !Number.isInteger(localId) || localId <= 0) return null

    const outPtr = [null]
    const code = this._wcdbGetMessageById(this.handle, sessionId, localId, outPtr)
    if (code !== 0 || !outPtr[0]) return null
    const value = this._parseAndFree(outPtr[0])
    return value && typeof value === 'object' && Object.keys(value).length ? value : null
  }

  /**
   * 执行自定义 SQL查询
   */
  async execQuery(kind, dbPath, sql) {
    if (!this.handle) throw new Error('Database not connected')
    const outPtr = [null]
    const code = this._wcdbExecQuery(this.handle, kind, dbPath || '', sql, outPtr)
    if (code !== 0 || !outPtr[0]) throw new Error(`execQuery failed: ${code}`)
    return this._parseAndFree(outPtr[0])
  }

  /**
   * 启动数据库变更监控（命名管道）
   */
  startMonitor(callback) {
    if (!this._wcdbStartMonitorPipe) return false
    const code = this._wcdbStartMonitorPipe()
    if (code !== 0) return false

    // 获取管道名
    let pipePath = '\\\\.\\pipe\\wxlens_monitor'
    if (this._wcdbGetMonitorPipeName) {
      try {
        const namePtr = [null]
        if (this._wcdbGetMonitorPipeName(namePtr) === 0 && namePtr[0]) {
          pipePath = this._decodeJsonPtr(namePtr[0])
          this._wcdbFreeString(namePtr[0])
        }
      } catch {}
    }

    // 连接管道
    const net = require('net')
    setTimeout(() => {
      try {
        const client = net.createConnection(pipePath, () => {})
        let buffer = ''
        client.on('data', (data) => {
          buffer += data.toString('utf8').replace(/\x00/g, '\n').replace(/}\s*{/g, '}\n{')
          const lines = buffer.split(/\r?\n/)
          buffer = lines.pop() || ''
          for (const line of lines) {
            if (line.trim()) {
              try {
                const parsed = JSON.parse(line)
                callback(parsed.action || 'update', parsed)
              } catch {}
            }
          }
        })
        client.on('error', () => {})
        client.on('close', () => {
          // 自动重连
          setTimeout(() => this.startMonitor(callback), 3000)
        })
        this._monitorClient = client
      } catch {}
    }, 100)
    return true
  }

  /**
   * 停止监控
   */
  stopMonitor() {
    if (this._monitorClient) {
      this._monitorClient.destroy()
      this._monitorClient = null
    }
    if (this._wcdbStopMonitorPipe) {
      try { this._wcdbStopMonitorPipe() } catch {}
    }
  }
}

module.exports = { WcdbClient, normalizeNameMap }
