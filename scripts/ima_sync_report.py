"""
ima 知识库 <-> 本地目录 同步工具（v2.0）

改进点（借鉴 cj0103/ima-sync-skill）：
  1. 双认证支持：OpenAPI（ClientID + APIKey，推荐） + Bearer Token（备选）
  2. 文件预检：19 种类型映射 + 大小限制校验
  3. 增量同步：sync_state.json 记录已上传文件状态
  4. CLI 模式：--dry-run 预览 / --full 全量 / 默认增量

运行方式：
  # OpenAPI 认证（推荐）
  export IMA_OPENAPI_CLIENTID="xxx"
  export IMA_OPENAPI_APIKEY="xxx"
  python ima_sync_report.py --local "C:/path" --kb 0019ecbe564011f4

  # Bearer Token 认证（备选）
  export IMA_TOKEN="xxx"
  python ima_sync_report.py --local "C:/path" --kb 0019ecbe564011f4

  # 预览模式（不执行上传）
  python ima_sync_report.py --local "C:/path" --kb xxx --dry-run

  # 全量同步（忽略 sync_state.json）
  python ima_sync_report.py --local "C:/path" --kb xxx --full

依赖：无需第三方库，仅用标准库
"""

import sys
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import hashlib
import hmac
import base64
import argparse
import datetime
import pathlib
import html as html_mod
import time

# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────
DEFAULT_KB_ID   = "0019ecbe564011f4"
DEFAULT_LOCAL   = r"C:\Users\timed\Desktop\ima-sync"
REPORT_DIR      = pathlib.Path(__file__).parent / "reports"
SYNC_STATE_FILE = pathlib.Path(__file__).parent / "sync_state.json"

IMA_BASE        = "https://ima.qq.com/openapi/wiki/v1"
IMA_OPENAPI     = "https://ima.qq.com/openapi/v1"

# ──────────────────────────────────────────────
# 文件预检配置（借鉴 cj0103/ima-sync-skill）
# ──────────────────────────────────────────────

# 文件类型映射：扩展名 -> { media_type, content_type, label, max_size_mb }
# media_type: ima API 整数枚举; content_type: HTTP MIME (create_media 用)
PREFLIGHT_MAP = {
    ".pdf":      {"media_type": 1,  "content_type": "application/pdf",                                                                       "label": "PDF",      "max_size_mb": 200},
    ".doc":      {"media_type": 3,  "content_type": "application/msword",                                                                   "label": "Word",     "max_size_mb": 200},
    ".docx":     {"media_type": 3,  "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",              "label": "Word",     "max_size_mb": 200},
    ".ppt":      {"media_type": 4,  "content_type": "application/vnd.ms-powerpoint",                                                        "label": "PPT",      "max_size_mb": 200},
    ".pptx":     {"media_type": 4,  "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",             "label": "PPT",      "max_size_mb": 200},
    ".xls":      {"media_type": 5,  "content_type": "application/vnd.ms-excel",                                                             "label": "Excel",    "max_size_mb": 10},
    ".xlsx":     {"media_type": 5,  "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",                     "label": "Excel",    "max_size_mb": 10},
    ".csv":      {"media_type": 5,  "content_type": "text/csv",                                                                             "label": "CSV",      "max_size_mb": 10},
    ".md":       {"media_type": 7,  "content_type": "text/markdown",                                                                        "label": "Markdown", "max_size_mb": 10},
    ".markdown": {"media_type": 7,  "content_type": "text/markdown",                                                                        "label": "Markdown", "max_size_mb": 10},
    ".txt":      {"media_type": 13, "content_type": "text/plain",                                                                           "label": "TXT",      "max_size_mb": 10},
    ".png":      {"media_type": 9,  "content_type": "image/png",                                                                            "label": "PNG",      "max_size_mb": 30},
    ".jpg":      {"media_type": 9,  "content_type": "image/jpeg",                                                                           "label": "JPG",      "max_size_mb": 30},
    ".jpeg":     {"media_type": 9,  "content_type": "image/jpeg",                                                                           "label": "JPEG",     "max_size_mb": 30},
    ".webp":     {"media_type": 9,  "content_type": "image/webp",                                                                           "label": "WebP",     "max_size_mb": 30},
    ".gif":     {"media_type": 9,  "content_type": "image/gif",                                                                            "label": "GIF",      "max_size_mb": 30},
    ".xmind":    {"media_type": 14, "content_type": "application/x-xmind",                                                                  "label": "Xmind",    "max_size_mb": 10},
    ".mp3":      {"media_type": 15, "content_type": "audio/mpeg",                                                                           "label": "MP3",      "max_size_mb": 200},
    ".m4a":      {"media_type": 15, "content_type": "audio/x-m4a",                                                                          "label": "M4A",      "max_size_mb": 200},
    ".wav":      {"media_type": 15, "content_type": "audio/wav",                                                                            "label": "WAV",      "max_size_mb": 200},
    ".aac":      {"media_type": 15, "content_type": "audio/aac",                                                                            "label": "AAC",      "max_size_mb": 200},
}

