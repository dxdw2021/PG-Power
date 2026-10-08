# PG-Power 项目初始化 + 论坛报名计划

## 一、项目概述

### 背景与痛点
- **组织痛点**：传统硬件功耗测试依赖 20 年前的老旧软件（如 GPIB 配套工具），界面陈旧、操作繁琐、缺乏自动化分析能力
- **核心目标**：用现代化 Python 工具链替换老旧方案，实现硬件功耗分析测试的自动化与可视化

### PG-Power 简介
**PG-Power** 是一个基于 Python + PyQt5 + PyQtGraph 的功耗测试工具，用于宠物定位器产品的功耗测试。支持：
- **GPIB 电源控制**（Keysight 663XX 系列，NI-488.2 驱动）— 兼容老旧 GPIB 设备
- **IotPower-cc USB 功耗仪**（合宙通信，VID=0x1209 PID=0x7301）— 微安级电流测量
- 实时电压/电流/功率波形采集、CSV 导出、三步校准向导、测试报告生成

核心文件：
- `main.py` — 主程序 GUI（~3100行），PyQt5 界面
- `iotpower_collector.py` — IotPower-cc 独立命令行采集脚本
- `requirements.txt` — 依赖：pyqt5, pyqtgraph, pyserial

## 二、项目初始化 (/init)

通过分析项目结构和依赖，确认项目初始化步骤：

1. **安装 Python 依赖**
   ```bash
   pip install -r requirements.txt
   ```
2. **验证 USB 驱动** — 确认 `libusb-1.0.dll` 存在于项目根目录
3. **验证 GPIB 驱动**（可选）— 确认 `ni4882.dll` 存在
4. **运行主程序**：`python main.py` 或双击 `run.bat`

## 三、论坛报名 — 浏览器自动化

### 目标
使用 MCP Chrome DevTools 浏览器自动化工具，导航到 `https://forum.trae.cn/c/38-category/40-category/40` 并完成报名操作。
https://forum.trae.cn/c/38-category/38

### 执行步骤

#### Step 1: 打开浏览器页面
调用 `mcp_Chrome_DevTools_MCP` 的 `new_page` 工具：
- URL: `https://forum.trae.cn/c/38-category/40-category/40`
https://forum.trae.cn/c/38-category/38
- 等待页面加载完成

#### Step 2: 获取页面快照
调用 `take_snapshot` 获取页面 a11y 树快照，了解页面结构：
- 识别页面上的报名表单、按钮、输入框等元素
- 确认"报名"的具体交互方式（回帖/表单/点击按钮）

#### Step 3: 根据页面结构执行报名
根据快照分析结果，分情况处理：

**情况 A：页面有报名按钮**
- 使用 `click` 点击报名按钮
- 等待弹出表单或跳转

**情况 B：页面有报名表单（输入框）**
- 使用 `fill` 填充各字段
- 点击提交按钮

**情况 C：需要回帖报名**
- 找到回复输入框
- 使用 `fill` 或 `type_text` 填写报名内容
- 点击提交/回复按钮

#### Step 4: 截图确认
调用 `take_screenshot` 截图保存，确认报名是否成功。

### 工具清单
| 工具 | 用途 |
|------|------|
| `new_page` | 打开论坛页面 |
| `take_snapshot` | 获取页面结构（a11y 树） |
| `take_screenshot` | 截图保存 |
| `click` | 点击按钮/链接 |
| `fill` | 填充输入框 |
| `type_text` | 键盘输入文本 |
| `wait_for` | 等待特定元素出现 |

## 四、假设与风险

1. **假设**：论坛页面可以正常访问，不需要登录（或已有登录态）
2. **假设**：报名表单字段为标准 HTML 表单元素（input/textarea/select）
3. **风险**：如果页面需要登录，可能需要先处理登录流程
4. **风险**：如果报名表单有验证码，需要人工介入

## 五、验证方式

- 页面快照中确认报名表单/按钮存在
- 填写完成后截图确认提交成功
- 页面出现"报名成功"或类似提示信息