# PLatex Client

Windows 剪贴板辅助工具。截屏复制公式图片后自动 OCR 识别为 LaTeX，不覆盖剪贴板原文。

## 功能

- **OCR 识别** — 复制截图，自动调用 GLM Vision 识别公式并返回 LaTeX
- **快捷键点击** — 配置全局快捷键，触发时鼠标瞬移到目标位置点击后恢复原位
- **脚本架构** — 每个功能模块（OCR、快捷键点击等）独立为脚本，各自管理设置和热键
- **控制面板** — 系统托盘 + Tab 页管理，每个脚本一页设置

## 安装

从 [Releases](https://github.com/AliceAuto/PLatex/releases) 下载安装包，或自行构建：

```bash
pip install -e .
```

## 使用

```bash
# 系统托盘模式（默认，打开控制面板）
platex-client panel

# 仅托盘
platex-client tray

# 前台运行
platex-client serve

# 手动识别一次
platex-client once
```

### 配置

配置文件路径：`%APPDATA%\PLatexClient\config.yaml`

```yaml
glm_api_key: YOUR_API_KEY_HERE
glm_model: glm-4.1v-thinking-flash
glm_base_url: https://open.bigmodel.cn/api/paas/v4/chat/completions
isolate_mode: false
interval: 0.8
```

控制面板中也可以直接编辑配置。快捷键点击的条目配置存储在 `scripts` 字段下。

### 快捷键点击

在控制面板的「快捷键点击」标签页：

1. 点击「添加快捷键」
2. 在快捷键输入框按下目标组合键
3. 输入 X/Y 坐标，或点击「拾取坐标」在全屏覆盖层上点选位置
4. 选择鼠标左键或右键
5. 填写备注（可选，方便识别）
6. 保存后即生效

触发快捷键时，鼠标瞬间移动到目标位置、执行点击、然后回到原来位置。

## 脚本开发

脚本放在 `scripts/` 目录下，实现 `ScriptBase` 接口：

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
        return "脚本描述"

    def create_settings_widget(self, parent=None):
        # 返回 PyQt6 QWidget 或 None
        ...

    def get_hotkey_bindings(self) -> dict[str, str]:
        return {"Ctrl+Alt+F1": "my_action"}

    def on_hotkey(self, action: str) -> None:
        if action == "my_action":
            ...

    # 如果需要 OCR 能力：
    def has_ocr_capability(self) -> bool:
        return True

    def process_image(self, image_bytes, context=None) -> str:
        return "识别结果"

def create_script() -> ScriptBase:
    return MyScript()
```

脚本必须提供 `create_script()` 工厂函数，客户端会自动扫描 `scripts/` 目录加载。

## 构建

```bash
pip install pyinstaller
python -m PyInstaller platex-client.spec
```

Inno Setup 安装包：

```bash
# 需要安装 Inno Setup 6
ISCC.exe platex-client.iss
```

## 项目结构

```
scripts/
  glm_vision_ocr.py    # OCR 脚本
  hotkey_click.py      # 快捷键点击脚本
src/platex_client/
  script_base.py       # 脚本基类
  script_registry.py   # 脚本注册中心
  hotkey_listener.py   # 全局热键监听
  loader.py            # 脚本加载器
  app.py               # 应用主逻辑
  tray.py              # 托盘 + 控制面板
  config.py            # 配置加载
  watcher.py           # 剪贴板监听
  clipboard.py         # 剪贴板操作
  windows_clipboard.py # Win32 剪贴板
  history.py           # SQLite 历史记录
  cli.py               # 命令行入口
```

## 许可证

MIT