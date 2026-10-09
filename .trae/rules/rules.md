# PG-Power 项目规则

## 项目概览

PG-Power 是一款宠物定位器测试工具（PyQt5 + Python），支持 USB IoT Power 电源 + GPIB 可编程电源控制、示波器波形采集、功耗测试、在线更新等功能。

- **入口文件**: `main.py`
- **打包 spec**: `pg-power.spec`
- **Python 环境**: `venv/`（已激活时用 `venv\Scripts\`）
- **版本号位置**: `main.py` 中的 `APP_VERSION` 常量
- **自动发版脚本**: `_release.py`（一键执行 Step 1-4）

## 发布流程（4 步全自动，无手动网页操作）

### Step 1 — 改版本号
编辑 `main.py` 找到 `APP_VERSION = "x.y.z"`，更新为目标版本号。

### Step 2 — 打包 exe
```powershell
# 只清 build/ (PyInstaller 临时目录), 保留 dist/ 里的旧版本!
Remove-Item build -Recurse -Force -ErrorAction SilentlyContinue

# 重新打包 (单文件, 无控制台窗口, spec 里已按版本号命名)
venv\Scripts\pyinstaller pg-power.spec --noconfirm

# 自动归档到 releases/ (保留所有历史版本, 不覆盖已存在的)
New-Item -ItemType Directory -Force releases | Out-Null
$new_exe = Get-ChildItem dist\PG-Power_v*.exe | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item $new_exe.FullName "releases\$($new_exe.Name)" -Force
```
产物:
- `dist\PG-Power_vX.Y.Z.exe`（当前版本, 70MB）
- `releases\PG-Power_v*.exe`（所有历史版本归档, 同时作为在线更新下载源）

**绝对不要** `Remove-Item dist, build -Recurse` — 会把 dist 里所有历史版本一起删掉!

### Step 3 — 更新 version.json（重要！影响在线更新下载链接）

version.json 中的 `exe_url` 必须指向 **GitCode contents API 返回的 download_url**（blobs 格式，速度最快 5.9 MB/s）：

```powershell
$token = $env:AG_TOKEN
$repo = "dxdw2021/PG-Power"
$tag  = "vX.Y.Z"
$name = "PG-Power_vX.Y.Z.exe"

# 通过 contents API 获取真实下载 URL (raw.gitcode.com/blobs/<sha>/...)
$resp = Invoke-RestMethod -Uri "https://gitcode.com/api/v5/repos/$repo/contents/releases/$name?ref=master" -Headers @{PRIVATE-TOKEN=$token}
$exe_url = $resp.download_url

$vj = @{
    version = "$tag"
    exe_url = "$exe_url"
    notes   = "vX.Y.Z: <改动摘要>"
} | ConvertTo-Json -Depth 3

[System.IO.File]::WriteAllText("$((Get-Location).Path)\version.json", $vj + "`n", (New-Object System.Text.UTF8Encoding $false))
```

### Step 4 — 提交 + 打 tag + 推送（双仓库同步）
```powershell
git add -A
git commit -m "feat: <本次改动摘要>"
git tag vX.Y.Z
git push origin master --tags        # → gitcode.com（国内主）
git push github master --tags       # → github.com（海外镜像）
```

✅ **发版完成！** 无需手动打开 GitCode Release 页面，exe 直接从仓库 `releases/` 目录通过 raw.gitcode.com 提供下载。

### 一键发版（推荐）
```powershell
# Step 1 手动改完版本号后
venv\Scripts\python _release.py
# 自动执行: 打包 → 归档 → version.json → commit → tag → push
```

## 在线更新机制

更新模块: `updater.py`（零第三方依赖，只用标准库）

### 版本检测
**优先**: GitCode contents API（`gitcode.com/api/v5/repos/{repo}/contents/version.json`）
- 读 version.json 文件，base64 解码得到版本号和 exe_url
- 国内响应 ~600ms，比 GitHub Release API 快 5 倍

### 下载源
**GitCode blobs**（raw.gitcode.com/.../blobs/<sha>/...）
- 速度: **5.9 MB/s**，70MB 约 **12 秒**
- 对比: GitCode Release 附件 2.3 MB/s | GitHub 0.2 MB/s

下载流程:
```
用户点"立即下载"
  → QProgressDialog 显示进度条 (0-100% + MB 计数)
  → urllib.request + Range header 流式下载
  → 保存到 %TEMP%\PG-Power_vX.Y.Z.exe
```

### 替换机制
**PowerShell 独立进程**（`pg_power_update.ps1`）
- `wscript.exe` 启动完全独立于主进程（不随主进程退出被杀）
- 主进程退出后，PowerShell 脚本通过 `Get-Process` 检测进程名消失
- `Move-Item -Force` 替换 exe，失败降级 `Copy-Item -Force`
- `Start-Process` 启动新版本
- 每步写入 **`%TEMP%\pg_power_update.log`** 便于追踪

## 注意事项

- **12V 电压支持**: 输出控制 SpinBox 范围 `setRange(0, 30)` 默认 5.0V；合并模式电压刻度 `setRange(-10, 30)`
- **PyInstaller 大文件**: 70MB exe 直接 git tracking（GitCode 限 500MB, GitHub 限 100MB）
- **双仓库推送**: origin → gitcode.com:dxdw2021/PG-Power（国内主），github → github.com/dxdw2021/PG-Power（海外镜像）
- **GPIB/USB 驱动**: ni4882.dll、libusb-1.0.dll 已打包进 spec 的 binaries
- **git config**: 新机器先 `git config user.email "dxdw2021@qq.com"` 和 `git config user.name "dxdw2021"`
- **AG_TOKEN**: 本机环境变量 `AG_TOKEN`（GitCode 个人访问令牌），用于 API 调用
- **为什么不用 GitCode Release 附件**: Release 附件上传 API 不开放（全 404），只能手动网页拖入；且下载速度比仓库 blobs 慢 2.5 倍。仓库 releases/ 目录 + raw.gitcode.com 是更优解
- **GitCode contents API 鉴权**: 公开仓库的 contents API 不用 token 也能访问，但加 `PRIVATE-TOKEN` header 更稳定
