# 小红书商品笔记爬虫使用说明

本文说明如何安装、登录和运行 `xhs_client.py`。所有命令均从项目根目录执行，
不依赖任何个人电脑的绝对路径。

## 1. 环境要求

- Python 3.10 或更高版本
- Git
- Windows、macOS 或 Linux
- 系统已安装 Microsoft Edge 或 Google Chrome
- 可以正常访问小红书的网络环境
- 小红书手机 App，用于扫码登录

## 2. 创建虚拟环境

### Windows PowerShell

```powershell
python -m venv .venv
```

如果系统使用 Python Launcher，也可以运行：

```powershell
py -3 -m venv .venv
```

### macOS / Linux

```bash
python3 -m venv .venv
```

## 3. 安装依赖

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\backend\app\data\crawlers\requirements.txt
```

### macOS / Linux

```bash
./.venv/bin/python -m pip install -r ./backend/app/data/crawlers/requirements.txt
```

登录直接使用系统已安装的 Edge 或 Chrome，不需要安装专用浏览器运行时。

## 4. 登录小红书

脚本默认先尝试系统 Edge，启动失败时自动尝试 Chrome。浏览器始终可见，扫码期间
不要提前关闭。登录 Cookie 保存到当前用户目录下的
`.xiaohongshu-cli/cookies.json`。

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe .\backend\app\data\crawlers\xhs_client.py --login
```

### macOS / Linux

```bash
./.venv/bin/python ./backend/app/data/crawlers/xhs_client.py --login
```

登录步骤：

1. 等待系统 Edge 或 Chrome 打开小红书登录页面。
2. 使用小红书手机 App 扫描二维码。
3. 在手机上确认登录。
4. 等待终端显示登录状态已保存，再关闭浏览器。

强制使用 Chrome：

```powershell
.\.venv\Scripts\python.exe .\backend\app\data\crawlers\xhs_client.py --login --browser chrome
```

强制使用 Edge：

```powershell
.\.venv\Scripts\python.exe .\backend\app\data\crawlers\xhs_client.py --login --browser edge
```

脚本使用项目独立资料目录：

```text
.runtime/xhs-profile/edge
.runtime/xhs-profile/chrome
```

该目录不会读取或修改日常浏览器资料，并已由 `.gitignore` 排除。

检查登录状态：

### Windows PowerShell

```powershell
.\.venv\Scripts\xhs.exe status
```

### macOS / Linux

```bash
./.venv/bin/xhs status
```

## 5. 按商品关键词采集

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe .\backend\app\data\crawlers\xhs_client.py "索尼XM5"
```

### macOS / Linux

```bash
./.venv/bin/python ./backend/app/data/crawlers/xhs_client.py "索尼XM5"
```

默认行为：

- 最多读取 50 个搜索候选。
- 持续检查候选，直到获得 10 篇有效笔记或候选耗尽。
- 只保留点赞数大于等于 10 的笔记。
- 每篇最多保存 20 条点赞达标的一级评论。
- 只保留点赞数大于等于 2 的评论。
- 每篇笔记最多读取 3 页一级评论。
- 优先处理标题中包含测评、使用体验、降噪、音质、佩戴、续航、避雷等词的笔记。

## 6. 按小红书链接采集

支持小红书笔记链接、带访问参数的搜索结果链接和小红书短链接。

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe .\backend\app\data\crawlers\xhs_client.py "小红书笔记链接"
```

### macOS / Linux

```bash
./.venv/bin/python ./backend/app/data/crawlers/xhs_client.py "小红书笔记链接"
```

## 7. 按淘宝或天猫链接采集

输入淘宝或天猫商品链接时，脚本可以使用 Playwright 读取商品标题，再将标题作为
小红书搜索关键词。

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe .\backend\app\data\crawlers\xhs_client.py "淘宝或天猫商品链接"
```

为了提高速度和关键词准确性，推荐通过 `--query` 手动指定商品名称：

```powershell
.\.venv\Scripts\python.exe .\backend\app\data\crawlers\xhs_client.py "淘宝或天猫商品链接" --query "索尼 WH-1000XM5"
```

macOS / Linux 使用相同参数，只需将 Python 路径改为 `./.venv/bin/python`。

## 8. 自定义采集参数

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe .\backend\app\data\crawlers\xhs_client.py "索尼XM5" `
  --candidates 50 `
  --max-notes 10 `
  --max-comments 20 `
  --min-note-likes 10 `
  --min-comment-likes 2 `
  --delay 1 `
  --output ".\backend\app\data\raw\sony_xm5.json"
