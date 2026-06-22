---
name: ima-sync
slug: ima-sync
displayName: ima 知识库同步工具
version: "2.0.2"
description: >
  ima 知识库与本地文件夹的同步工具——零依赖、浏览器打开即用。
  支持双向差异对比、增量同步上传、可视化 HTML 报告、文件预检过滤。
  三种使用形态：纯前端可视化工具（Chrome/Edge 打开即用，无需安装）、
  Python 命令行脚本（纯 stdlib 零外部依赖）、WorkBuddy 定时自动化。
  21 种文件格式支持，COS 直传 + OpenAPI 双认证，上传更稳定。
  v2.0.1: 修复 create_media 字段名、add_knowledge 缺失参数、media_type 枚举、COS 签名等 7 处 API 对接问题。
category: tools
agent_created: true
---

# ima 知识库同步工具（v2.0.2）

## 概述

ima 知识库与本地文件夹的同步工具——**零依赖、浏览器打开即用**。

核心亮点：
- 🚀 **零依赖**：Python 纯 stdlib，无任何第三方包；前端纯 HTML，无需安装
- 🖥️ **浏览器打开即用**：Chrome/Edge 打开 index.html 就能操作，推荐普通用户
- 🔄 **双向差异对比**：一眼看清 ima 上有什么、本地有什么、哪些不一致
- ⚡ **增量同步**：sync_state.json 追踪状态，第二次运行只传变化的部分
- 🛡️ **文件预检**：21 种扩展名自动校验格式和大小，上传前就知道能不能传
- 🔐 **双认证模式**：OpenAPI（ClientID+APIKey）推荐 + Bearer Token 备选
- ☁️ **COS 直传**：HMAC-SHA1 签名直传腾讯云 COS，比反推接口更稳定

三种使用形态：
- **可视化界面**：纯前端 HTML，浏览器打开即用，零门槛（推荐普通用户）
- **Python 脚本**：命令行运行，纯 stdlib 零外部依赖，适合自动化或定时任务
- **WorkBuddy 自动化**：接入 WorkBuddy 定时任务，每日自动生成差异报告

## 触发条件

当用户提到以下意图时加载此 Skill：
- "同步 ima 知识库"、"对比 ima 和本地文件"
- "生成 ima 同步报告"、"ima 同步检查"
- "设置 ima 自动同步"、"每天检查 ima 知识库更新"
- "一键上传到 ima"、"批量同步 ima"

## 核心概念

| 概念 | 说明 |
|------|------|
| 知识库 ID | ima 中知识库的唯一标识，如 0019ecbe564011f4 |
| OpenAPI 认证 | Client ID + API Key，从 ima.qq.com/agent-interface 获取（推荐） |
| Bearer Token | ima API 鉴权凭证，从浏览器开发者工具获取（备选） |
| 差异状态 | missing（仅 ima）、new（仅本地）、modified（内容不同）、same（一致） |
| 文件预检 | 上传前检查文件类型和大小，自动过滤不支持格式 |
| sync_state.json | 记录已上传文件的大小和修改时间，下次运行只传变化 |
| 本地目录 | 用户指定的本地文件夹，文件名与 ima 标题对应 |

## 文件清单

```
ima-sync/
├── SKILL.md                本文件
├── assets/
│   └── index.html         可视化同步工具（v2.0：双认证+预检+快捷操作）
├── scripts/
│   └── ima_sync_report.py  Python 同步脚本（v2.0：增量+预检+多模式）
│   └── reports/            报告输出目录（保留最近 30 份）
│   └── sync_state.json     增量同步状态文件
└── references/
    └── api_reference.md   ima API 接口参考（含 OpenAPI 和 COS 直传）
```

## 使用方式

### 方式一：可视化工具（推荐普通用户）

将 `assets/index.html` 用 Chrome 或 Edge 打开，按四步操作：
1. 配置认证（推荐 OpenAPI：输入 Client ID 和 API Key）
2. 加载并选择知识库
3. 选择本地同步目录
4. 点击"开始对比"，查看差异并选择操作

新增功能：
- 认证方式切换：OpenAPI（推荐）/ Bearer Token（备选）
- 文件预检提示：不支持的格式和超限文件会自动标记
- 快捷选择：一键选中所有新文件、一键选中所有变更文件
- 一键上传：直接上传所有新文件，无需逐个勾选

