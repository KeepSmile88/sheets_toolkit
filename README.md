# 📊 Google Sheets Toolkit (谷歌表格高级工具箱)

基于 **Python + PySide6 + Google Workspace API** 构建的 Google Sheets 与 Google Drive 批量操作工具箱。

采用 **MVC 架构 + 命令模式 + 策略模式 + 任务调度**，提供完善、流畅、且支持全异步操作的专业桌面 GUI 界面。专为高频、大量的自动化办公与资产管理场景设计。

---

## ✨ 核心特性与功能概览 (Key Features)

### 1. 🔐 账号与权限双核管理系统 (最新特性)
- **多租户与身份隔离**: 引入 `sqlite3` 本地持久化存储，支持内置 Admin 与自定义 Guest/普通用户的隔离体系。
- **动态免密/强验证**: 登录面板根据账号态势自动判定，支持免密一键登录与 SHA-256 强验证登陆。
- **协作者权限批量操控**: 一键获取、变更或移除指定文件夹内所有表格的协作者权限；支持所有权 (Ownership) 的一键接收。
- **高级安全策略下发**: 一键下发“禁止下载/复制/打印” (Secure Mode) 以及“仅所有者可分享” (Writers cannot share) 等工作簿级安全策略。

### 2. 📂 穿透式网盘资产管理器 (最新特性)
- **Drive 文件夹浏览器**: 输入任意 Google Drive 链接，自动解析并在本地通过高速多线程加载文件夹下属所有资源。
- **递归引擎**: 独创的递归获取算法，一键穿透多层子文件夹，将散落的文件资源“拉平”展示在表格中。
- **多维过滤矩阵**: 支持精准匹配、模糊匹配、正则表达式，结合“按归属”或“按用户名/邮箱”的过滤目标，在海量文件中实现秒级定位。

### 3. 🛠️ 经典批量处理体系 (全能矩阵)
| 分类 | 功能 |
|------|------|
| **数据操作** | 读取/写入/清空/批量写入数据 |
| **结构管理** | 创建/重命名/删除工作表，删除行 |
| **数据处理** | 求和/筛选/排序/去重/关键词查找/日期过滤 |
| **权限协作** | 邀请协作者/回收权限/设置只读 |
| **备份导出** | 云端复制 + 本地 Excel 双重备份 |
| **调度系统** | 一次性/间隔/每日计划任务 |
| **撤销支持** | 写入/清空/创建/重命名操作可完美撤销 |
| **数据预览** | QTableWidget 实时预览 Sheet 数据 |
| **操作历史** | 完整的操作记录和结果展示 |
| **主题切换** | 浅色/深色主题动态平滑切换 |

---

## 🚀 高性能架构与体验保障

- **全异步无阻塞 (QThread Pool)**: 所有网络 I/O (Google API 通信、下载、上传) 和耗时逻辑均通过底层的 `QThread` 与 `QRunnable` 分离至后台执行，保证在处理数千个表格时，主 UI 依然保持极致顺滑。
- **智能垃圾回收防崩**: 严格的内存生命周期管控 (`deleteLater` 释放模型) 彻底杜绝了 C++ 层面的 `Destroyed while thread is still running` 致命崩溃。
- **安全沙箱 (防篡改设计)**: 代码级消除敏感凭据硬编码，全面启用 Base64 脱敏与哈希校验，轻松通过 GitHub CodeQL 静态安全扫描。

---

## 🏗 架构设计

```text
sheets_toolkit/
├── main.py                  # 应用入口
├── config.json              # 配置文件
├── requirements.txt         # 依赖
│
├── core/                    # 核心层
│   ├── auth.py              # OAuth2 认证（单例模式）
│   ├── config.py            # 配置管理（单例模式）
│   ├── db.py                # SQLite3 本地凭证数据库
│   ├── exceptions.py        # 异常体系 + API 重试装饰器
│   ├── executor.py          # 多线程执行器 (QRunnable)
│   ├── logger.py            # 统一日志（控制台 + 文件 + Qt 信号）
│   └── scheduler.py         # APScheduler 任务调度
│
├── services/                # 服务层
│   ├── sheet_service.py     # 门面类（统一所有 API 操作）
│   ├── command/             # 命令模式
│   │   ├── base_command.py  # ABC 基类（含 undo 支持）
│   │   ├── write_command.py
│   │   ├── read_command.py
│   │   └── ...              # 其他操作命令
│   └── strategy/            # 策略模式
│       ├── base_strategy.py # ABC 基类
│       └── ...              # 排序/去重等策略
│
├── modules/                 # 便捷函数层（SheetService 的薄封装）
│   └── ...                  # drive_ops, sheet_ops, permissions 等
│
└── ui/                      # 界面层 (PySide6)
    ├── main_window.py       # 主窗口
    ├── login_dialog.py      # 安全登录与权限分离
    ├── controller.py        # MVC 控制器
    ├── theme_manager.py     # 主题管理器
    └── ...                  # 各个批量操作的独立 Widget (DriveFolder, PermissionManager 等)
```

---

## 📦 安装与运行 (Installation & Usage)

### 1. 安装依赖
确保已安装 Python 3.9+。
```bash
pip install -r requirements.txt
```
*(如果缺失某些包，可手动安装：`pip install PySide6 google-api-python-client google-auth-httplib2 google-auth-oauthlib apscheduler`)*

### 2. 配置 Google API
1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建项目并启用 **Google Sheets API** 和 **Google Drive API**
3. 下载 `credentials.json` 到项目根目录

### 3. 运行与初始登录
```bash
python main.py
```
- **默认管理员账号**：`admin`
- 首次运行时会弹出浏览器完成 OAuth2 授权。

---

## 🎨 主题切换
通过菜单 **👁 视图 → 🌓 切换主题** 在浅色和深色模式之间自由切换。

## ⚙️ 配置文件 (config.json)
| 选项 | 说明 | 默认值 |
|------|------|--------|
| `default_spreadsheet_id` | 默认 Sheet ID | 空 |
| `backup_dir` | 备份目录 | `backups` |
| `log_level` | 日志级别 | `INFO` |
| `theme` | 主题 (light/dark) | `light` |
| `max_retries` | API 重试次数 | `3` |
| `recent_spreadsheets` | 最近使用的 Sheet ID | `[]` |

---
*该系统不仅是面向最终用户的高级操作仪表盘，更是一套可高度扩展的底层框架。开发者可以轻松地通过接入 `ui/controller.py` 与 `services/*` 添加新的算子和组件。*
