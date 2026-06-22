# 常见问题（FAQ）

## 上传/同步相关

### 上传成功了，但 ima 知识库还是空的？

这是 ima 后台索引延迟，不是上传失败。文件实际上传成功了，但 ima 搜索索引需要 1-5 分钟刷新。

**验证方法**：等 2 分钟后，在 ima 桌面端/网页端打开知识库，切换到"文件"视图（不要用搜索），就能看到新文件。

**下次同步**：索引延迟期间再次运行同步，diff 会显示"仅在本地"重新上传，不会丢数据。等索引完成后再跑就正常了。

### Bearer Token 过期了怎么办？

Bearer Token 有有效期（通常几小时到几天），过期后 API 返回 401。

**获取新的 Bearer Token**：
1. 浏览器打开 ima.qq.com 并登录
2. F12 打开开发者工具 → Network（网络）标签
3. 在页面进行一次操作（如打开知识库）
4. 找到任意一个 `ima.qq.com` 的请求
5. 在 Request Headers 中找到 `Authorization: Bearer xxx...` 或 `cookie` 字段
6. 复制 token 值

**建议**：优先使用 OpenAPI 认证（Client ID + API Key），有效期更长更稳定。获取方式见 SKILL.md "首次配置"章节。

### 文件名必须和 ima 里的一模一样吗？

是的。同步按**文件名（含扩展名）**进行匹配。本地文件和 ima 上的标题必须完全一致。

**例子**：
- 本地 `工作报告.pdf` → ima 标题 `工作报告.pdf` ✅ 匹配
- 本地 `工作报告.pdf` → ima 标题 `2024工作报告` ❌ 不匹配，会被判为"仅在本地"

**批量对齐**：如果本地文件名和 ima 标题不一致，先手动对齐。可以用脚本批量重命名。

### 同步中断了（网络断了/电脑休眠），sync_state 会乱吗？

不会。上传是**先上传后记录**——只有上传成功后才会更新 sync_state.json。中断后重新运行即可，未完成的上传会重新执行。

**万一 sync_state 错乱了**：删除 `scripts/sync_state.json`，用 `--full` 模式重新全量同步即可恢复。

### COS 直传是什么？失败了怎么办？

COS 直传是 ima 推荐的上传方式：文件直接上传到腾讯云 COS 存储，不走 ima 中转，速度更快更稳定。

v2.0.2+ 版本**仅使用 COS 直传**（OpenAPI 模式），没有退路接口。如果 COS 直传反复失败：

1. 检查网络是否正常（COS 域名可能被防火墙拦截）
2. 确认文件大小在限制内
3. 检查 API 凭证是否有效
4. 等待几分钟重试

### 上传超大文件很慢？

- PDF/Word/PPT 限制 200MB，上传取决于网速
- 超过 100MB 的文件建议在 ima 桌面端直接上传，体验更好
- 音频文件限制 200MB，大文件同样建议在桌面端操作

## 文件格式相关

### 为什么不能上传视频文件？

这是 ima OpenAPI 的限制，不是 ima-sync 的问题。视频文件（.mp4/.avi/.mov 等）的 media_type 不在 OpenAPI 支持范围内。

**替代方案**：视频文件在 ima 桌面端拖拽上传。

### 有哪些文件格式不支持上传？

以下格式 ima OpenAPI 不支持，同步时会自动跳过：

| 格式 | 扩展名 | 替代方案 |
|------|--------|----------|
| 视频 | .mp4 .avi .mov .mkv .wmv .flv .rmvb .3gp .ts | 桌面端上传 |
| 压缩包 | .zip .rar .7z .tar .gz | 暂不支持 |
| 可执行文件 | .exe .dmg .apk | 暂不支持 |
| 其他 | .epub .pages .numbers .key | 暂不支持 |

跳过时会显示在同步报告的"预检警告"区域。

## 认证与配置

### OpenAPI 的 Client ID 和 API Key 在哪获取？

1. 浏览器打开 https://ima.qq.com/agent-interface
2. 登录你的 QQ 账号
3. 页面会直接显示 Client ID 和 API Key
4. 复制到对应位置即可

**注意**：这是敏感凭证，不要分享给他人。

### OpenAPI 和 Bearer Token 用哪个？

| | OpenAPI | Bearer Token |
|---|---|---|
| 获取方式 | ima.qq.com/agent-interface | 浏览器开发者工具 |
| 有效期 | 长期（数月） | 短（几小时到几天） |
| 稳定性 | 高 | 中 |
| 推荐程度 | ⭐⭐⭐ 推荐 | ⭐ 备选 |

**建议**：优先用 OpenAPI。Bearer Token 仅作备选。

## 浏览器兼容性

### 可视化工具需要什么浏览器？

需要支持 File System Access API 的浏览器：

- **Chrome/Edge 127+**（推荐）
- **Opera 113+**
- **不支持**：Firefox、Safari（尚未实现 File System Access API）

### 浏览器打开白屏/报错？

1. 确认浏览器版本 ≥ Chrome 127 或 Edge 127
2. 不要通过 `file://` 协议打开（会被浏览器限制），可以：
   - 用 Live Server 插件
   - `python -m http.server 8080` 然后访问 `http://localhost:8080`
3. 控制台查看具体报错（F12 → Console）

## 其他

### sync_state.json 是什么？

增量同步状态文件。记录每个文件上次同步时的 `size` 和 `mtime`（修改时间）。

- 下次同步时对比这个记录，没变的跳过，变了的重新上传
- 删除它下次就会全量重新同步
- 放在 `.gitignore` 里，不会提交到 Git

### 报告能保留多久？

默认保留最近 30 份报告（在 `scripts/reports/` 目录下）。旧报告会自动清理。

### 可以在多台电脑上共用一个知识库同步吗？

可以，但需要注意：
- 每台电脑的 `sync_state.json` 是独立的
- 如果多台电脑同时上传同名文件，后上传的会覆盖先上传的
- 建议一台电脑做主同步，其他电脑只做 `--dry-run` 预览
