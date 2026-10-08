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
# 清理旧产物
Remove-Item dist, build -Recurse -Force -ErrorAction SilentlyContinue

# 重新打包 (单文件, 无控制台窗口)
venv\Scripts\pyinstaller pg-power.spec --noconfirm
```
产物: `dist\PG-Power_vX.Y.Z.exe`（约 70MB）

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

### Step 4 — 创建 GitHub Release 并上传 exe（必须手动）

浏览器打开: `https://github.com/dxdw2021/PG-Power/releases/new?tag=vX.Y.Z&title=PG-Power%20vX.Y.Z`

**原因**: 系统 GH_TOKEN 没有 release upload 权限（HTTP 403 `Resource not accessible by integration`），必须手动拖文件上传。

### Step 5 — 更新 version.json（重要！影响在线更新检测）
提交后，确认 `version.json` 中的 `exe_url` 指向 **GitHub Release 官方下载链接**：
```
https://github.com/dxdw2021/PG-Power/releases/download/vX.Y.Z/PG-Power_vX.Y.Z.exe
```
**不要用 jsdelivr CDN**（单文件限 50MB，exe 70MB → 403 Forbidden）。

### Step 6 — 验证
- GitHub Release 页面能看到 asset（不是空列表）
- `https://api.github.com/repos/dxdw2021/PG-Power/releases/tags/vX.Y.Z` 返回 `assets` 非空
- 程序内点「检查更新」能检测到新版本

## 在线更新机制

更新模块: `updater.py`（零第三方依赖，只用标准库）

**检测源优先级**:
1. GitHub Release API（`github_repo` 配置项，最准）
2. 自动 CDN 候选（raw.githubusercontent.com → jsdelivr → fastgit）
3. 静态 JSON `static_url` 兜底

**下载源**: 永远用 GitHub Release 官方 URL（`github.com/.../releases/download/tag/name.exe`），不要用 jsdelivr / fastgit（jsdelivr 单文件 50MB 限制，fastgit 不稳定）。

## 注意事项

- **12V 电压支持**: 输出控制 SpinBox 范围 `setRange(0, 30)` 默认 5.0V；合并模式电压刻度 `setRange(-10, 30)`
- **PyInstaller 大文件**: 70MB exe 直接 git tracking（GitHub 限 100MB），不要用 git-lfs（jsdelivr 不代理 LFS，会 403）
- **双仓库推送**: origin → gitcode.com:dxdw2021/PG-Power，github → github.com/dxdw2021/PG-Power
- **GPIB/USB 驱动**: ni4882.dll、libusb-1.0.dll 已打包进 spec 的 binaries
- **git config**: 新机器先 `git config user.email "dxdw2021@qq.com"` 和 `git config user.name "dxdw2021"`
