# PLatex Client

[![Python](https://img.shields.io/badge/Python-%E2%89%A5%203.10-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-1.0.0-cyan.svg)](https://github.com/AliceAuto/PLatex/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Windows 剪贴板辅助工具。截屏复制公式图片后自动 OCR 识别为 LaTeX，不覆盖剪贴板原文。支持脚本扩展、全局快捷键、配置管理。

## 目录

- [功能](#功能)
- [安装](#安装)
- [使用](#使用)
  - [CLI 参考](#cli-参考)
  - [配置](#配置)
  - [快捷键点击](#快捷键点击)
- [架构概述](#架构概述)
- [脚本开发教程](#脚本开发教程)
  - [最小脚本示例](#最小脚本示例)
  - [ScriptBase API 参考](#scriptbase-api-参考)
  - [带设置 UI 的脚本](#带设置-ui-的脚本)
  - [带位置拾取的脚本](#带位置拾取的脚本)
  - [托盘菜单项](#托盘菜单项)
  - [配置导入导出](#配置导入导出)
  - [调试技巧](#调试技巧)
- [构建](#构建)
- [项目结构](#项目结构)
- [许可证](#许可证)

## 功能

- **OCR 识别** — 复制截图，自动调用 GLM Vision 识别公式并返回 LaTeX
- **快捷键点击** — 配置全局快捷键，触发时鼠标瞬移到目标位置点击后恢复原位，支持多配置组绑定不同窗口
- **脚本架构** — 每个功能模块独立为脚本，各自管理设置、热键和 UI，支持新式（`ScriptBase` 子类）和旧式（模块级 `process_image` 函数）两种格式
- **控制面板** — 系统托盘 + PyQt6 Tab 页管理，每个脚本一页设置，支持配置导入导出
- **配置管理** — 支持注册表/环境变量/安装时自定义配置目录，API Key 安全存储（不写入 YAML 文件）
- **历史记录** — SQLite（WAL 模式）存储 OCR 识别历史，支持查询和回溯
- **单实例锁** — 文件锁 + Windows 命名事件确保只运行一个实例

## 安装

从 [Releases](https://github.com/AliceAuto/PLatex/releases) 下载安装包，或自行构建：

```bash
pip install -e .
```

## 使用

### CLI 参考

```bash
platex-client <command> [options]
```

| 命令 | 说明 |
|------|------|
| `panel` | 系统托盘模式，打开控制面板（推荐） |
| `tray` | 仅系统托盘模式 |
| `tray --gui` | 系统托盘模式，启动时打开控制面板 |
| `serve` | 前台控制台运行 |
| `once` | 手动识别一次当前剪贴板 |
| `history --limit N` | 查看最近 N 条识别历史 |
| `latest` | 显示最近一次识别结果 |
| `copy-latest` | 复制最近一次 LaTeX 结果到剪贴板 |
| `logs --limit N` | 查看最近 N 行日志 |

**全局参数：**

| 参数 | 说明 |
|------|------|
| `--config PATH` | 指定 YAML 配置文件路径 |
| `--db-path PATH` | 指定 SQLite 数据库路径 |
| `--script PATH` | 指定 OCR 脚本路径 |
| `--log-file PATH` | 指定日志文件路径 |
| `--interval SECONDS` | 剪贴板轮询间隔（秒） |
| `--isolate` | 禁用后台轮询，仅手动触发 OCR |

### 配置

配置文件路径（按优先级）：

1. `--config` 命令行参数指定
2. `%APPDATA%\PLatexClient\config.yaml`
3. 当前工作目录的 `config.yaml`

**完整配置示例：**

```yaml
glm_api_key: YOUR_API_KEY_HERE   # 建议用环境变量 GLM_API_KEY 替代
glm_model: glm-4.1v-thinking-flash
glm_base_url: https://open.bigmodel.cn/api/paas/v4/chat/completions
isolate_mode: false              # true 则禁用后台轮询
interval: 0.8                    # 剪贴板轮询间隔（秒）
auto_start: false                # 开机自启
ui_language: en                  # UI 语言
scripts:
  glm_vision_ocr:
    model: glm-4.1v-thinking-flash
    base_url: https://open.bigmodel.cn/api/paas/v4/chat/completions
    enabled: true
  hotkey_click:
    enabled: true
    entries:
      - hotkey: "Ctrl+Alt+1"
        x: 500
        y: 300
        button: left
        remark: "示例"
```

**配置字段说明：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `glm_api_key` | string | — | 智谱 AI API Key，建议用环境变量 `GLM_API_KEY` 替代 |
| `glm_model` | string | — | GLM 模型名称 |
| `glm_base_url` | string | — | GLM API 地址 |
| `isolate_mode` | bool | `false` | 禁用后台轮询，仅手动触发 OCR |
| `interval` | float | `0.8` | 剪贴板轮询间隔（秒），最小 0.1 |
| `auto_start` | bool | `false` | 开机自启动 |
| `ui_language` | string | `"en"` | UI 语言 |
| `db_path` | string | — | SQLite 数据库路径 |
| `script` | string | — | OCR 脚本路径 |
| `log_file` | string | — | 日志文件路径 |

> **安全提示**：`api_key` 不会写入 YAML 文件，仅存储在环境变量或控制面板设置中。

### 快捷键点击

在控制面板的「快捷键点击」标签页：

1. 点击「➕ 添加快捷键」
2. 在快捷键输入框按下目标组合键
3. 输入 X/Y 坐标，或点击「📍 拾取坐标」在全屏覆盖层上点选位置
4. 选择鼠标左键或右键
5. 填写备注（可选，方便识别）
6. 保存后即生效

触发快捷键时，鼠标瞬间移动到目标位置、执行点击、然后回到原来位置。

---

## 架构概述

PLatex Client 采用**脚本平台架构**，核心设计理念：

- **事件驱动** — `EventBus` 发布/订阅模式解耦各模块（OCR 成功/失败、配置变更、面板显示、关闭等事件）
- **状态机管理** — `StateMachine` 严格控制应用生命周期：`IDLE → STARTING → RUNNING → STOPPING → STOPPED`
- **脚本插件化** — 客户端提供基础设施（托盘、配置目录、热键监听、脚本注册），功能模块以独立脚本形式运行
- **安全设计** — API Key 脱敏存储、脚本危险模式扫描、URL 白名单校验、路径遍历防护
- **Windows 深度集成** — 单实例锁（文件锁 + 命名事件）、DPI 感知、开机自启、Win32 热键、鼠标模拟

---

## 脚本开发教程

客户端启动时自动扫描 `scripts/` 目录，加载包含 `create_script()` 工厂函数的 `.py` 文件。

### 最小脚本示例

在 `scripts/` 目录下创建 `my_script.py`：

```python
from platex_client.script_base import ScriptBase

class MyScript(ScriptBase):
    @property
    def name(self) -> str:
        return "my_script"

    @property
    def display_name(self) -> str:
        return "我的脚本"

    @property
    def description(self) -> str:
        return "这是一个示例脚本"

def create_script() -> ScriptBase:
    return MyScript()
```

### ScriptBase API 参考

```python
from platex_client.script_base import ScriptBase

class MyScript(ScriptBase):
    # ── 必须实现 ──────────────────────────────────

    @property
    def name(self) -> str:
        """脚本唯一标识（英文、下划线），用于配置键名和日志"""

    @property
    def display_name(self) -> str:
        """控制面板标签页显示名称"""

    @property
    def description(self) -> str:
        """脚本功能的简短描述"""

    # ── 可选覆盖 ──────────────────────────────────

    def create_settings_widget(self, parent=None) -> QWidget | None:
        """创建设置页 QWidget，返回 None 表示无设置 UI。
        如果返回的 widget 有 save_settings() 方法，控制面板
        会在保存时调用它。"""
        return None

    def get_hotkey_bindings(self) -> dict[str, str]:
        """返回 {快捷键: 动作名} 映射。
        快捷键格式："Ctrl+Alt+1", "Ctrl+Shift+F5"
        动作名会传给 on_hotkey()。"""
        return {}

    def on_hotkey(self, action: str) -> None:
        """快捷键触发时的回调，action 为 get_hotkey_bindings 的值"""

    def activate(self) -> None:
        """脚本激活时调用（应用启动时）"""

    def deactivate(self) -> None:
        """脚本停用时调用（应用退出时）"""

    # ── OCR 能力 ─────────────────────────────────

    def has_ocr_capability(self) -> bool:
        """是否处理剪贴板图片，默认 False"""
        return False

    def process_image(self, image_bytes: bytes, context: dict | None = None) -> str:
        """处理剪贴板图片，返回识别结果（LaTeX 文本）。
        仅在 has_ocr_capability() 为 True 时被调用。"""

    # ── 托盘菜单 ─────────────────────────────────

    def get_tray_menu_items(self) -> list[TrayMenuItem]:
        """返回托盘右键菜单项列表，支持子菜单、勾选状态、分隔线"""

    # ── 配置持久化 ─────────────────────────────────

    def load_config(self, config: dict) -> None:
        """从配置字典加载脚本状态"""

    def save_config(self) -> dict:
        """将脚本状态导出为配置字典。
        注意：不要把 API key 等敏感信息写入 YAML，
        应使用环境变量或单独的安全存储。"""

    def import_config(self, path) -> dict:
        """从文件导入配置，默认 YAML 格式"""

    def export_config(self, path) -> None:
        """导出配置到文件，默认 YAML 格式"""

    # ── 连接测试 ─────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """测试脚本连接是否正常，返回 (成功, 消息)。
        控制面板会在设置页调用此方法。"""
        return True, "OK"
```

### 带设置 UI 的脚本

```python
from platex_client.script_base import ScriptBase

class GreetingScript(ScriptBase):
    def __init__(self):
        self._message = "Hello"
        self._count = 0

    @property
    def name(self) -> str:
        return "greeting"

    @property
    def display_name(self) -> str:
        return "问候脚本"

    @property
    def description(self) -> str:
        return "弹出问候消息"

    def get_hotkey_bindings(self) -> dict[str, str]:
        return {"Ctrl+Alt+G": "greet"}

    def on_hotkey(self, action: str) -> None:
        if action == "greet":
            self._count += 1
            print(f"{self._message} (count: {self._count})")

    def load_config(self, config):
        self._message = config.get("message", "Hello")
        self._count = config.get("count", 0)

    def save_config(self):
        return {"message": self._message, "count": self._count}

    def create_settings_widget(self, parent=None):
        from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QLabel

        script_ref = self

        class _SettingsWidget(QWidget):
            def __init__(self):
                super().__init__(parent)
                layout = QVBoxLayout(self)
                layout.addWidget(QLabel("问候语:"))
                self._msg_edit = QLineEdit()
                self._msg_edit.setText(script_ref._message)
                layout.addWidget(self._msg_edit)
                layout.addStretch()

            def save_settings(self):
                script_ref._message = self._msg_edit.text().strip() or "Hello"

        return _SettingsWidget()

def create_script() -> ScriptBase:
    return GreetingScript()
```

### 带位置拾取的脚本

快捷键点击脚本使用了 `simulate_click` 和位置拾取覆盖层：

```python
from platex_client.hotkey_listener import simulate_click

def on_hotkey(self, action: str) -> None:
    if action.startswith("click_"):
        simulate_click(x=500, y=300, button="left")
```

### 托盘菜单项

脚本可以通过 `get_tray_menu_items()` 向系统托盘右键菜单添加自定义项：

```python
from platex_client.script_base import ScriptBase, TrayMenuItem

class MyScript(ScriptBase):
    # ... (name, display_name, description 省略)

    def get_tray_menu_items(self) -> list[TrayMenuItem]:
        return [
            TrayMenuItem(label="执行任务", action=self._do_task),
            TrayMenuItem(separator=True),
            TrayMenuItem(
                label=lambda: "✓ 自动模式" if self._auto else "自动模式",
                action=self._toggle_auto,
                checked=lambda: self._auto,
            ),
            TrayMenuItem(
                label="子菜单",
                items=[
                    TrayMenuItem(label="选项 A", action=self._option_a),
                    TrayMenuItem(label="选项 B", action=self._option_b),
                ],
            ),
        ]
```

### 配置导入导出

`ScriptBase` 提供了默认的 YAML 导入导出实现。控制面板在每个脚本标签页底部自动添加「导入配置」和「导出配置」按钮。

如果需要自定义格式，覆盖 `import_config` 和 `export_config` 方法即可。

### 调试技巧

1. **查看日志**：`platex-client logs --limit 100`
2. **手动测试**：`platex-client once`（单次 OCR 识别）
3. **日志位置**：`%LOCALAPPDATA%\Copilot\PLatexClient\logs\platex-client.log`
4. **脚本加载日志**：启动时日志会显示 `Loaded new-style script: <name> from <path>`，如果脚本有语法错误会打印完整 traceback

---

## 构建

```bash
# 开发安装
pip install -e .

# PyInstaller 打包
python -m PyInstaller --noconfirm --clean --onedir --noconsole \
  --contents-directory . --name platex-client \
  --icon assets/platex-client.ico --paths src \
  --add-data "scripts/glm_vision_ocr.py;scripts" \
  --add-data "scripts/hotkey_click.py;scripts" \
  --hidden-import pynput.keyboard --hidden-import pynput.mouse \
  --hidden-import pynput._util \
  --collect-submodules PyQt6 --collect-data PyQt6 --collect-binaries PyQt6 \
  launcher.py

# Inno Setup 安装包（需要安装 Inno Setup 6）
ISCC.exe platex-client.iss
```

CI 自动构建：推送 `v*` 标签即可触发 GitHub Actions 打包并发布 Release。

## 项目结构

```
scripts/
  glm_vision_ocr.py          # OCR 脚本（ScriptBase 实现）
  hotkey_click.py            # 快捷键点击脚本（ScriptBase 实现）
src/platex_client/
  __init__.py                # 包初始化，版本号
  app.py                     # 应用主逻辑（注册脚本、启动热键、后台监听）
  cli.py                     # 命令行入口（参数解析、单实例锁、子命令）
  config.py                  # YAML/JSON 配置加载，AppConfig 数据类
  config_manager.py          # 配置目录管理（注册表/环境变量/导入导出）
  models.py                  # 数据模型（ClipboardEvent, ClipboardImage, OcrProcessor）
  script_base.py             # 脚本抽象基类 + TrayMenuItem
  script_registry.py         # 脚本注册中心（发现、加载、安全扫描、生命周期）
  script_context.py          # 脚本上下文
  loader.py                  # 脚本加载器（new-style / legacy 兼容适配）
  watcher.py                 # 剪贴板轮询监听（去重、OCR 超时保护）
  clipboard.py               # 剪贴板图像读取（重试、大小限制）、文本写入
  clipboard_listener.py      # 剪贴板变化监听
  windows_clipboard.py       # Win32 剪贴板操作封装
  history.py                 # SQLite 历史存储（WAL 模式）
  hotkey_listener.py         # 全局热键监听（pynput GlobalHotKeys + simulate_click）
  win32_hotkey.py            # Win32 热键注册实现
  mouse_input.py             # 鼠标输入（获取前台窗口标题等）
  tray.py                    # 系统托盘 + 控制面板（pystray + PyQt6）
  popup_manager.py           # OCR 成功弹窗队列
  events.py                  # 事件总线 EventBus（发布/订阅、弱引用）
  app_state.py               # 应用状态机（IDLE → STARTING → RUNNING → STOPPING → STOPPED）
  app_config.py              # 应用配置辅助
  api_key_masking.py         # API Key 脱敏处理
  secrets.py                 # 安全存储（内存中 secrets 管理）
  logging_utils.py           # 日志配置和格式化
  platform_utils.py          # 平台工具（DPI 感知、开机自启、单实例信号）
  ui/
    control_panel.py         # 控制面板主窗口（QTabWidget）
    general_tab.py           # 通用设置 Tab 页
    log_tab.py               # 日志查看 Tab 页
    popup.py                 # OCR 成功弹窗（自动淡出、点击写入剪贴板）
    glass_utils.py           # 毛玻璃/透明效果工具
launcher.py                  # PyInstaller 入口（引导日志、全局异常捕获）
```

## 许可证

MIT
