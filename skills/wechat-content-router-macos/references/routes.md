# 路由说明

当前内置路由：

- `xhs`：匹配 `xiaohongshu.com` / `xhslink.com`
- `mp`：匹配 `mp.weixin.qq.com`
- `feishu`：匹配 `feishu.cn/wiki` / `feishu.cn/docx`

保留扩展位：

- `quark`
- `baidu`

设计原则：

1. 统一从微信消息里提取 URL
2. 先判断类型，再调用对应 importer
3. 每条消息生成稳定 `message_key`，避免重复导入
4. 所有本地路径都必须走配置，不写死个人目录
5. 当 `storage.mode=local` 时，默认按 **PDF 主产物** 的规则理解输出
6. `xhs` / `mp` / `feishu` 当前都已接入 `browser_render` PDF
