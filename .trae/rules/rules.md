# PG-Power 项目规则

## 项目概览

PG-Power 是一款宠物定位器测试工具（PyQt5 + Python），支持 USB IoT Power 电源 + GPIB 可编程电源控制、示波器波形采集、功耗测试、在线更新等功能。

- **入口文件**: `main.py`
- **打包 spec**: `pg-power.spec`
- **Python 环境**: `venv/`（已激活时用 `venv\Scripts\`）
- **版本号位置**: `main.py` 中的 `APP_VERSION` 常量

## 发布流程（每次发版必须严格执行）

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
- `releases\PG-Power_v*.exe`（所有历史版本归档）

**绝对不要** `Remove-Item dist, build -Recurse` — 会把 dist 里所有历史版本一起删掉!

### Step 3 — 提交 + 打 tag + 推送（双仓库同步）
```powershell
# 如果未配置 git user, 先执行:
git config user.email "dxdw2021@qq.com"
git config user.name "dxdw2021"

git add -A
git commit -m "feat: <本次改动摘要>"
git tag vX.Y.Z
git push origin master --tags        # → gitcode.com
git push github master --tags       # → github.com
```

### Step 4 — 创建 GitCode Release 并上传 exe（必须手动）

浏览器打开: `https://gitcode.com/dxdw2021/PG-Power/releases/create`

填写 tag（如 `vX.Y.Z`）、标题、描述后，**在发布描述下方的附件区域拖入 exe 文件**，点「发布」。

编辑已有 Release: `https://gitcode.com/dxdw2021/PG-Power/releases/edit/vX.Y.Z`

**GitCode Release API 不支持 asset 上传**，必须手动在网页上拖入 exe 文件。

### Step 5 — 更新 version.json（重要！影响在线更新检测）
提交后，确认 `version.json` 中的 `exe_url` 指向 **GitCode Release 官方下载链接**：
```
https://gitcode.com/dxdw2021/PG-Power/releases/download/vX.Y.Z/PG-Power_vX.Y.Z.exe
```

### Step 6 — 验证
- GitCode Release 页面能看到 asset（不是空列表）
- GitCode API 返回 assets 非空
  ```powershell
  $token = $env:AG_TOKEN
  Invoke-RestMethod -Uri "https://gitcode.com/api/v5/repos/dxdw2021/PG-Power/releases/tags/vX.Y.Z" -Headers @{PRIVATE-TOKEN=$token}
  ```
- 程序内点「检查更新」能检测到新版本

## 在线更新机制

更新模块: `updater.py`（零第三方依赖，只用标准库）

**检测源优先级**:
1. GitCode contents API（`gitcode.com/api/v5/repos/.../contents/version.json`，国内最快 600ms）
2. GitHub Release API（海外镜像，国内慢但备份）
3. 静态 JSON `static_url` 兜底

**下载源**: GitCode Release 官方 URL（`gitcode.com/.../releases/download/tag/name.exe`），国内下载速度比 GitHub 快 10 倍+。

**更新替换机制**: PowerShell 独立进程（`pg_power_update.ps1`）
- `wscript.exe` 启动完全独立于主进程
- 主进程退出后，PowerShell 脚本检测进程名消失
- `Move-Item -Force` 替换 exe，失败降级 `Copy-Item -Force`
- `Start-Process` 启动新版本
- 每步写入 `%TEMP%\pg_power_update.log` 便于追踪

## 注意事项

- **12V 电压支持**: 输出控制 SpinBox 范围 `setRange(0, 30)` 默认 5.0V；合并模式电压刻度 `setRange(-10, 30)`
- **PyInstaller 大文件**: 70MB exe 直接 git tracking（GitCode 限 500MB）
- **双仓库推送**: origin → gitcode.com:dxdw2021/PG-Power（国内主），github → github.com/dxdw2021/PG-Power（海外镜像）
- **GPIB/USB 驱动**: ni4882.dll、libusb-1.0.dll 已打包进 spec 的 binaries
- **git config**: 新机器先 `git config user.email "dxdw2021@qq.com"` 和 `git config user.name "dxdw2021"`
- **AG_TOKEN**: 本机环境变量 `AG_TOKEN`（GitCode 个人访问令牌），用于 API 调用
- **GitCode Release URL 格式**: `https://gitcode.com/<owner>/<repo>/releases/download/<tag>/<filename>`