SUPPORTED_EXTS = set(PREFLIGHT_MAP.keys())

# 视频不支持
UNSUPPORTED_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".rmvb", ".3gp", ".ts"}

# ima API 中的 media_type -> label（与 API 文档一致）
MEDIA_TYPE_MAP = {
    1: "PDF", 2: "网页", 3: "Word", 4: "PPT", 5: "Excel",
    6: "公众号", 7: "Markdown", 9: "图片", 11: "笔记",
    12: "AI会话", 13: "TXT", 14: "Xmind", 15: "录音", 16: "视频",
}


# ──────────────────────────────────────────────
# 认证（双模式）
# ──────────────────────────────────────────────

class AuthInfo:
    """统一认证信息，支持 OpenAPI 和 Bearer Token 两种方式"""
    def __init__(self, mode: str = "", client_id: str = "", api_key: str = "", token: str = ""):
        self.mode = mode  # "openapi" or "bearer"
        self.client_id = client_id
        self.api_key = api_key
        self.token = token

    def resolve(self) -> str:
        """自动从环境变量读取认证信息，返回认证模式"""
        # 优先使用 OpenAPI
        cid = self.client_id or os.environ.get("IMA_OPENAPI_CLIENTID", "")
        akey = self.api_key or os.environ.get("IMA_OPENAPI_APIKEY", "")
        if cid and akey:
            self.mode = "openapi"
            self.client_id = cid
            self.api_key = akey
            return self.mode

        # 备选：Bearer Token
        tok = self.token or os.environ.get("IMA_TOKEN", "")
        if tok:
            self.mode = "bearer"
            self.token = tok
            return self.mode

        raise ValueError(
            "缺少认证信息。推荐方式：设置环境变量 IMA_OPENAPI_CLIENTID 和 IMA_OPENAPI_APIKEY\n"
            "（从 ima.qq.com/agent-interface 获取）。备选：设置 IMA_TOKEN（Bearer Token）。"
        )

    def headers(self) -> dict:
        """返回请求头"""
        if self.mode == "openapi":
            return {
                "ima-openapi-clientid": self.client_id,
                "ima-openapi-apikey": self.api_key,
                "Content-Type": "application/json",
                "User-Agent": "WorkBuddy-ima-sync/2.0",
            }
        else:
            return {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "WorkBuddy-ima-sync/2.0",
            }


# ──────────────────────────────────────────────
# ima API 请求
# ──────────────────────────────────────────────