### 方式二：Python 脚本（推荐自动化）

```bash
# OpenAPI 认证（推荐）
export IMA_OPENAPI_CLIENTID="你的ClientID"
export IMA_OPENAPI_APIKEY="你的APIKey"

# 预览模式（只看差异，不上传）
python scripts/ima_sync_report.py --local "C:/path" --kb 0019ecbe564011f4 --dry-run

# 增量同步（只上传变化的部分，推荐日常使用）
python scripts/ima_sync_report.py --local "C:/path" --kb 0019ecbe564011f4

# 全量同步（忽略 sync_state.json，首次使用时推荐）
python scripts/ima_sync_report.py --local "C:/path" --kb 0019ecbe564011f4 --full
```

脚本自动：
- 预检过滤不支持的文件格式
- 检查文件大小限制
- 执行上传（增量模式下只传变化的部分）
- 保存 sync_state.json 追踪同步状态
- 输出 HTML 报告到 reports/ 目录

### 方式三：WorkBuddy 自动化

通过 automation_update 创建定时任务，每天自动执行差异检查并展示报告。
推荐使用 --dry-run 模式，只看差异不执行上传。

## 差异对比逻辑（v2.0 增强）

1. 通过 ima MCP 工具或 API 获取知识库文件列表（游标分页）
2. 递归扫描本地目录，过滤不支持的格式
3. 文件预检：校验文件类型映射和大小限制
4. 加载 sync_state.json（增量模式）
5. 按文件名匹配，判断差异状态：
   - **仅在 ima**（missing）：ima 有，本地无，可选下载
   - **仅在本地**（new）：本地有，ima 无，可选上传（标记预检结果）
   - **内容不同**（modified）：与 sync_state 对比，文件大小或修改时间变化
   - **一致**（same）：两端都有且与 sync_state 记录一致
6. 生成 HTML 报告展示结果（含预检警告区域）
7. 执行上传后更新 sync_state.json

## 文件预检规则

| 类型 | 扩展名 | 大小限制 |
|------|--------|----------|
| PDF | .pdf | 200 MB |
| Word | .doc .docx | 200 MB |
| PPT | .ppt .pptx | 200 MB |
| Excel | .xls .xlsx .csv | 10 MB |
| Markdown | .md .markdown | 10 MB |
| TXT | .txt | 10 MB |
| 图片 | .png .jpg .jpeg .webp .gif | 30 MB |
| Xmind | .xmind | 10 MB |
| 音频 | .mp3 .m4a .wav .aac | 200 MB |

不支持的视频格式（.mp4, .avi, .mov 等）自动跳过，需在 ima 桌面端上传。

## 上传机制

严格遵循 ima OpenAPI 三步上传流程（与 API 文档一致）：
1. `create_media` → 传入 `file_name`/`file_size`/`content_type`(MIME)/`knowledge_base_id`/`file_ext`，获取 `media_id` + COS 凭证
2. COS PUT 直传 → HMAC-SHA1 签名（含 `host` header），`bucket_name`/`cos_key` 字段名对齐 API
3. `add_knowledge` → 传入 `media_type`(整数)/`media_id`/`title`/`knowledge_base_id`/`file_info`，注册到知识库

OpenAPI 认证模式仅走 COS 直传流程（无退路接口）。

## 注意事项

- **文件名匹配**：依赖文件名（含扩展名）完全匹配，ima 中的标题需与本地文件名一致
- **OpenAPI 认证**：推荐方式，从 ima.qq.com/agent-interface 获取，更稳定不易过期
- **sync_state.json**：增量同步状态文件，记录已上传文件信息，--full 模式会忽略它
- **浏览器兼容**：可视化工具需要 Chrome 或 Edge 127 以上（File System Access API 支持）
- **预检过滤**：不支持的文件类型和超限文件会自动标记，上传时跳过

## 参考资料

- API 接口详情：`references/api_reference.md`（含 OpenAPI 认证和 COS 直传）
- GitHub 参考：cj0103/ima-sync-skill（增量同步 + COS 直传 + 预检）
- ima 官方文档：https://ima.qq.com
