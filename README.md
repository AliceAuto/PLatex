# PLatex Client

PLatex Client 是一个 Windows 剪贴板助手，用来挂载“图片 -> LaTeX”的脚本。

它会持续监听剪贴板：如果当前内容是图片，就调用你挂载的 OCR 脚本把图片转成 LaTeX，并把结果保存在本地历史里作为“第二份内容”。整个过程不会覆盖系统剪贴板，所以 `Ctrl+V` 仍然粘贴原图。

## 当前实现

- 监听 Windows 剪贴板中的图片内容
- 通过可插拔脚本完成 OCR 到 LaTeX
- 将识别结果保存到本地 SQLite 历史库
- 提供查看最近结果、复制最近结果的命令

## 目录结构

- `src/platex_client/`：客户端核心代码
- `scripts/glm_vision_ocr.py`：默认挂载脚本示例
- `tests/`：基础单元测试

## 安装

需要 Python 3.10+。

```bash
pip install -e .
```

## 配置脚本

默认脚本使用 GLM 视觉模型（智谱开放平台）。请先设置环境变量：

- `GLM_API_KEY`

可选环境变量：

- `GLM_MODEL`（默认：`glm-4.1v-thinking-flash`）
- `GLM_BASE_URL`（默认：`https://open.bigmodel.cn/api/paas/v4/chat/completions`）

如果你想换成自己的脚本，可以实现一个 `process_image(image_bytes, context)` 函数，然后启动时通过 `--script` 指向它。

## 配置文件

除了环境变量，你也可以放一个本地 YAML 配置文件。默认路径是：

- `%APPDATA%\PLatexClient\config.yaml`

你也可以手动指定：

```bash
platex-client tray --config C:\path\to\config.yaml
```

示例：

```yaml
glm_api_key: your-api-key
glm_model: glm-4.1v-thinking-flash
glm_base_url: https://open.bigmodel.cn/api/paas/v4/chat/completions
log_file: C:/Users/your-name/AppData/Roaming/PLatexClient/logs/platex-client.log
publish_latex: true
restore_delay: 0.25
interval: 0.8
```

优先级规则是：命令行参数 > 环境变量 > 配置文件 > 默认值。

## 运行

启动监听：

```bash
platex-client serve
```

托盘常驻：

```bash
platex-client tray --publish-latex
```

托盘模式会在 Windows 右下角显示图标，后台持续监听剪贴板，菜单里可以复制最新 LaTeX 或退出。

日志文件默认写到：

- `%APPDATA%\PLatexClient\logs\platex-client.log`

你也可以在终端直接看最近日志：

```bash
platex-client logs --limit 50
```

如果你开启 `--publish-latex`，程序会在识别后把 LaTeX 短暂写入系统剪贴板历史，再自动恢复原图。这样你可以在 `Win+V` 里看到公式，但极短时间内执行 `Ctrl+V` 仍然有可能粘贴到 LaTeX；如果你非常在意原图粘贴，就不要开启这个开关。

查看最近历史：

```bash
platex-client history
```

查看最新一条：

```bash
platex-client latest
```

把最新 LaTeX 复制到剪贴板：

```bash
platex-client copy-latest
```

## 行为说明

- 只读剪贴板，不会把图片剪贴板改成文本
- OCR 结果保存在本地数据库中，作为第二份内容
- 如果脚本失败，会把错误写入历史，方便排查

## 你接下来可以做的事

1. 换成你自己的 OCR 脚本
2. 把客户端做成托盘程序
3. 增加全局热键，把“第二份内容”快速贴出来

