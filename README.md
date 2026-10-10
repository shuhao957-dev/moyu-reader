# 摸鱼阅读器 (Moyu Reader)

> 一个透明的桌面阅读器，专为上班摸鱼设计

## 下载

提供两个版本，功能相同，区别仅在界面：

| | 隐匿版 (v2.1) | 进度条版 (v2.1-bar) |
|---|---|---|
| 界面 | 纯净，零多余元素 | 底部 3px 半透明进度条 |
| 点击跳转 | 无 | 点击进度条跳转到任意位置 |
| 适合场景 | 上班摸鱼（最隐蔽） | 长篇小说需要来回翻阅 |
| 下载 | [v2.1 Release](https://github.com/shuhao957-dev/moyu-reader/releases/tag/v2.1) | [v2.1-bar Release](https://github.com/shuhao957-dev/moyu-reader/releases/tag/v2.1-bar) |
| 源码 | `main` 分支 | `progress-bar` 分支 |

每个 Release 包含 3 个文件，放同一目录即可：
1. `MoyuReader.exe` — 主程序
2. `MicrosoftEdgeWebview2Setup.exe` — WebView2 安装包（离线备用，有网时程序会自动下载）
3. `dotnet-desktop-runtime-8.0.22-win-x64.exe` — .NET 运行时（可选，仅透明背景需要）

## 功能

- **透明窗口** — 文字浮在桌面上，透过窗口能看到后面的内容
- **窗口置顶** — 始终在最上层
- **自动滚动** — 可调速度，像股票行情一样慢慢滚
- **手动翻页** — 所有字母键 / 空格 / 回车 = 下一页（看起来像在打字）
- **内置设置** — Ctrl+, 调整窗口大小和滚动速度
- **进度保存** — 5 秒定时保存 + 关闭时保存，打开同一文件自动恢复位置
- **格式支持** — TXT、EPUB
- **依赖自检** — 缺少 WebView2 时自动下载安装，朋友双击就能用

## 快捷键

| 按键 | 功能 |
|---|---|
| 右键 | 打开文件 |
| 任意字母 / 空格 / 回车 | 下一页（手动模式） |
| M | 切换自动/手动模式 |
| Ctrl+, | 打开设置 |
| ESC | 关闭程序 |

自动模式下点击文字区域暂停/继续。

## 从源码运行

```bash
pip install pywebview ebooklib beautifulsoup4
python reader.py
```

透明背景（可选）需要额外安装 pythonnet 和 [.NET Desktop Runtime 8](https://dotnet.microsoft.com/download/dotnet/8.0)。

## 打包

```bash
pip install pyinstaller
pyinstaller MoyuReader_v2.spec
```

## 配置文件

- `~/.moyu_reader_config.json` — 窗口大小、位置、滚动速度
- `~/.moyu_reader_progress.json` — 每本书的阅读进度（全路径为 key）

## 贡献

欢迎 PR 和 Issue。

## 免责声明

本工具仅供学习交流。请合理安排工作和休息时间。作者不对因使用本工具而导致的任何后果负责。

## License

MIT
