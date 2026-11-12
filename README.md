# 摸鱼阅读器 (Moyu Reader)

> 一个透明的桌面阅读器，专为上班摸鱼设计 —— 文字浮在桌面上，透过窗口能看到后面的内容。

## 最近更新

- **v3.2（当前版本）**
  - 鼠标感应模式下「离开窗口后隐藏延迟」可在设置里调节（0 = 鼠标一离开立刻消失）
  - 鼠标感应模式下光标停留 3 秒自动隐藏，不再挡字
  - 窗口在**任务栏和 Alt+Tab 里都不再显示**，降低暴露风险
- **v3.1**
  - 重写渲染层为**真·虚拟滚动（windowing）**：DOM 只挂视口附近少量块，6MB+ 的 EPUB 也能秒开、翻页零抖动
  - EPUB 解析改用正则快通道，**不再依赖 beautifulsoup4 / lxml**，体积更小、更稳
  - TXT/EPUB 走 gzip 压缩过桥，大文件打开不再卡

## 下载（普通用户看这里）

**👉 点右侧（或顶部）的 [Releases 发布页](https://github.com/shuhao957-dev/moyu-reader/releases) 下载 exe，开箱即用。**

> ⚠️ **不要**点击仓库页面上绿色的 "Code → Download ZIP" —— 那是**源码**，不是软件。
> 里面没有可运行的 exe，直接运行其中的脚本会报错（例如"Windows 找不到文件 Pythonw"）。

### 我该下哪个版本？（按系统对号入座）

| 你的系统 | 推荐版本 | 说明 |
|---|---|---|
| Windows 10 / 11 | **[v3.2.1](https://github.com/shuhao957-dev/moyu-reader/releases/tag/v3.2.1)（正式版）** | 功能最全、维护最活跃 |
| Windows 7（尤其长期不更新 / 内网机） | [v2.1.6-win7](https://github.com/shuhao957-dev/moyu-reader/releases/tag/v2.1.6-win7)（兼容版） | 独立维护的老技术栈，安装指引和已知限制见 [win7 分支说明](https://github.com/shuhao957-dev/moyu-reader/tree/win7) |
| macOS | 实验版 | [v2.1.6-mac](https://github.com/shuhao957-dev/moyu-reader/releases/tag/v2.1.6-mac)（Apple Silicon 构建包，未经充分实测）；Intel Mac 需自行构建，见 [mac 分支](https://github.com/shuhao957-dev/moyu-reader/tree/mac) |

**当前推荐版本：[v3.2](https://github.com/shuhao957-dev/moyu-reader/releases/tag/v3.2)**
（在 v3.0 基础上：更流畅的大文件渲染 + 鼠标感应隐藏细节打磨 + 任务栏/Alt+Tab 不显示，详见发布说明）

**一般只需要下载 1 个文件：`MoyuReader_v3.2.exe`** — 主程序自带全部运行时，双击即用。

另外 2 个文件是备用件，**只有运行 exe 弹出缺少运行时的提示时才需要下载**：
- `MicrosoftEdgeWebview2Setup.exe` — WebView2 在线安装器（绝大多数 Win10/11 已自带，无需理会；完全无外网的电脑请改用微软官网的离线安装包）
- `dotnet-desktop-runtime-8.0.22-win-x64.exe` — .NET 运行时（可选，仅透明背景需要）

## 功能

- **透明窗口** — 文字浮在桌面上，透过窗口能看到后面的内容；v3.0 修复 Windows 11 深色模式下背景变黑的问题
- **窗口置顶** — 始终在最上层
- **任意位置拖动** — 鼠标 / 触摸屏 / 触控笔都能拖（v2.1.7 重构为指针捕获，快速拖动不断流）
- **自动滚动** — 可调速度，像股票行情一样慢慢滚；v3.0 起打开书默认暂停起步（按空格开滚），并记住上次用的是自动还是手动
- **手动翻页** — 所有字母键 / 空格 / 回车 = 下一页（看起来像在打字）；v3.0 起每次翻页实测校准，长篇连翻几十页首行也不会变半截字
- **目录面板**（v3.0 新增） — Ctrl+T 打开，自动识别章节（第X章 / 数字编号 / 卷 等），EPUB 直接用书里自带的目录；没有章节的书按 500 行分段
- **全文搜索**（v3.0 新增） — Ctrl+F 唤起迷你搜索条，Enter 下一处、Shift+Enter 上一处
- **进度条 + 百分比跳转**（v3.0 新增） — 设置里开启底部进度条，点击进度条或输入百分比直达任意位置
- **鼠标感应模式** — 鼠标离开窗口自动隐藏并暂停滚动，点击可穿透到下层窗口，鼠标移回即恢复
  - v3.2 新增：离开后的隐藏延迟可在设置里调节；感应模式下光标停留 3 秒自动隐藏
- **文字样式** — 字号 / 颜色 / 不透明度可调，调低不透明度可让文字透出后面的工作内容
- **内置设置** — Ctrl+, 调整窗口大小、滚动速度和文字样式，附快捷键速查
- **进度保存** — 5 秒定时保存 + 关闭时保存，打开同一文件自动恢复位置
- **格式支持** — TXT（自动识别 UTF-8 / UTF-16 / GBK 等编码）、EPUB；v3.0 起文件选择框默认同时显示 txt 和 epub
- **大文件流畅**（v3.1 新增） — 真·虚拟滚动渲染 + gzip 过桥 + 正则 EPUB 快通道，6MB+ 的小说打开快、翻页零抖
- **依赖自检** — 缺少 WebView2 时自动下载安装
- **低调运行**（v3.2 新增） — 窗口不在任务栏和 Alt+Tab 中显示

## 快捷键

| 按键 | 功能 |
|---|---|
| 右键 | 打开文件 |
| 任意字母 / 空格 / 回车 | 下一页（手动模式）；自动模式下空格 = 暂停/继续滚动 |
| M | 切换自动/手动模式 |
| Ctrl+F | 全文搜索（Enter 下一处，Shift+Enter 上一处，Esc 关闭） |
| Ctrl+T | 目录面板（点章节直达，Esc 关闭） |
| Ctrl+, | 打开设置 |
| Ctrl+H | 切换鼠标感应模式 |
| ESC | 关闭面板；无面板打开时关闭程序 |

自动模式下点击文字区域暂停/继续。

## 从源码运行（开发者向）

需要本机已安装 Python 3.10+：

```bash
pip install pywebview ebooklib
python reader.py
```

透明背景（可选）需要额外安装 pythonnet 和 [.NET Desktop Runtime 8](https://dotnet.microsoft.com/download/dotnet/8.0)。
`virtual.js`（虚拟滚动渲染器）已随仓库分发，无需额外安装。

## 打包

```bash
pip install pyinstaller
pyinstaller MoyuReader_v3.2.spec
```

## 配置文件

- `~/.moyu_reader_config.json` — 窗口大小、位置、滚动速度、文字样式、鼠标感应开关、离开隐藏延迟
- `~/.moyu_reader_progress.json` — 每本书的阅读进度（全路径为 key）

## 鸣谢

- **Socsal**：感谢其 Pull Request [#1《修复透明背景并将设置合并为单程序》](https://github.com/shuhao957-dev/moyu-reader/pull/1)，解决了早期「设置需要分窗口进行」的问题。
- **星星不在家（热心网友）**：感谢提供虚拟滚动渲染优化方案（私聊发送文件与工作区，未走 PR）。v3.1 引入的真·虚拟滚动渲染（windowing）核心思路来源于此，让 6MB+ 的 EPUB 也能流畅打开、翻页零抖动。
- 本软件由 **Claude、GLM、Hy** 共同编写。

## 贡献

欢迎 PR 和 Issue。

## 免责声明

本工具仅供学习交流。请合理安排工作和休息时间。作者不对因使用本工具而导致的任何后果负责。

## License

MIT