def ima_post(path: str, payload: dict, auth: AuthInfo) -> dict:
    """调用 ima API，自动解包 {code, msg, data} 包装，失败时抛异常"""
    url = IMA_BASE + path
    data = json.dumps(payload).encode("utf-8")
    headers = auth.headers()
    req = urllib.request.Request(
        url, data=data, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    code = body.get("code", -1)
    if code != 0:
        raise ValueError(f"ima API 错误 ({path}): [{code}] {body.get('msg', '未知错误')}")
    return body.get("data", body)


def load_ima_files(kb_id: str, auth: AuthInfo) -> list[dict]:
    """分页拉取知识库所有文件（游标分页）"""
    files = []
    cursor = ""
    while True:
        data = ima_post("/get_knowledge_list", {
            "knowledge_base_id": kb_id,
            "limit": 50,
            "cursor": cursor,
        }, auth)
        batch = data.get("knowledge_list", [])
        files.extend(batch)
        cursor = data.get("next_cursor", "")
        if data.get("is_end") or not cursor:
            break
    return files


def load_kb_info(kb_id: str, auth: AuthInfo) -> dict:
    """获取知识库基本信息"""
    data = ima_post("/get_knowledge_base", {
        "ids": [kb_id],
    }, auth)
    infos = data.get("infos", {})
    kb = infos.get(kb_id, {})
    return {"id": kb_id, "basic_info": {"name": kb.get("name", kb_id)}}


# ──────────────────────────────────────────────
# 文件上传（借鉴 cj0103 三步上传 + COS 直传）
# ──────────────────────────────────────────────

def upload_file_to_ima(file_path: str, kb_id: str, auth: AuthInfo) -> dict:
    """
    上传本地文件到 ima 知识库。
    流程（与 API 文档一致）：
      1) check_repeated_names（可选，跳过不阻塞）
      2) create_media → 获取 media_id + COS 凭证
      3) COS PUT 直传
      4) add_knowledge → 注册到知识库
    """
    p = pathlib.Path(file_path)
    ext = p.suffix.lower()
    preflight = PREFLIGHT_MAP.get(ext)

    # 预检
    if not preflight:
        raise ValueError(f"不支持的文件类型：{ext}")
    file_stat = p.stat()
    file_size = file_stat.st_size
    if file_size > preflight["max_size_mb"] * 1024 * 1024:
        raise ValueError(f"文件超过大小限制：{p.name}（{file_size/1024/1024:.1f} MB > {preflight['max_size_mb']} MB）")

    file_name = p.name
    file_ext = ext.lstrip(".")  # 无点号，如 "pdf"

    # Step 1: create_media — 获取 media_id + COS 上传凭证
    # API 字段：file_name, file_size, content_type, knowledge_base_id, file_ext
    create_payload = {
        "file_name": file_name,
        "file_size": file_size,
        "content_type": preflight["content_type"],
        "knowledge_base_id": kb_id,
        "file_ext": file_ext,
    }

    create_resp = ima_post("/create_media", create_payload, auth)
    media_id = create_resp.get("media_id", "")
    cos_cred = create_resp.get("cos_credential", {})

    if not media_id or not cos_cred:
        raise ValueError(f"create_media 返回缺少必要字段：media_id={media_id}, cos_credential={bool(cos_cred)}")

    # Step 2: COS PUT 直传
    # API 返回字段：token, secret_id, secret_key, start_time, expired_time,
    #               appid, bucket_name, region, custom_domain, cos_key
    bucket = cos_cred.get("bucket_name", "")
    region = cos_cred.get("region", "")
    cos_key = cos_cred.get("cos_key", "")
    tmp_secret_id = cos_cred.get("secret_id", "")
    tmp_secret_key = cos_cred.get("secret_key", "")
    session_token = cos_cred.get("token", "")
    start_time = str(cos_cred.get("start_time", ""))
    expired_time = str(cos_cred.get("expired_time", ""))

    if not all([bucket, region, cos_key, tmp_secret_id, tmp_secret_key]):
        raise ValueError(f"COS 凭证不完整：bucket={bucket}, region={region}, cos_key={cos_key}")

    cos_url = f"https://{bucket}.cos.{region}.myqcloud.com/{cos_key}"

    # HMAC-SHA1 签名
    key_time = f"{start_time};{expired_time}"
    sign_key = hmac.new(tmp_secret_key.encode(), key_time.encode(), hashlib.sha1).hexdigest()
    http_string = f"put\n/{cos_key}\n\nhost={bucket}.cos.{region}.myqcloud.com\n"
    sha1_http = hashlib.sha1(http_string.encode()).hexdigest()
    string_to_sign = f"sha1\n{key_time}\n{sha1_http}\n"
    signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()

    authorization = (
        f"q-sign-algorithm=sha1"
        f"&q-ak={tmp_secret_id}"
        f"&q-sign-time={key_time}"
        f"&q-key-time={key_time}"
        f"&q-header-list=host"
        f"&q-url-param-list="
        f"&q-signature={signature}"
    )

    upload_headers = {
        "Authorization": authorization,
        "x-cos-security-token": session_token,
        "Host": f"{bucket}.cos.{region}.myqcloud.com",
        "Content-Type": "application/octet-stream",
        "User-Agent": "WorkBuddy-ima-sync/2.0",
    }

    with open(file_path, "rb") as f:
        file_data = f.read()

    upload_req = urllib.request.Request(cos_url, data=file_data, headers=upload_headers, method="PUT")
    with urllib.request.urlopen(upload_req, timeout=120) as upload_resp:
        if upload_resp.status >= 300:
            raise ValueError(f"COS 上传失败：HTTP {upload_resp.status}")

    # Step 3: add_knowledge — 注册到知识库
    # API 字段：media_type, media_id, title, knowledge_base_id, file_info
    add_payload = {
        "media_type": preflight["media_type"],
        "media_id": media_id,
        "title": file_name,
        "knowledge_base_id": kb_id,
        "file_info": {
            "cos_key": cos_key,
            "file_size": file_size,
            "last_modify_time": int(file_stat.st_mtime),
            "password": "",
            "file_name": file_name,
        },
    }
    ima_post("/add_knowledge", add_payload, auth)

    return {"media_id": media_id, "title": file_name, "status": "uploaded"}


# ──────────────────────────────────────────────
# 本地目录扫描
# ──────────────────────────────────────────────

def scan_local(root: str) -> dict[str, dict]:
    """递归扫描本地目录，返回 {相对路径: 文件信息}"""
    result = {}
    root_path = pathlib.Path(root)
    if not root_path.exists():
        return result
    for p in root_path.rglob("*"):
        if p.is_file():
            ext = p.suffix.lower()
            # 跳过不支持的格式
            if ext in UNSUPPORTED_EXTS:
                continue
            # 跳过不在预检映射中的格式（非核心文件类型也忽略）
            if ext not in SUPPORTED_EXTS:
                continue
            rel = str(p.relative_to(root_path)).replace("\\", "/")
            stat = p.stat()
            result[rel] = {
                "path": str(p),
                "size": stat.st_size,
                "mtime": int(stat.st_mtime * 1000),
                "ext": ext,
                "preflight": PREFLIGHT_MAP.get(ext),
            }
    return result


def scan_all_local(root: str) -> dict[str, dict]:
    """扫描所有文件（包括不支持的），用于报告中的警告提示"""
    result = {}
    root_path = pathlib.Path(root)
    if not root_path.exists():
        return result
    for p in root_path.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root_path)).replace("\\", "/")
            stat = p.stat()
            result[rel] = {
                "path": str(p),
                "size": stat.st_size,
                "mtime": int(stat.st_mtime * 1000),
                "ext": p.suffix.lower(),
                "supported": p.suffix.lower() in SUPPORTED_EXTS,
                "oversized": False,
            }
            # 检查大小是否超限
            pf = PREFLIGHT_MAP.get(p.suffix.lower())
            if pf and stat.st_size > pf["max_size_mb"] * 1024 * 1024:
                result[rel]["oversized"] = True
    return result


