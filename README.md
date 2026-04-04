# PLatex Client

PLatex Client 是一个 Windows 剪贴板助手，用来把图片中的数学公式或文本识别成 LaTeX，并自动放到系统剪贴板顶部。

识别成功后，结果会自动写入系统剪贴板，方便你直接 `Ctrl+V` 粘贴；同时也会保存到本地历史库，便于查看最近结果。

## 主要功能

- 监听 Windows 剪贴板中的图片
- 使用可插拔 OCR 脚本把图片转成 LaTeX 或文本
- OCR 成功后自动把结果写入系统剪贴板顶部
- 支持托盘常驻、历史查看、最近结果复制
- 支持自动模式和手动隔离模式

## 运行方式

### 1. 安装

需要 Python 3.10+。

```powershell
pip install -e .
```

### 2. 启动自动监听模式

默认模式会自动监听剪贴板图片，识别成功后自动写入剪贴板：

```powershell
platex-client tray
```

如果你想直接运行模块，也可以：

```powershell
python -m platex_client.cli tray
```

### 3. 手动隔离模式

如果你不想后台自动轮询，可以启用强隔离模式。此时不会自动 OCR，只会在托盘菜单里手动触发一次：

```powershell
platex-client --isolate tray
```

托盘菜单里的 `OCR once now` 会执行一次识别，并把结果写入系统剪贴板顶部。

### 4. 单次 OCR

只对当前剪贴板图片识别一次，然后退出：

```powershell
platex-client --isolate once
```

## 命令说明

```powershell
platex-client tray
platex-client serve
platex-client once
platex-client history --limit 10
platex-client latest
platex-client copy-latest
platex-client logs --limit 50
```

- `tray`：托盘模式，适合常驻使用
- `serve`：命令行轮询模式
- `once`：对当前剪贴板图片只识别一次
- `history`：查看最近 OCR 历史
- `latest`：查看最新一条识别结果
- `copy-latest`：把最新结果复制到剪贴板
- `logs`：查看最近日志

## OCR 结果如何输出

默认情况下，OCR 成功后会：

1. 将识别结果写入系统剪贴板顶部
2. 保留本地历史记录
3. 弹出成功提示窗口

注意：当前实现不会把图片回写到剪贴板，因此不会再出现“识别后图片被恢复”的行为。

## 配置

程序支持 YAML 配置文件。

默认配置路径：

- `%APPDATA%\PLatexClient\config.yaml`

你也可以手动指定：

```powershell
platex-client tray --config C:\path\to\config.yaml
```

配置示例：

```yaml
glm_api_key: your-api-key
glm_model: glm-4.1v-thinking-flash
glm_base_url: https://open.bigmodel.cn/api/paas/v4/chat/completions
publish_latex: true
isolate_mode: false
restore_delay: 0.25
interval: 0.8
```

优先级规则：

1. 命令行参数
2. 环境变量
3. 配置文件
4. 默认值

### 环境变量

默认 OCR 脚本使用 GLM 视觉模型，常用环境变量：

- `GLM_API_KEY`
- `GLM_MODEL`
- `GLM_BASE_URL`

## 默认 OCR 脚本

默认挂载脚本位于：

- `scripts/glm_vision_ocr.py`

你也可以自行实现一个脚本，只要提供下面这个函数即可：

```python
def process_image(image_bytes, context=None):
    ...
```

然后通过 `--script` 指定你的脚本路径。

## 日志与历史

日志默认写到：

- `%APPDATA%\PLatexClient\logs\platex-client.log`

历史默认保存到：

- `%APPDATA%\PLatexClient\history.sqlite3`

查看日志：

```powershell
platex-client logs --limit 50
```

查看历史：

```powershell
platex-client history --limit 20
```

## 打包与发布

仓库里已经配置了 GitHub Actions：

- [构建工作流](.github/workflows/build.yml)
- [发布工作流](.github/workflows/release.yml)

其中：

- `build.yml` 用于自动构建并上传 artifact
- `release.yml` 会在推送 `v*` tag 时自动构建并创建 GitHub Release

例如：

```bash
git tag v0.1.1
git push origin v0.1.1
```

## 目录结构

- `src/platex_client/`：客户端核心代码
- `scripts/glm_vision_ocr.py`：默认 OCR 脚本示例
- `tests/`：基础测试
- `.github/workflows/`：GitHub Actions 构建和发布流程

## 说明

- 自动模式下，程序会持续监听剪贴板图片并自动 OCR
- 强隔离模式下，不会后台监听，只能手动触发一次 OCR
- OCR 成功后，结果会直接放到系统剪贴板顶部，便于粘贴
- 如果脚本失败，错误会写入历史，便于排查