```

### macOS / Linux

```bash
./.venv/bin/python ./backend/app/data/crawlers/xhs_client.py "索尼XM5" \
  --candidates 50 \
  --max-notes 10 \
  --max-comments 20 \
  --min-note-likes 10 \
  --min-comment-likes 2 \
  --delay 1 \
  --output "./backend/app/data/raw/sony_xm5.json"
```

参数说明：

| 参数 | 说明 | 默认值 |
| --- | --- | ---: |
| `--candidates` | 最多读取的搜索候选数 | 50 |
| `--max-notes` | 最多保存的有效笔记数 | 10 |
| `--max-comments` | 每篇最多保存的达标一级评论数 | 20 |
| `--min-note-likes` | 笔记最低点赞数，使用大于等于判断 | 10 |
| `--min-comment-likes` | 评论最低点赞数，使用大于等于判断 | 2 |
| `--delay` | 接口请求最小间隔秒数 | 1 |
| `--output` | JSON 输出文件路径 | 自动生成 |
| `--query` | 手动指定商品搜索关键词 | 无 |
| `--browser` | 系统浏览器：`auto`、`edge` 或 `chrome` | `auto` |
| `--profile-dir` | 登录和商品页解析使用的独立浏览器资料目录 | `.runtime/xhs-profile` |
| `--headless` | 解析淘宝/天猫标题时隐藏浏览器 | 关闭 |

查看完整命令行帮助：

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe .\backend\app\data\crawlers\xhs_client.py --help
```

### macOS / Linux

```bash
./.venv/bin/python ./backend/app/data/crawlers/xhs_client.py --help
```

## 9. 输出数据

未指定 `--output` 时，脚本会在项目根目录的 `data/raw/` 中生成：

```text
data/raw/xhs_dataset_年月日_时分秒.json
```

数据集主要包含：

- 输入类型和最终搜索关键词。
- 候选数、有效笔记数和评论数。
- 笔记标题、正文、标签、发布时间和互动量。
- 正文图片 URL。
- 点赞达标的一级评论。
- 采集过程中的结构化错误信息。

当前版本只保存正文图片 URL，不下载图片，也不执行 OCR。输出 URL 不包含
`xsec_token`，登录 Cookie 和临时访问令牌不会写入数据集。

## 10. 常见问题

### `AUTH_REQUIRED`

登录状态不存在或已过期。重新运行 `xhs_client.py --login`，通过系统 Edge/Chrome
完成扫码。

### `PLATFORM_CHALLENGE`

平台触发安全验证或访问限制。停止连续重试，等待一段时间后，在正常网络环境下
重新登录。不要使用验证码绕过、代理池或高频请求。

### `BROWSER_NOT_FOUND`

系统 Edge/Chrome 未安装、无法启动，或独立资料目录正在被另一个进程占用。确认浏览器
已安装并关闭其他使用同一 `.runtime/xhs-profile` 的爬虫进程，也可以通过
`--browser edge` 或 `--browser chrome` 明确指定。

### `SIGNATURE_ERROR`

小红书接口或签名规则可能发生变化，需要检查 `xiaohongshu-cli` 是否发布兼容版本，
升级后重新测试。

### 采集结果为 0

检查商品关键词是否准确，也可以临时降低笔记点赞阈值进行测试：

```powershell
.\.venv\Scripts\python.exe .\backend\app\data\crawlers\xhs_client.py "索尼XM5" --min-note-likes 0
```

## 11. 数据与账号安全

- 不要提交 `.venv/`、`.runtime/`、Cookie、Token、账号信息和浏览器配置目录。
- 原始数据集是否提交到仓库，应遵循团队的数据管理约定。
- 只采集正常登录后可见的公开内容。
- 不绕过验证码、安全验证或平台访问限制。
- 正式使用前应核对平台规则、隐私要求和第三方依赖许可证。