# ──────────────────────────────────────────────
# 增量同步状态（借鉴 cj0103 sync_state.json）
# ──────────────────────────────────────────────

def load_sync_state() -> dict:
    """加载上次同步状态"""
    if SYNC_STATE_FILE.exists():
        try:
            return json.loads(SYNC_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_sync_state(state: dict):
    """保存同步状态"""
    SYNC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ──────────────────────────────────────────────
# 差异对比（增量模式增强）
# ──────────────────────────────────────────────

def _extract_filename(title: str) -> str:
    """从 ima title 提取纯文件名（去掉可能的路径前缀）"""
    if not title:
        return ""
    # title 可能是 "foo/bar.pdf" 或 "bar.pdf"，统一取最后一段
    return title.replace("\\", "/").rsplit("/", 1)[-1]


def compute_diff(ima_files: list[dict], local_files: dict, sync_state: dict, full_mode: bool = False) -> list[dict]:
    """
    对比 ima 文件列表与本地文件：
    - 通过文件名（纯 basename）做双向匹配
    - 用 sync_state 记录的行踪（size + mtime）判断"已同步一致"
    - 不用时间戳做差异判断（ima create_time 和本地 mtime 无直接可比性）
    """
    # ima 按文件名索引（title 去路径前缀）
    ima_by_name = {}
    for f in ima_files:
        name = _extract_filename(f.get("title", ""))
        if not name:
            name = f.get("media_id", "")
        ima_by_name[name] = f

    # 本地文件名集合
    local_names = set(local_files.keys())

    items = []

    # ima 侧遍历
    for name, f in ima_by_name.items():
        local = local_files.get(name)
        ima_ts = int(f.get("create_time") or 0)
        ima_size = int(f.get("file_size") or 0)

        if not local:
            items.append({
                "name": name,
                "status": "missing",
                "ima_ts": ima_ts,
                "ima_size": ima_size,
                "local_size": None,
                "local_mtime": None,
                "media_type": MEDIA_TYPE_MAP.get(f.get("media_type"), "文件"),
                "ima_file": f,
                "local_path": None,
            })
        else:
            # 判断是否已同步：sync_state 记录了上次上传时的 size + mtime
            state_entry = sync_state.get(name, {}) if not full_mode else {}
            local_mtime = local["mtime"]
            local_size = local["size"]

            if state_entry.get("size") == local_size and state_entry.get("mtime") == local_mtime:
                status = "same"
            else:
                # 本地文件与上次同步时不同（或没有记录）→ 需要重新上传
                status = "modified"

            items.append({
                "name": name,
                "status": status,
                "ima_ts": ima_ts,
                "ima_size": ima_size,
                "local_size": local_size,
                "local_mtime": local_mtime,
                "media_type": MEDIA_TYPE_MAP.get(f.get("media_type"), "文件"),
                "ima_file": f,
                "local_path": local.get("path"),
            })

    # 本地独有文件
    for name, local in local_files.items():
        if name not in ima_by_name:
            pf = local.get("preflight")
            preflight_ok = pf is not None
            oversized = pf and local["size"] > pf["max_size_mb"] * 1024 * 1024
            ext = pathlib.Path(name).suffix.lstrip(".").upper() or "文件"
            items.append({
                "name": name,
                "status": "new",
                "ima_ts": None,
                "ima_size": None,
                "local_size": local["size"],
                "local_mtime": local["mtime"],
                "media_type": pf["label"] if pf else ext,
                "ima_file": None,
                "local_path": local.get("path"),
                "preflight_ok": preflight_ok,
                "oversized": oversized,
            })

    order = {"missing": 0, "new": 1, "modified": 2, "same": 3}
    items.sort(key=lambda x: (order[x["status"]], x["name"]))
    return items


# ──────────────────────────────────────────────
# HTML 报告生成（增加预检警告区域）
# ──────────────────────────────────────────────

def fmt_size(n):
    if n is None or n == 0: return "-"
    if n < 1024: return f"{n} B"
    if n < 1024**2: return f"{n/1024:.1f} KB"
    return f"{n/1024**2:.1f} MB"

def fmt_ts(ms):
    if ms is None or ms == 0: return "-"
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")

STATUS_INFO = {
    "missing":  ("仅在 ima",  "#854F0B", "#FAEEDA"),
    "new":      ("仅在本地",  "#0F6E56", "#E1F5EE"),
    "modified": ("内容不同",  "#185FA5", "#E6F1FB"),
    "same":     ("一致",      "#5F5E5A", "#F1EFE8"),
}


def generate_html_report(
    items: list[dict],
    kb_name: str,
    kb_id: str,
    local_dir: str,
    run_time: datetime.datetime,
    auth_mode: str = "",
    warnings: list[str] = [],
    uploaded: list[dict] = [],
    dry_run: bool = False,
) -> str:
    # 用纯拼接构建 HTML，避免 PEP 701 f-string 解析问题
    counts = {}
    for s in ["missing", "new", "modified", "same"]:
        counts[s] = sum(1 for i in items if i["status"] == s)
    total = len(items)

    run_time_str = run_time.strftime("%Y-%m-%d %H:%M")
    run_time_zh = run_time.strftime("%Y年%m月%d日 %H:%M")
    kb_name_esc = html_mod.escape(kb_name)
    local_dir_esc = html_mod.escape(local_dir)
    auth_label = "OpenAPI (ClientID + APIKey)" if auth_mode == "openapi" else "Bearer Token"
    mode_label = "预览模式（dry-run）" if dry_run else "同步模式"

    # 预检警告
    warn_html = ""
    if warnings:
        warn_items = "\n".join(
            '<li style="margin-bottom:4px">' + html_mod.escape(w) + '</li>' for w in warnings
        )
        warn_html = (
            '<div class="card" style="border-left:3px solid #FAC775">'
            '<div class="card-title" style="color:#854F0B">预检警告</div>'
            '<ul style="font-size:12px;color:#854F0B;margin:0;padding-left:16px;line-height:1.6">'
            + warn_items + '</ul></div>'
        )

    # 上传结果
    upload_html = ""
    if uploaded:
        ok_count = sum(1 for u in uploaded if u.get("status") == "uploaded")
        fail_count = len(uploaded) - ok_count
        result_color = "#0F6E56" if fail_count == 0 else "#185FA5"
        upload_items = "".join(
            "<div>" + html_mod.escape(u["title"]) + " → " + html_mod.escape(str(u["status"])) + "</div>"
            for u in uploaded
        )
        upload_html = (
            '<div class="card" style="border-left:3px solid ' + result_color + '">'
            '<div class="card-title" style="color:' + result_color + '">'
            '同步结果（成功 ' + str(ok_count) + ' / 失败 ' + str(fail_count) + '）</div>'
            '<div style="font-size:12px;color:#5F5E5A;line-height:1.6">'
            + upload_items + '</div></div>'
        )

    # 行内容
    rows_html = []
    for item in items:
        st_label, st_color, st_bg = STATUS_INFO[item["status"]]

        # 预检标记
        extra_tag = ""
        if item["status"] == "new":
            if not item.get("preflight_ok", True):
                extra_tag = '<span style="display:inline-block;padding:2px 6px;border-radius:20px;font-size:10px;background:#FCEBEB;color:#A32D2D;margin-left:4px">不支持</span>'
            elif item.get("oversized", False):
                pf = item.get("preflight") or PREFLIGHT_MAP.get(pathlib.Path(item["name"]).suffix.lower())
                limit = pf["max_size_mb"] if pf else "?"
                extra_tag = '<span style="display:inline-block;padding:2px 6px;border-radius:20px;font-size:10px;background:#FAEEDA;color:#854F0B;margin-left:4px">超限(' + str(limit) + 'MB)</span>'

        tag = (
            '<span style="display:inline-block;padding:2px 8px;border-radius:20px;'
            'font-size:11px;font-weight:500;background:' + st_bg + ';color:' + st_color
            + '">' + st_label + '</span>' + extra_tag
        )
        row = (
            '<tr>'
            '<td style="font-weight:500;color:#2C2C2A;padding:8px 10px">' + html_mod.escape(item["name"]) + '</td>'
            '<td style="color:#888780;padding:8px 10px">' + html_mod.escape(item["media_type"]) + '</td>'
            '<td style="color:#888780;padding:8px 10px">' + fmt_size(item["ima_size"]) + '</td>'
            '<td style="color:#888780;padding:8px 10px">' + fmt_ts(item["ima_ts"]) + '</td>'
            '<td style="color:#888780;padding:8px 10px">' + fmt_size(item["local_size"]) + '</td>'
            '<td style="color:#888780;padding:8px 10px">' + fmt_ts(item["local_mtime"]) + '</td>'
            '<td style="padding:8px 10px">' + tag + '</td>'
            '</tr>'
        )
        rows_html.append(row)

    rows_str = "\n".join(rows_html)

    # 概况标签
    def chip(label, count, color, bg):
        if count == 0:
            return ""
        return (
            '<span style="display:inline-block;padding:3px 10px;border-radius:20px;'
            'font-size:12px;font-weight:500;background:' + bg + ';color:' + color + ';margin-right:6px">'
            + label + ' ' + str(count) + '</span>'
        )

    chips = (
        chip("仅在 ima",  counts["missing"],  "#854F0B", "#FAEEDA") +
        chip("仅在本地",  counts["new"],      "#0F6E56", "#E1F5EE") +
        chip("内容不同",  counts["modified"], "#185FA5", "#E6F1FB") +
        chip("一致",      counts["same"],     "#5F5E5A", "#F1EFE8")
    )
    chips_or_no = chips if chips else '<span style="color:#888780">无差异</span>'

    # 判断是否有差异
    has_diff = total > 0 and (counts["missing"] + counts["new"] + counts["modified"]) > 0

    if has_diff:
        table_html = (
            "<table><thead><tr>"
            "<th>文件名</th><th>类型</th>"
            "<th>ima 大小</th><th>ima 时间</th>"
            "<th>本地大小</th><th>本地时间</th>"
            "<th>状态</th>"
            "</tr></thead><tbody>" + rows_str + "</tbody></table>"
        )
    else:
        table_html = "<div class='empty'>本地与 ima 完全一致，无需操作 ✓</div>"

    # CSS 模板
    css = (
        "<style>\n"
        "  body { font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; font-size:13px;\n"
        "          color:#2C2C2A; background:#F8F7F4; margin:0; padding:2rem; }\n"
        "  .wrap { max-width:1000px; margin:0 auto; }\n"
        "  .header { display:flex; align-items:center; gap:12px; margin-bottom:1.5rem; }\n"
        "  .logo { width:36px; height:36px; background:#534AB7; border-radius:10px;\n"
        "           display:flex; align-items:center; justify-content:center;\n"
        "           color:#fff; font-size:18px; font-weight:500; flex-shrink:0; }\n"
        "  h1 { font-size:18px; font-weight:500; margin:0; }\n"
        "  .subtitle { font-size:12px; color:#888780; margin-top:2px; }\n"
        "  .card { background:#fff; border-radius:12px; border:0.5px solid rgba(0,0,0,0.12);\n"
        "           padding:1.25rem; margin-bottom:1rem; }\n"
        "  .card-title { font-size:13px; font-weight:500; color:#444441; margin-bottom:8px; }\n"
        "  .metrics { display:flex; gap:12px; margin-bottom:1rem; flex-wrap:wrap; }\n"
        "  .metric { background:#F8F7F4; border-radius:8px; padding:.75rem 1rem; min-width:100px; }\n"
        "  .metric-label { font-size:11px; color:#888780; margin-bottom:4px; }\n"
        "  .metric-value { font-size:22px; font-weight:500; color:#2C2C2A; }\n"
        "  table { width:100%; border-collapse:collapse; font-size:12px; }\n"
        "  th { text-align:left; padding:6px 10px; font-weight:500; color:#888780;\n"
        "        border-bottom:0.5px solid rgba(0,0,0,0.1); font-size:11px; }\n"
        "  tr:hover td { background:#F8F7F4; }\n"
        "  tr td { border-bottom:0.5px solid rgba(0,0,0,0.06); }\n"
        "  .info { display:flex; gap:2rem; font-size:12px; color:#888780; flex-wrap:wrap; }\n"
        "  .info strong { color:#444441; }\n"
        "  .empty { text-align:center; padding:3rem; color:#888780; }\n"
        "</style>"
    )

    # 组装最终 HTML（纯拼接，零 f-string）
    html = "\n".join([
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="UTF-8">',
        "<title>ima 同步报告 " + run_time_str + "</title>",
        css,
        "</head>",
        "<body>",
        '<div class="wrap">',
        '  <div class="header">',
        '    <div class="logo">i</div>',
        "    <div>",
        "      <h1>ima 知识库同步报告</h1>",
        '      <div class="subtitle">生成时间：' + run_time_zh
        + ' &nbsp;·&nbsp; 共 ' + str(total) + ' 个文件'
        + ' &nbsp;·&nbsp; 认证：' + auth_label
        + ' &nbsp;·&nbsp; 模式：' + mode_label + '</div>',
        "    </div>",
        "  </div>",
        warn_html,
        upload_html,
        '  <div class="card">',
        '    <div class="info">',
        '      <div>知识库 <strong>' + kb_name_esc + '</strong>（' + kb_id + '）</div>',
        '      <div>本地目录 <strong>' + local_dir_esc + '</strong></div>',
        "    </div>",
        '    <div style="margin-top:1rem">' + chips_or_no + '</div>',
        "  </div>",
        '  <div class="card">',
        '    <div class="metrics">',
        '      <div class="metric"><div class="metric-label">仅在 ima</div>'
        + '<div class="metric-value" style="color:#854F0B">' + str(counts["missing"]) + '</div></div>',
        '      <div class="metric"><div class="metric-label">仅在本地</div>'
        + '<div class="metric-value" style="color:#0F6E56">' + str(counts["new"]) + '</div></div>',
        '      <div class="metric"><div class="metric-label">内容不同</div>'
        + '<div class="metric-value" style="color:#185FA5">' + str(counts["modified"]) + '</div></div>',
        '      <div class="metric"><div class="metric-label">已同步一致</div>'
        + '<div class="metric-value" style="color:#5F5E5A">' + str(counts["same"]) + '</div></div>',
        "    </div>",
        table_html,
        "  </div>",
        "</div>",
        "</body>",
        "</html>",
    ])
    return html


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def run_sync_check(
    local_dir: str = DEFAULT_LOCAL,
    kb_id: str = DEFAULT_KB_ID,
    auth: AuthInfo = None,
    output_dir: str = "",
    dry_run: bool = False,
    full_mode: bool = False,
) -> str:
    """
    执行一次同步检查+上传，返回 HTML 报告路径。
    dry_run=True 时只生成报告，不执行上传。
    full_mode=True 时忽略 sync_state.json，全量对比。
    """
    if auth is None:
        auth = AuthInfo()
    auth_mode = auth.resolve()

    run_time = datetime.datetime.now()
    print(f"[{run_time.strftime('%H:%M:%S')}] 开始同步检查...")
    print(f"  - 认证方式：{auth_mode}")

    # 1. 加载 ima 知识库
    print(f"  - 获取知识库信息（{kb_id}）...")
    kb_info = load_kb_info(kb_id, auth)
    kb_name = kb_info.get("basic_info", {}).get("name", kb_id)
    print(f"  - 知识库：{kb_name}")

    print("  - 加载 ima 文件列表（游标分页）...")
    ima_files = load_ima_files(kb_id, auth)
    print(f"  - ima 共 {len(ima_files)} 个文件")

    # 2. 扫描本地目录
    local_root = pathlib.Path(local_dir)
    local_root.mkdir(parents=True, exist_ok=True)
    local_files = scan_local(local_dir)
    all_local = scan_all_local(local_dir)
    print(f"  - 本地共 {len(local_files)} 个可同步文件（{local_dir}）")

    # 3. 生成预检警告
    warnings = []
    unsupported = [n for n, f in all_local.items() if not f["supported"]]
    oversized = [n for n, f in all_local.items() if f.get("oversized")]
    if unsupported:
        warnings.append(f"发现 {len(unsupported)} 个不支持格式的文件（如视频），已自动跳过")
    if oversized:
        warnings.append(f"发现 {len(oversized)} 个超过大小限制的文件，上传时会失败")

    # 4. 加载同步状态 + 差异对比
    sync_state = {} if full_mode else load_sync_state()
    items = compute_diff(ima_files, local_files, sync_state, full_mode)
    counts = {s: sum(1 for i in items if i["status"] == s)
              for s in ["missing", "new", "modified", "same"]}
    print(f"  - 仅在 ima: {counts['missing']}  仅在本地: {counts['new']}  "
          f"不一致: {counts['modified']}  一致: {counts['same']}")

    # 5. 执行上传（非 dry-run 模式）
    uploaded = []
    if not dry_run:
        to_upload = [i for i in items if i["status"] in ("new", "modified")
                     and i.get("local_path") and i.get("preflight_ok", True)
                     and not i.get("oversized", False)]
        if to_upload:
            print(f"  - 准备上传 {len(to_upload)} 个文件...")
            for item in to_upload:
                try:
                    result = upload_file_to_ima(item["local_path"], kb_id, auth)
                    uploaded.append(result)
                    print(f"    ✓ {item['name']}")
                    # 更新 sync_state
                    sync_state[item["name"]] = {
                        "size": item["local_size"],
                        "mtime": item["local_mtime"],
                        "uploaded_at": int(time.time() * 1000),
                    }
                except Exception as e:
                    uploaded.append({"title": item["name"], "status": f"失败: {str(e)[:100]}"})
                    print(f"    ✗ {item['name']}: {e}")

            # 保存 sync_state
            save_sync_state(sync_state)
        else:
            print("  - 无需上传的文件")

    # 6. 生成报告
    out_dir = pathlib.Path(output_dir) if output_dir else REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    report_name = f"ima-sync-{run_time.strftime('%Y%m%d-%H%M%S')}.html"
    report_path = out_dir / report_name

    html_content = generate_html_report(
        items, kb_name, kb_id, local_dir, run_time,
        auth_mode=auth_mode, warnings=warnings,
        uploaded=uploaded, dry_run=dry_run,
    )
    report_path.write_text(html_content, encoding="utf-8")
    print(f"  - 报告已生成：{report_path}")

    # 7. 保留最近 30 份报告
    old_reports = sorted(out_dir.glob("ima-sync-*.html"))
    if len(old_reports) > 30:
        for old in old_reports[:-30]:
            old.unlink(missing_ok=True)

    return str(report_path)


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ima 知识库本地同步工具 v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 预览模式（只看差异，不上传）
  python ima_sync_report.py --local "C:/path" --kb xxx --dry-run

  # 增量同步（只上传变化的部分）
  python ima_sync_report.py --local "C:/path" --kb xxx

  # 全量同步（忽略历史状态，重新对比所有文件）
  python ima_sync_report.py --local "C:/path" --kb xxx --full

认证方式（优先级从高到低）：
  1. OpenAPI: 设置 IMA_OPENAPI_CLIENTID 和 IMA_OPENAPI_APIKEY 环境变量（推荐）
  2. Bearer Token: 设置 IMA_TOKEN 环境变量（备选）
  3. 命令行传入: --client-id / --api-key / --token 参数
        """,
    )
    parser.add_argument("--local",      default=DEFAULT_LOCAL,  help="本地目录路径")
    parser.add_argument("--kb",         default=DEFAULT_KB_ID,  help="ima 知识库 ID")
    parser.add_argument("--token",      default="",             help="ima Bearer Token（备选认证）")
    parser.add_argument("--client-id",  default="",             help="ima OpenAPI Client ID（推荐认证）")
    parser.add_argument("--api-key",    default="",             help="ima OpenAPI API Key（推荐认证）")
    parser.add_argument("--output",     default="",             help="报告输出目录（默认 ./reports/）")
    parser.add_argument("--dry-run",    action="store_true",    help="预览模式：只生成报告，不执行上传")
    parser.add_argument("--full",       action="store_true",    help="全量模式：忽略 sync_state.json，重新对比所有文件")

    args = parser.parse_args()

    auth = AuthInfo(
        client_id=args.client_id,
        api_key=args.api_key,
        token=args.token,
    )

    try:
        path = run_sync_check(
            local_dir=args.local,
            kb_id=args.kb,
            auth=auth,
            output_dir=args.output,
            dry_run=args.dry_run,
            full_mode=args.full,
        )
        print(f"\n完成！报告路径：{path}")
    except ValueError as e:
        print(f"错误：{e}")
        sys.exit(1)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        print(f"ima API 错误 {e.code}：{body}")
        sys.exit(1)
    except Exception as e:
        print(f"意外错误：{e}")
        raise
