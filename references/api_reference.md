# ima API 参考

本文档记录 ima 知识库相关 API 接口，供 Skill 内部使用。

## 基础信息

| 项目 | 值 |
|------|-----|
| Base URL | `https://ima.qq.com/backend/api/v1` |
| OpenAPI URL | `https://ima.qq.com/openapi/v1` |

## 认证方式

### 1. OpenAPI 认证（推荐）

从 <https://ima.qq.com/agent-interface> 获取 Client ID 和 API Key。

请求头：
```
Authorization: Bearer <api_key>
X-IMA-Client-ID: <client_id>
Content-Type: application/json
```

获取方式：
1. 登录 ima.qq.com
2. 进入"Agent Interface"页面
3. 创建或查看已有的 Client ID / API Key

优点：稳定、不易过期、官方接口

### 2. Bearer Token 认证（备选）

请求头：
```
Authorization: Bearer <token>
Content-Type: application/json
```

获取方式：
1. 打开 [ima.qq.com](https://ima.qq.com) 并登录
2. 按 F12 打开开发者工具 → Network 标签
3. 找任意 API 请求 → 复制 `Authorization: Bearer ` 后面的字符串

缺点：Token 可能定期过期，需手动刷新

## 接口列表

### 1. 获取知识库列表

```
POST /knowledge_base/list
Body: {"limit": 50, "type": "KBT_MINE_KB"}
```

返回：
```json
{
  "results": [{
    "knowledge_base_list": [{
      "id": "0019ecbe564011f4",
      "basic_info": {
        "name": "知识库名称",
        "size": "12345",
        "knowledge_total_size": "10"
      }
    }]
  }]
}
```

### 2. 获取知识库文件列表（游标分页）

```
POST /knowledge/list
Body: {
  "knowledge_base_id": "0019ecbe564011f4",
  "limit": 100,
  "cursor": "",
  "sort_type": "UPDATE_TS_DESC_SORT_TYPE"
}
```

返回：
```json
{
  "knowledge_list": [{
    "media_id": "wechatarticle_xxx",
    "media_type": 6,
    "title": "文件名或文章标题",
    "file_size": "39935",
    "create_time": "1754555336029",
    "media_state": 2
  }],
  "next_cursor": "...",
  "is_end": true
}
```

`media_type` 枚举：1=PDF, 2=网页, 3=Word, 4=PPT, 5=Excel, 6=公众号, 7=Markdown, 8=图片, 9=笔记, 11=TXT, 14=Xmind, 17=音频

### 3. 获取文件内容

```
POST /knowledge/fetch_content
Body: {"media_id": "wechatarticle_xxx"}
```

返回文件文本内容（适合 TXT/Markdown/笔记类）。

### 4. 创建媒体（COS 直传方式）

```
POST /knowledge/create_media
Body: {
  "knowledge_base_id": "...",
  "file_name": "test.pdf",
  "file_size": 12345,
  "media_type": 1
}
```

返回：
```json
{
  "media_id": "...",
  "upload_credential": {
    "bucket": "ima-xxx",
    "region": "ap-guangzhou",
    "object_key": "xxx/test.pdf",
    "tmp_secret_id": "...",
    "tmp_secret_key": "...",
    "session_token": "...",
    "start_time": "1234567890",
    "expired_time": "1234568490"
  }
}
```

### 5. COS 上传（PUT 直传）

```
PUT https://{bucket}.cos.{region}.myqcloud.com/{object_key}
Headers:
  Authorization: q-sign-algorithm=sha1&...（HMAC-SHA1 签名）
  x-cos-security-token: {session_token}
  Content-Type: application/octet-stream
Body: 文件二进制内容
```

签名算法（HMAC-SHA1）：
1. KeyTime = {start_time};{expired_time}
2. SignKey = HMAC-SHA1(SecretKey, KeyTime)
3. HttpString = PUT\n/{object_key}\n\n
4. StringToSign = sha1\n{KeyTime}\nHMAC-SHA1(SignKey, HttpString)
5. Signature = HMAC-SHA1(SignKey, StringToSign)
6. Authorization = q-sign-algorithm=sha1&q-ak={SecretId}&q-sign-time={KeyTime}&q-key-time={KeyTime}&q-header-list=&q-url-param-list=&q-signature={Signature}

### 6. 注册到知识库

```
POST /knowledge/add_knowledge
Body: {"knowledge_base_id": "...", "media_id": "...", "title": "文件名"}
```

### 7. 上传文件（原始方式，备选）

Step1: 获取上传链接
```
POST /knowledge/upload_url
Body: {"knowledge_base_id": "...", "file_name": "test.pdf", "file_size": 12345}
```

Step2: PUT 上传到返回的 `upload_url`

Step3: 通知上传完成
```
POST /knowledge/upload_complete
Body: {"knowledge_base_id": "...", "media_id": "..."}
```

## 文件类型和大小限制

| 类型 | 扩展名 | media_type | 最大大小 |
|------|--------|-----------|----------|
| PDF | .pdf | 1 | 200 MB |
| Word | .doc .docx | 3 | 200 MB |
| PPT | .ppt .pptx | 4 | 200 MB |
| Excel | .xls .xlsx .csv | 5 | 10 MB |
| Markdown | .md .markdown | 7 | 10 MB |
| TXT | .txt | 11 | 10 MB |
| 图片 | .png .jpg .jpeg .webp .gif | 8 | 30 MB |
| Xmind | .xmind | 14 | 10 MB |
| 音频 | .mp3 .m4a .wav .aac | 17 | 200 MB |

不支持：视频文件（.mp4, .avi, .mov 等），需在 ima 桌面端上传

## MCP 工具（优先使用）

如果 WorkBuddy 已连接 `ima-mcp`，优先使用以下 MCP 工具，无需手动处理 Token：

| MCP 工具 | 功能 |
|-----------|------|
| `mcp__ima-mcp__get_knowledge_base_list` | 获取知识库列表 |
| `mcp__ima-mcp__get_knowledge_list` | 获取文件列表 |
| `mcp__ima-mcp__search_knowledge` | 搜索知识库内容 |
| `mcp__ima-mcp__fetch_media_content` | 获取文件内容 |
