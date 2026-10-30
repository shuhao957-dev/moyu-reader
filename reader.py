import webview
import sys
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
import json
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from settings import get_settings_html

class BookReader:
    def __init__(self, data_dir=None):
        self.content = ""
        self.current_file = None
        data_dir = Path(data_dir) if data_dir is not None else Path.home()
        self.progress_file = data_dir / '.moyu_reader_progress.json'
        self.config_file = data_dir / '.moyu_reader_config.json'
        self._window = None
        self._reader_size = None
        # 自研 pointer 拖动状态（取代 pywebview easy_drag）
        self._drag_anchor = None   # (win_left, win_top, anchor_screen_x, anchor_screen_y, dpi_scale)
        self._drag_hwnd = None
        self._drag_lock = threading.Lock()
        self.progress = {}
        self.chapters = []   # [{title, offset}]：目录面板数据（load 时扫描）
        self.sense = MouseSenseController(self)
        self.load_progress()
        self.load_config()

    DEFAULT_CONFIG = {
        'window': {'width': 400, 'height': 60, 'x': 100, 'y': 100},
        'speed': 50,
        'mouse_sense': False,
        'font_size': 14,
        'text_color': '#333333',
        'text_opacity': 100,
        'progress_bar': False,
        'auto_mode': True,   # 上次使用的翻页模式（自动/手动），打开书时恢复
    }

    def load_config(self):
        """加载配置文件"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            else:
                self.config = self.DEFAULT_CONFIG
        except:
            self.config = self.DEFAULT_CONFIG
        # 老配置文件补齐新增字段的默认值
        for key, value in self.DEFAULT_CONFIG.items():
            self.config.setdefault(key, value)

    def load_progress(self):
        """加载阅读进度"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    self.progress = json.load(f)
            except:
                self.progress = {}

    def save_progress(self, file_path, position):
        """保存阅读进度"""
        self.progress[file_path] = position
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.progress, f, indent=4, ensure_ascii=False)
        except:
            pass

    def get_progress(self, file_path):
        """获取阅读进度。先查全路径，再回退短文件名（兼容旧数据）"""
        pos = self.progress.get(file_path, None)
        if pos is not None:
            return pos
        # Fallback: old versions stored progress under short filename
        short_name = Path(file_path).name
        pos = self.progress.get(short_name, 0)
        if pos > 0:
            # Migrate old entry to full path key
            self.progress[file_path] = pos
            del self.progress[short_name]
            self._save_progress_sync()
        return pos

    def _save_progress_sync(self):
        """Internal: flush progress dict to disk immediately"""
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.progress, f, indent=4, ensure_ascii=False)
        except:
            pass

    def get_config(self):
        return self.config

    # ---------- v3.0 章节目录扫描（目录面板数据源） ----------
    # 严格档：误判率极低，命中即信。
    #   第X章/节/卷/回/部/集/篇（允许【】[] 包裹、允许冒号空格接标题）、
    #   序章/楔子/引子/尾声等、番外、Chapter N、卷一/卷12 式（数字在后）。
    # 行短（≤34字）才算标题，避免把正文里恰好以"第…"开头的长句误认成章节。
    CHAPTER_TITLE_RE = re.compile(
        r'^(?:[【\[]?第[零〇一二三四五六七八九十百千万两0-9]{1,14}[章节卷回部集篇][】\]]?'
        r'|序章|序言|楔子|引子|尾声|终章|后记'
        r'|番外.{0,12}'
        r'|卷[零〇一二三四五六七八九十百千0-9]{1,6}(?![章节卷回部集篇])'
        r'|Chapter\s*\d+)'
        r'.{0,20}$'
    )
    # 宽松档：纯编号式章节（用户书库实测存在），必须整档通过分布校验才启用。
    #   "1"/"12" 纯数字独立行、"一、标题"、"1. 标题"、"12 决战"、"三" 等。
    CHAPTER_LOOSE_RE = re.compile(
        r'^(?:'
        r'\d{1,4}'                                   # 纯数字独立行
        r'|\d{1,4}[、.．:：](?!\d)\s*.{0,24}'         # 数字+分隔符+标题（"1.5" 不算）
        r'|\d{1,4}\s+.{1,24}'                        # 数字+空格+标题
        r'|[零〇一二三四五六七八九十百千]{1,6}[、.．]\s*.{0,24}'
        r'|[零〇一二三四五六七八九十百千]{1,6}'
        r')$'
    )
    LOOSE_LINE_MAX = 30          # 宽松档行长度上限（严格档 34）
    LOOSE_MIN_HITS = 3           # 宽松档最少命中数
    LOOSE_MIN_GAP = 8            # 命中行间隔中位数下限：低于此判定为正文列表而非章节

    def _scan_chapters(self):
        """扫描全书章节标题行。offset 记录标题首字符在全文字符串中的偏移，
        按 UTF-16 码元计数——与 JS 侧 textNode.length 同单位，前端用 Range
        量像素时才能指哪打哪（星外字符会让 Python len() 少算一截）。

        两档策略：严格档命中即信；宽松档（纯编号式）只在整本书通过
        "命中数 + 间隔中位数" 校验时才启用，防止把正文里的
        "1. 2. 3." 列表或 "一、二、三、" 递进句误认成目录。
        一个都认不出时按 500 行一段生成伪目录（用户拍板的兜底方案）。"""
        chapters = []
        if self.content:
            strict_idx = []   # 严格档命中的行号
            loose_idx = []    # 宽松档命中的行号（不含严格档已命的）
            strict_rows, loose_rows = [], []
            for i, line in enumerate(self.content.split('\n')):
                if len(line) <= 34 and self.CHAPTER_TITLE_RE.match(line):
                    strict_idx.append(i)
                    strict_rows.append(line)
                elif len(line) <= self.LOOSE_LINE_MAX and self.CHAPTER_LOOSE_RE.match(line):
                    loose_idx.append(i)
                    loose_rows.append(line)
                if len(strict_idx) + len(loose_idx) >= 3000:
                    break  # 防御：超级长篇/正则误判爆炸时封顶
            all_idx = sorted(strict_idx + loose_idx)
            total = len(all_idx)
            # 相邻命中行的间隔中位数：真章节至少隔几行；密集编号列表会远小于阈值
            if total >= 2:
                gaps = sorted(all_idx[i] - all_idx[i - 1] for i in range(1, total))
                med_gap = gaps[len(gaps) // 2]
            else:
                med_gap = 0
            if total >= self.LOOSE_MIN_HITS and med_gap >= self.LOOSE_MIN_GAP:
                take = dict.fromkeys(all_idx)          # 合并去重、保序
                loose_map = dict(zip(loose_idx, loose_rows))
                strict_map = dict(zip(strict_idx, strict_rows))
                # 重新按行号算偏移
                offset = 0
                lineno = 0
                for line in self.content.split('\n'):
                    if lineno in take:
                        title = strict_map.get(lineno) or loose_map.get(lineno) or line
                        chapters.append({'title': title, 'offset': offset})
                    offset += len(line.encode('utf-16-le')) // 2 + 1
                    lineno += 1
                    if len(chapters) >= 3000:
                        break
            elif len(strict_idx) >= self.LOOSE_MIN_HITS:
                chapters = [{'title': t, 'offset': o}
                            for t, o in zip(strict_rows, self._line_offsets(strict_idx))]
        if not chapters:
            chapters = self._segment_chapters(500)
        self.chapters = chapters

    def _line_offsets(self, linenos):
        """给定命中行号列表，返回各行起始的 UTF-16 字符偏移。"""
        offsets = []
        want = set(linenos)
        offset = 0
        for i, line in enumerate(self.content.split('\n')):
            if i in want:
                offsets.append(offset)
            offset += len(line.encode('utf-16-le')) // 2 + 1
        return offsets

    def _segment_chapters(self, seg_lines):
        """无章节标题可识别时：按固定行数切段，段首行做标题预览。"""
        chapters = []
        lines = self.content.split('\n')
        starts = []
        offset = 0
        for line in lines:  # 预计算每行起始偏移（UTF-16 码元）
            starts.append(offset)
            offset += len(line.encode('utf-16-le')) // 2 + 1
        for i in range(0, len(lines), seg_lines):
            chunk = lines[i:i + seg_lines]
            chapters.append({
                'title': '第%d段（行%d-%d）· %s' % (
                    len(chapters) + 1, i + 1, i + len(chunk), chunk[0][:16]),
                'offset': starts[i],
            })
            if len(chapters) >= 3000:
                break
        return chapters

    def get_chapters(self):
        """目录面板数据：[{title, offset}]，offset 为全书 UTF-16 字符偏移"""
        return {'chapters': self.chapters, 'count': len(self.chapters)}

    def open_toc(self):
        """打开目录：像设置面板一样临时撑大窗口（阅读窗可能只有一行高，
        悬浮目录根本放不下），返回章节列表。"""
        self.sense.suspend()  # 目录窗口打开期间暂停鼠标感应隐身
        win = self._window
        if self._reader_size is None:
            self._reader_size = (win.x, win.y, win.width, win.height)
        w, h = self.SETTINGS_SIZE
        left, top, right, bottom = self._work_area()
        x = max(left, min(win.x, right - w))
        y = max(top, min(win.y, bottom - h))
        try:
            win.resize(w, h)
            win.move(x, y)
        except Exception:
            pass  # 撑不动也不影响：Esc/点空白仍可退出目录
        return {'chapters': self.chapters, 'count': len(self.chapters)}

    def close_toc(self):
        """关闭目录：恢复阅读窗口原尺寸与位置"""
        self.sense.resume()
        if self._reader_size is not None:
            x, y, w, h = self._reader_size
            try:
                self._window.resize(w, h)
                self._window.move(x, y)
            except Exception:
                pass
            self._reader_size = None

    SETTINGS_SIZE = (420, 660)

    @staticmethod
    def _work_area():
        """屏幕工作区（排除任务栏）。取不到时逐级退回：主屏尺寸 → 保守默认值。"""
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
        try:
            import ctypes
            sm = ctypes.windll.user32.GetSystemMetrics
            return 0, 0, sm(0), sm(1)
        except Exception:
            return 0, 0, 1920, 1080

    def open_settings(self):
        self.sense.suspend()  # 设置窗口打开期间暂停鼠标感应隐身
        win = self._window
        if self._reader_size is None:
            # 记录阅读时的位置和尺寸，关闭设置后原样恢复
            self._reader_size = (win.x, win.y, win.width, win.height)
        w, h = self.SETTINGS_SIZE
        left, top, right, bottom = self._work_area()
        # 把拉大后的设置窗口平移到工作区内，避免贴边时按钮被顶出屏幕
        x = max(left, min(win.x, right - w))
        y = max(top, min(win.y, bottom - h))
        try:
            win.resize(w, h)
            win.move(x, y)
        except Exception:
            pass  # 拖不动也不影响：Esc/点空白仍可退出设置
        return self.config

    def close_settings(self):
        self.sense.resume()
        if self._reader_size is not None:
            x, y, w, h = self._reader_size
            try:
                self._window.resize(w, h)
                self._window.move(x, y)
            except Exception:
                pass
            self._reader_size = None

    def sense_toggle(self):
        """Ctrl+H 兜底开关：运行时切换鼠标感应模式（不写配置文件）"""
        return self.sense.toggle()

    # ---------- 自研窗口拖动（pointer 事件链） ----------
    # 背景：pywebview 的 easy_drag 只监听 mousedown/mousemove 且不做指针捕获，
    # 在触摸屏一体机（合成鼠标事件不连续）和快速拖动（光标跑出小窗口导致
    # mousemove 断流）场景下会"拖不动"。改为 JS 侧 pointer 事件 + setPointerCapture，
    # 鼠标/触摸/触控笔统一走本链路，Python 侧用锚点式 SetWindowPos 移动。

    @staticmethod
    def _drag_scale(hwnd):
        """窗口 DPI 缩放系数（JS screenX 是 DIP，win32 坐标是物理像素）"""
        try:
            import ctypes
            dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
            if dpi and dpi >= 96:
                return dpi / 96.0
        except Exception:
            pass
        return 1.0

    def drag_begin(self, screen_x, screen_y):
        """pointerdown：记录窗口当前原点与指针屏幕坐标作为拖动锚点"""
        try:
            import ctypes
            from ctypes import wintypes
            win = self._window
            if win is None:
                return False
            hwnd = win.native.Handle.ToInt64()
            rect = wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return False
            self._drag_hwnd = hwnd
            self._drag_anchor = (rect.left, rect.top,
                                 float(screen_x), float(screen_y),
                                 self._drag_scale(hwnd))
            return True
        except Exception:
            return False

    def drag_move(self, screen_x, screen_y):
        """pointermove：按锚点把窗口挪到目标位置。
        每次调用经 js_api 各起一个线程，故用非阻塞锁丢帧——锚点式计算丢帧无损。"""
        anchor = self._drag_anchor
        if anchor is None or self._drag_hwnd is None:
            return False
        if not self._drag_lock.acquire(False):
            return False  # 上一帧还在搬，跳过本帧
        try:
            import ctypes
            win_left, win_top, ax, ay, scale = anchor
            x = int(win_left + (float(screen_x) - ax) * scale)
            y = int(win_top + (float(screen_y) - ay) * scale)
            SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
            ctypes.windll.user32.SetWindowPos(
                self._drag_hwnd, None, x, y, None, None,
                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            return True
        except Exception:
            return False
        finally:
            self._drag_lock.release()

    def drag_end(self):
        """pointerup / pointercancel：结束拖动"""
        self._drag_anchor = None
        return True

    def apply_settings(self, width, height, speed, mouse_sense=None,
                       font_size=None, text_color=None, text_opacity=None,
                       progress_bar=None):
        try:
            width, height, speed = int(width), int(height), int(speed)
            if not (150 <= width <= 1200 and 20 <= height <= 600 and 10 <= speed <= 200):
                raise ValueError('设置超出允许范围')
        except (TypeError, ValueError, OverflowError):
            return {'success': False, 'message': '宽度须为 150–1200，高度须为 20–600，速度须为 10–200。'}

        # 文字样式：未传参时保持现值（兼容旧调用方）
        if font_size is None:
            font_size = self.config.get('font_size', 14)
        if text_color is None:
            text_color = self.config.get('text_color', '#333333')
        if text_opacity is None:
            text_opacity = self.config.get('text_opacity', 100)
        try:
            font_size, text_opacity = int(font_size), int(text_opacity)
            if not (10 <= font_size <= 48):
                raise ValueError('字号')
            if not (20 <= text_opacity <= 100):
                raise ValueError('透明度')
            if not (isinstance(text_color, str)
                    and re.fullmatch(r'#[0-9a-fA-F]{6}', text_color)):
                raise ValueError('颜色')
        except (TypeError, ValueError, OverflowError):
            return {'success': False, 'message': '字号须为 10–48，不透明度须为 20–100，颜色须为 #RRGGBB。'}

        config = {**self.config,
                  'window': {**self.config['window'], 'width': width, 'height': height},
                  'speed': speed,
                  'font_size': font_size,
                  'text_color': text_color,
                  'text_opacity': text_opacity}
        if mouse_sense is not None:
            config['mouse_sense'] = bool(mouse_sense)
        if progress_bar is not None:
            config['progress_bar'] = bool(progress_bar)
        # 翻页模式没有设置面板表单入口，必须显式保留，否则保存一次设置就丢
        config['auto_mode'] = bool(self.config.get('auto_mode', True))
        try:
            self.config_file.write_text(json.dumps(config, indent=4, ensure_ascii=False), encoding='utf-8')
        except OSError as error:
            return {'success': False, 'message': f'保存失败：{error}'}
        self.config = config
        if self._reader_size is not None:
            # 设置面板开着时保存了新尺寸：更新待恢复的阅读窗口尺寸（位置不变）
            self._reader_size = (*self._reader_size[:2], width, height)
        if mouse_sense is not None and bool(mouse_sense) != self.sense.enabled:
            self.sense.set_enabled(bool(mouse_sense))
        # 文字样式立即生效
        if self._window is not None:
            try:
                self._window.evaluate_js(
                    f'applyFontStyle({font_size}, {json.dumps(text_color)}, {text_opacity})')
            except Exception:
                pass
        return {'success': True, 'config': config}

    def set_auto_mode(self, enabled):
        """持久化翻页模式（自动/手动）——toggleMode 切换时调用，下次打开书恢复"""
        try:
            self.config['auto_mode'] = bool(enabled)
            self.config_file.write_text(json.dumps(self.config, indent=4, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass   # 落盘失败不阻断切换，下次打开退回默认
        return {'success': True}

    @staticmethod
    def _decode_score(s):
        """给解码结果打分：常用字符（中文/中文标点/可打印ASCII）占比越高越好"""
        if not s:
            return 0.0
        good = 0
        for ch in s:
            o = ord(ch)
            if (0x4E00 <= o <= 0x9FFF      # CJK 统一表意文字
                    or 0x3000 <= o <= 0x303F  # 中文标点
                    or 0xFF00 <= o <= 0xFFEF  # 全角字符
                    or 0x20 <= o <= 0x7E      # 可打印 ASCII
                    or ch in '\n\r\t'):
                good += 1
        return good / len(s)

    def load_txt(self, file_path):
        """加载TXT文件，自动检测编码（BOM优先，支持UTF-16/UTF-8/GB18030）。
        任何编码问题都不会抛异常：最坏显示替换字符或乱码，而不是打不开。"""
        with open(file_path, 'rb') as f:
            raw = f.read()

        # UTF-16 要求偶数字节；文件被截断多出 1 字节时先去掉
        utf16_raw = raw[:-1] if len(raw) % 2 else raw

        # BOM 信息（有 BOM 的文件优先按 BOM 编码严格解码）
        bom_enc, bom_data = None, None
        if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
            bom_enc, bom_data = 'utf-16', utf16_raw
        elif raw.startswith(b'\xef\xbb\xbf'):
            bom_enc, bom_data = 'utf-8-sig', raw

        content = None
        # 1. BOM 严格解码
        if bom_enc:
            try:
                content = bom_data.decode(bom_enc)
            except UnicodeDecodeError:
                content = None

        # 2. UTF-8 严格解码（无 BOM 或 BOM 解码失败时）
        if content is None:
            try:
                content = raw.decode('utf-8')
            except UnicodeDecodeError:
                # 3. 竞争打分：GB18030 / UTF-16LE / UTF-16BE 谁解出来更"像中文"用谁
                best = None
                for enc, data in (('gb18030', raw), ('utf-16-le', utf16_raw), ('utf-16-be', utf16_raw)):
                    try:
                        text = data.decode(enc)
                    except UnicodeDecodeError:
                        continue
                    score = self._decode_score(text)
                    if best is None or score > best[0]:
                        best = (score, text)
                if best is not None and best[0] > 0.6:
                    content = best[1]

        # 4. 最终兜底（保证不抛异常）：有 BOM 就替换坏字符解码，否则忽略错误解码
        if content is None:
            try:
                content = bom_data.decode(bom_enc, errors='replace') if bom_enc else raw.decode('utf-8', errors='ignore')
            except (UnicodeDecodeError, ValueError):
                content = raw.decode('utf-8', errors='ignore')

        self.content = content

        self.content = '\n'.join(line.strip() for line in self.content.split('\n') if line.strip())
        self.current_file = file_path
        self._scan_chapters()
        return True

    def load_epub(self, file_path):
        """加载EPUB文件：按 spine（阅读顺序）拼接正文，并解析自带目录
        （toc.ncx / nav.xhtml）。旧实现用 get_items() 的 manifest 顺序拼文本，
        既可能乱序又丢掉了 epub 自带的目录层级，均已修正。"""
        try:
            book = epub.read_epub(file_path)

            # 1) 按 spine 顺序取正文文档
            docs = []
            for spine_item in book.spine:
                idref = spine_item[0] if isinstance(spine_item, (tuple, list)) else spine_item
                item = book.get_item_with_id(idref)
                if item is not None and item.get_type() == ebooklib.ITEM_DOCUMENT:
                    docs.append(BeautifulSoup(item.get_content(), 'html.parser'))
            if not docs:  # 怪书没有 spine，回退 manifest 顺序
                docs = [BeautifulSoup(it.get_content(), 'html.parser')
                        for it in book.get_items() if it.get_type() == ebooklib.ITEM_DOCUMENT]

            # 2) 拼全文，记录每篇文档起始的 UTF-16 字符偏移
            parts = []
            doc_starts = []
            offset = 0
            for soup in docs:
                text = '\n'.join(line.strip() for line in soup.get_text().split('\n') if line.strip())
                doc_starts.append(offset)
                parts.append(text)
                offset += len(text.encode('utf-16-le')) // 2 + 1
            self.content = '\n'.join(parts)
            self.current_file = file_path

            # 3) 目录：epub 自带目录优先；认不出再退回正则/分段
            self.chapters = self._epub_toc_chapters(book, docs, doc_starts)
            if not self.chapters:
                self._scan_chapters()
            return True
        except Exception:
            return False

    @staticmethod
    def _href_basename(href):
        """取链接目标里的文件名（去 fragment、去目录路径、统一小写）。"""
        if not href:
            return ''
        return href.split('#')[0].split('/')[-1].strip().lower()

    def _epub_toc_chapters(self, book, docs, doc_starts):
        """把 epub 自带目录（book.toc，Section/Link 树）映射成
        [{title, offset}]。Link 按目标文件匹配到 spine 文档的起始偏移；
        Section 只当层级缩进前缀。一篇文章一章的常见结构粒度足够。"""
        # 文件名 -> spine 文档序号（docs 是 soup 没带 item 引用，从 book 侧重建）
        name_to_index = {}
        doc_i = 0
        for spine_item in book.spine:
            idref = spine_item[0] if isinstance(spine_item, (tuple, list)) else spine_item
            item = book.get_item_with_id(idref)
            if item is not None and item.get_type() == ebooklib.ITEM_DOCUMENT:
                name_to_index[self._href_basename(item.get_name())] = doc_i
                doc_i += 1

        chapters = []

        def walk(entries, depth):
            for entry in entries or []:
                if isinstance(entry, epub.Section):
                    title = (entry.title or '').strip()
                    if title and len(chapters) < 3000:
                        chapters.append({'title': '　' * depth + title, 'offset': None})
                    walk(getattr(entry, 'children', None) or [], depth + 1)
                elif isinstance(entry, epub.Link):
                    title = (entry.title or '').strip()
                    if not title:
                        continue
                    doc_idx = name_to_index.get(self._href_basename(entry.href))
                    if doc_idx is None:
                        continue  # 指向非正文资源（样式表等），丢弃
                    if len(chapters) >= 3000:
                        break
                    chapters.append({'title': '　' * depth + title,
                                     'offset': doc_starts[doc_idx]})
                elif isinstance(entry, (list, tuple)):
                    walk(entry, depth)

        try:
            walk(book.toc, 0)
        except Exception:
            return []
        # Section 条目 offset 还是 None：用它后面第一个有 offset 的条目补齐，
        # 末尾没有的用全书末尾。这样点卷名也能跳到对应卷开头。
        end_off = len(self.content.encode('utf-16-le')) // 2
        next_off = end_off
        for i in range(len(chapters) - 1, -1, -1):
            if chapters[i]['offset'] is None:
                chapters[i]['offset'] = next_off
            else:
                next_off = chapters[i]['offset']
        return chapters

    def open_file(self):
        """打开文件对话框"""
        # 默认筛选：txt+epub 一起显示（ epub 用户不用再手动切筛选 ）
        file_types = ('Books (*.txt;*.epub)', 'Text Files (*.txt)', 'EPUB Files (*.epub)', 'All Files (*.*)')
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)

        if result and len(result) > 0:
            file_path = result[0]
            ext = Path(file_path).suffix.lower()

            if ext == '.txt':
                if self.load_txt(file_path):
                    saved_position = self.get_progress(file_path)
                    return {'success': True, 'content': self.content, 'filename': Path(file_path).name, 'filepath': file_path, 'position': saved_position, 'auto_mode': bool(self.config.get('auto_mode', True))}
            elif ext == '.epub':
                if self.load_epub(file_path):
                    saved_position = self.get_progress(file_path)
                    return {'success': True, 'content': self.content, 'filename': Path(file_path).name, 'filepath': file_path, 'position': saved_position, 'auto_mode': bool(self.config.get('auto_mode', True))}

            return {'success': False, 'error': '不支持的文件格式'}

        return {'success': False, 'error': '未选择文件'}




# ---------------------------------------------------------------------------
# Dependency self-check: auto-install WebView2 / .NET if missing
# ---------------------------------------------------------------------------

def _is_webview2_installed():
    """Check if WebView2 runtime is installed via Windows registry.

    Microsoft has used multiple GUIDs for WebView2 over time.
    We check all known ones + fall back to checking the DLL path.
    """
    # Known WebView2 Runtime GUIDs (varies by installer version/channel)
    WEBVIEW2_GUIDS = [
        '{F3017226-FE2A-4295-8BEB-3A2F0F6B5A7B}',  # Early Evergreen Standalone
        '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',  # Current Evergreen Standalone
    ]
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for wow64 in ('', 'WOW6432Node\\'):
                for guid in WEBVIEW2_GUIDS:
                    try:
                        key = winreg.OpenKey(
                            root,
                            rf'SOFTWARE\{wow64}Microsoft\EdgeUpdate\Clients\{guid}',
                        )
                        winreg.CloseKey(key)
                        return True
                    except (FileNotFoundError, OSError):
                        continue
    except ImportError:
        pass

    # Fallback: check if the EmbeddedFixedVersion DLL exists
    import glob
    dll_patterns = [
        os.path.expandvars(r'%ProgramFiles(x86)%\Microsoft\EdgeWebView\Application\*\EmbeddedFixedVersion.dll'),
        os.path.expandvars(r'%ProgramFiles%\Microsoft\EdgeWebView\Application\*\EmbeddedFixedVersion.dll'),
        os.path.expandvars(r'%LocalAppData%\Microsoft\EdgeWebView\Application\*\EmbeddedFixedVersion.dll'),
    ]
    for pattern in dll_patterns:
        if glob.glob(pattern):
            return True

    return False


def _is_dotnet8_desktop_installed():
    """Check if .NET 8 Desktop Runtime is installed (optional, for transparency)."""
    try:
        result = subprocess.run(
            ['dotnet', '--list-runtimes'],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        return 'Microsoft.WindowsDesktop.App 8.' in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _get_exe_dir():
    """Get directory of the running exe or script."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _msg_box(text, title='摸鱼阅读器', icon=0x40):
    """Show a Windows message box. icon: 0x10=error 0x30=warn 0x40=info 0x20=question"""
    import ctypes as _ct
    _ct.windll.user32.MessageBoxW(0, text, title, icon)


def _run_installer_elevated(installer_path):
    """Run an installer with UAC elevation via PowerShell. Returns True on success."""
    try:
        # PowerShell Start-Process -Verb RunAs handles UAC; -Wait blocks until done
        cmd = (
            f'powershell -ExecutionPolicy Bypass -Command '
            f'"Start-Process -FilePath \'{installer_path}\' -Verb RunAs -Wait"'
        )
        subprocess.run(
            cmd, shell=True, timeout=180,
            creationflags=0x08000000,  # CREATE_NO_WINDOW — hide PS console flash
        )
        return True
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def ensure_dependencies():
    """Check and auto-install missing dependencies. Returns True if OK to proceed."""
    import ctypes as _ct

    # --- WebView2 (required) ---
    if not _is_webview2_installed():
        exe_dir = _get_exe_dir()
        local_installer = os.path.join(exe_dir, 'MicrosoftEdgeWebview2Setup.exe')

        if os.path.exists(local_installer):
            installer = local_installer
        else:
            # No local installer — ask to download from Microsoft
            result = _ct.windll.user32.MessageBoxW(
                0,
                '摸鱼阅读器需要 WebView2 运行时才能运行。\n\n'
                '点击「确定」自动下载安装（约 2MB，需要网络）\n'
                '点击「取消」退出程序',
                '摸鱼阅读器',
                0x31,  # MB_OKCANCEL | MB_ICONQUESTION
            )
            if result != 1:  # not IDOK
                return False

            try:
                installer = os.path.join(
                    tempfile.gettempdir(), 'MicrosoftEdgeWebview2Setup.exe'
                )
                urllib.request.urlretrieve(
                    'https://go.microsoft.com/fwlink/p/?LinkId=2124703',
                    installer,
                )
            except Exception as e:
                _msg_box(
                    f'下载失败：{e}\n\n请手动安装 WebView2 后重试。',
                    icon=0x10,
                )
                return False

        # Run installer (with UAC elevation if needed)
        _run_installer_elevated(installer)

        # Verify installation
        if not _is_webview2_installed():
            _msg_box(
                'WebView2 安装似乎未成功。\n'
                '阅读器仍将尝试启动，但可能无法正常工作。',
                icon=0x30,  # MB_ICONWARNING
            )

    # --- .NET 8 Desktop Runtime (optional — only for transparency) ---
    if not _is_dotnet8_desktop_installed():
        # Already handled gracefully by enable_windows_transparency's try/except.
        # Just leave a quiet note; no blocking dialog.
        print('[摸鱼阅读器] .NET 8 Desktop Runtime 未安装，透明背景不可用（不影响阅读）')

    return True


def enable_windows_transparency(window):
    """Keep the WinForms host transparent when WebView2 resizes or restores.
    Requires pythonnet + .NET Desktop Runtime. Falls back gracefully if unavailable."""
    if sys.platform != 'win32' or webview.renderer != 'edgechromium':
        return

    try:
        import ctypes
        from ctypes import wintypes
        import clr
        clr.AddReference('System.Drawing')
        from System.Drawing import Color

        class Margins(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int) for name in ('left', 'right', 'top', 'bottom')]

        extend_frame = ctypes.WinDLL('dwmapi').DwmExtendFrameIntoClientArea
        extend_frame.argtypes = [wintypes.HWND, ctypes.POINTER(Margins)]
        extend_frame.restype = ctypes.c_long

        # Win11 深色模式下 DWM 会把玻璃区渲染成不透明深色（浅色模式则正常透明）。
        # 双保险，须在扩展玻璃区之前设置：
        # - 属性 20 (DWMWA_USE_IMMERSIVE_DARK_MODE) = FALSE：把窗口钉在浅色框架渲染
        # - 属性 38 (DWMWA_SYSTEMBACKDROP_TYPE) = 1 (DWMSBT_NONE)：禁用 Mica 等系统材质
        #   （Mica 本身不透明，深色主题下就是一层黑幕）
        # Win10 不认识这些属性，返回错误码但不抛异常，静默忽略即可，不影响现有行为。
        set_attr = ctypes.WinDLL('dwmapi').DwmSetWindowAttribute
        set_attr.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        set_attr.restype = ctypes.c_long
        _dark_off = wintypes.BOOL(0)
        _backdrop_none = wintypes.INT(1)
        _hwnd = window.native.Handle.ToInt64()
        set_attr(_hwnd, 20, ctypes.byref(_dark_off), ctypes.sizeof(_dark_off))
        set_attr(_hwnd, 38, ctypes.byref(_backdrop_none), ctypes.sizeof(_backdrop_none))

        # Negative margins cover the entire client area, including future resizes.
        # A black host supplies zero-alpha pixels to DWM; WebView2 still draws text
        # and opaque controls normally. This is not a color-key transparency mask.
        margins = Margins(-1, -1, -1, -1)
        result = extend_frame(window.native.Handle.ToInt64(), ctypes.byref(margins))
        if result < 0:
            raise OSError(f'DwmExtendFrameIntoClientArea failed: 0x{result & 0xffffffff:08X}')
        window.native.BackColor = Color.Black
    except (ImportError, OSError, Exception) as e:
        # pythonnet / .NET Desktop Runtime not available — transparency disabled,
        # but the reader still works perfectly without it.
        print(f'[摸鱼阅读器] 透明背景未启用: {e}')
        print('[摸鱼阅读器] 提示: 安装 .NET Desktop Runtime 可启用透明背景效果')


class MouseSenseController:
    """鼠标感应模式：鼠标在窗口内 = 正常显示；离开超过 0.5 秒 = 窗口淡出 + 暂停滚动 + 点击穿透。

    实现要点：
    - 后台线程轮询全局鼠标坐标（GetCursorPos）与窗口矩形（GetWindowRect），
      不依赖窗口自身接收鼠标事件，因此隐身（点击穿透）状态下仍能感知鼠标回来。
    - 隐藏用"视觉隐身"（JS 淡出 + WS_EX_TRANSPARENT 点击穿透）而非 window.hide()，
      避免窗口消失后无法再触发的死锁。
    - 恢复滚动带 1 秒缓冲，防止鼠标路过窗口导致误触发。
    """

    POLL_INTERVAL = 0.2
    HIDE_DELAY = 0.5
    RESUME_DELAY = 1.0

    def __init__(self, reader):
        self.reader = reader
        self._window = None
        self._hwnd = None
        self._enabled = False
        self._suspended = False
        self._stop = threading.Event()
        self._thread = None

    @property
    def enabled(self):
        return self._enabled

    def attach(self, window):
        """窗口 shown 后（GUI 线程）调用，缓存原生句柄供 win32 调用使用"""
        self._window = window
        try:
            self._hwnd = window.native.Handle.ToInt64()
        except Exception:
            self._hwnd = None

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self._enabled:
            if not enabled:
                self._force_visible()
            return
        if enabled:
            self._enabled = True
            self._suspended = False
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name='moyu-mouse-sense', daemon=True)
            self._thread.start()
        else:
            self._enabled = False
            self._suspended = False
            self._stop.set()
            t = self._thread
            self._thread = None
            if t is not None and t is not threading.current_thread():
                t.join(timeout=2)
            self._force_visible()

    def suspend(self):
        """设置窗口打开等场景：强制可见并暂停隐身判定"""
        if not self._enabled:
            return
        self._suspended = True
        self._force_visible()

    def resume(self):
        self._suspended = False

    def toggle(self):
        self.set_enabled(not self._enabled)
        return self._enabled

    def _force_visible(self):
        self._set_click_through(False)
        self._eval_js('moyuSenseShow()')

    def _eval_js(self, code):
        try:
            if self._window is not None:
                self._window.evaluate_js(code)
        except Exception:
            pass  # 窗口关闭等竞态下静默失败

    def _set_click_through(self, on):
        """给窗口加/去 WS_EX_TRANSPARENT：开启后鼠标点击穿到下层窗口"""
        if sys.platform != 'win32' or not self._hwnd:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            style = user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
            if on:
                style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                style &= ~WS_EX_TRANSPARENT  # LAYERED 保留（透明背景依赖）
            user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _loop(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        pt = wintypes.POINT()
        rect = wintypes.RECT()
        hidden = False
        out_since = None
        resume_at = None
        while not self._stop.wait(self.POLL_INTERVAL):
            try:
                if self._suspended or not self._hwnd:
                    if hidden:
                        self._force_visible()
                        hidden = False
                    out_since = None
                    resume_at = None
                    continue
                if not user32.GetCursorPos(ctypes.byref(pt)):
                    continue
                if not user32.GetWindowRect(self._hwnd, ctypes.byref(rect)):
                    continue
                inside = rect.left <= pt.x < rect.right and rect.top <= pt.y < rect.bottom
                now = time.time()
                if inside:
                    out_since = None
                    if hidden:
                        # 鼠标回来了：先关穿透再淡入，滚动等缓冲后恢复
                        self._set_click_through(False)
                        self._eval_js('moyuSenseShow()')
                        hidden = False
                        resume_at = now + self.RESUME_DELAY
                    elif resume_at is not None and now >= resume_at:
                        self._eval_js('moyuSenseResume()')
                        resume_at = None
                else:
                    resume_at = None
                    if out_since is None:
                        out_since = now
                    elif not hidden and (now - out_since) >= self.HIDE_DELAY:
                        # 离开超过宽限期：JS 淡出+暂停，再开点击穿透
                        self._eval_js('moyuSenseHide()')
                        self._set_click_through(True)
                        hidden = True
            except Exception:
                continue  # 单次轮询异常不终止线程


def get_html():
    """返回HTML内容"""
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: "Microsoft YaHei", sans-serif;
            font-size: 14px;
            line-height: 1.6;
            color: #333;
            overflow: hidden;
            -webkit-app-region: drag;
            user-select: none;
            background: transparent;
            touch-action: none; /* 触摸拖窗口不被浏览器滚动手势截胡（截胡会发 pointercancel） */
        }

        #container {
            height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 4px 8px;
            transition: opacity 0.4s;
        }

        /* 鼠标感应模式：隐身时整体淡出，面板和模式指示完全消失 */
        body.sense-hidden #container { opacity: 0; }
        body.sense-hidden #controls { display: none !important; }
        body.sense-hidden #mode-indicator { display: none; }

        #text-display {
            flex: 1;
            overflow: hidden;
            position: relative;
            cursor: pointer;
            -webkit-app-region: no-drag;
        }

        #text-content {
            white-space: pre-wrap;
            word-break: break-all;
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            transition: transform 0.1s linear;
        }

        /* --- 底部进度条（默认关闭，body.progress-bar-on 时显示） --- */
        #progress-bar {
            display: none;               /* 默认隐匿；开关打开后由 body 类翻转为 flex */
            height: 3px;
            flex-shrink: 0;
            background: rgba(180, 180, 180, 0.2);
            cursor: pointer;
            -webkit-app-region: no-drag;
            position: relative;
        }
        body.progress-bar-on #progress-bar { display: flex; }
        #progress-fill {
            height: 100%;
            width: 0%;
            background: rgba(76, 175, 80, 0.5);
            pointer-events: none;
        }

        /* --- v3.0: 迷你搜索条（Ctrl+F）与目录面板（Ctrl+T，复用设置撑窗机制） --- */
        #search-bar {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 96px;             /* 右上角给控件面板留地盘 */
            z-index: 1500;
            padding: 3px 6px;
            background: rgba(247, 247, 248, 0.95);
            border: 1px solid #ccc;
            border-top: none;
            border-radius: 0 0 6px 6px;
            font-size: 12px;
            -webkit-app-region: no-drag;
            align-items: center;
            gap: 6px;
        }
        #search-bar.open { display: flex; }
        #search-input {
            flex: 1;
            min-width: 36px;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 2px 6px;
            font-size: 12px;
            user-select: text;
        }
        #search-count { color: #888; font-size: 11px; white-space: nowrap; }
        #search-bar button { margin: 0; padding: 1px 8px; font-size: 11px; }

        /* 目录：全屏覆盖式面板（窗口已由 Python 侧撑大到设置尺寸），
           版式向设置面板看齐：浅灰底 + 居中白卡 */
        #toc-panel {
            position: fixed;
            inset: 0;
            z-index: 2000;
            overflow: auto;
            padding: 12px;
            background: #f7f7f8;
            color: #333;
            -webkit-app-region: no-drag;
        }
        #toc-panel[hidden] { display: none; }
        body.toc-open #container { visibility: hidden; }
        body.toc-open #controls { display: none; }
        #toc-card {
            max-width: 380px;
            margin: 0 auto;
            padding: 14px 16px;
            background: white;
            border: 1px solid #e3e3e6;
            border-radius: 8px;
            box-shadow: 0 4px 14px rgba(0,0,0,0.08);
        }
        #toc-card h1 { font-size: 16px; margin: 0 0 6px; }
        #toc-count { color: #888; font-size: 12px; font-weight: normal; margin-left: 6px; }
        #toc-close { float: right; }
        #toc-list { margin-top: 8px; }
        .toc-item {
            padding: 4px 8px;
            cursor: pointer;
            border-radius: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .toc-item:hover { background: #e8f0e8; color: #2c6e2f; }
        .toc-empty { padding: 10px 2px; color: #888; }
        /* 隐身/设置状态下把交互面板一并藏起来 */
        body.sense-hidden #search-bar { display: none !important; }
        body.settings-open #search-bar { display: none !important; }

        #controls {
            position: fixed;
            top: 0;
            right: 0;
            padding: 4px;
            background: transparent;
            border-radius: 4px;
            font-size: 12px;
            -webkit-app-region: no-drag;
            z-index: 1000;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.5s;
        }

        #controls.show {
            opacity: 1;
            pointer-events: auto;
        }

        #controls button {
            background: transparent;
            color: #333;
            border: none;
        }

        #controls button:hover {
            background: transparent;
            color: #000;
            text-decoration: underline;
        }

        #controls button.active {
            background: transparent;
            color: #388E3C;
            border: none;
            font-weight: bold;
        }

        #controls label {
            color: #333;
        }

        #controls input[type="range"] {
            accent-color: #888;
        }

        #mode-indicator {
            position: fixed;
            top: 4px;
            left: 4px;
            padding: 3px 8px;
            background: rgba(100, 100, 100, 0.7);
            color: white;
            border-radius: 4px;
            font-size: 10px;
            -webkit-app-region: no-drag;
            z-index: 999;
            opacity: 0;
            transition: opacity 0.3s;
        }

        #mode-indicator.show {
            opacity: 1;
        }

        button {
            margin: 0 2px;
            padding: 2px 6px;
            font-size: 11px;
            cursor: pointer;
            border: 1px solid #ccc;
            background: white;
            border-radius: 3px;
        }

        button:hover {
            background: #f0f0f0;
        }

        button.active {
            background: #4CAF50;
            color: white;
            border-color: #4CAF50;
        }

        #speed-control {
            margin-top: 4px;
        }

        input[type="range"] {
            width: 100px;
            vertical-align: middle;
        }
    </style>
</head>
<body>
    <div id="container">
        <div id="mode-indicator">自动滚动</div>
        <div id="controls">
            <div>
                <button onclick="openFile()">打开</button>
                <button id="settings-btn" onclick="openSettings()" title="Ctrl+,">设置</button>
                <button onclick="openToc()" title="Ctrl+T">目录</button>
                <button id="mode-btn" onclick="toggleMode()" class="active">自动</button>
                <button id="pause-btn" onclick="togglePause()">暂停</button>
                <button onclick="closeApp()">关闭</button>
            </div>
            <div id="speed-control">
                <label>速度: <span id="speed-value">50</span></label>
                <input type="range" min="10" max="200" value="50" oninput="changeSpeed(this.value)">
            </div>
        </div>
        <div id="text-display" onclick="togglePause()">
            <div id="text-content">右键点击打开电子书...</div>
        </div>
        <div id="progress-bar" onclick="jumpToProgress(event)" title="点击跳转">
            <div id="progress-fill"></div>
        </div>
    </div>

    <!-- v3.0: Ctrl+F 迷你搜索条 -->
    <div id="search-bar">
        <input id="search-input" type="text" placeholder="搜全书，Enter 下一处">
        <span id="search-count">0/0</span>
        <button type="button" onclick="gotoMatch(-1)" title="上一个 (Shift+Enter)">↑</button>
        <button type="button" onclick="gotoMatch(1)" title="下一个 (Enter)">↓</button>
    </div>
    <!-- v3.0: Ctrl+T 目录面板（窗口由 Python 侧撑大后再显示） -->
    <section id="toc-panel" hidden aria-label="目录">
        <div id="toc-card">
            <button type="button" id="toc-close" onclick="closeToc()" title="Esc 关闭">✕ 返回阅读</button>
            <h1>目录<span id="toc-count"></span></h1>
            <div id="toc-list"></div>
        </div>
    </section>

    <script>
        let content = '';
        let currentPosition = 0;
        let isPaused = false;
        let scrollSpeed = 50;
        let lastTimestamp = 0;
        let isAutoMode = true;
        // 行对齐分页：页首永远落在文字行边界上（行高的整数倍），不再维护"固定页高切片"的页数概念。
        // 窗口高度是用户随手调的，几乎不可能是行高整数倍；固定页高切片会把切缝处的一行腰斩成
        // 两半（上一页半行 + 下一页半行），两半都读不出来，效果就是跳过了一行。
        let currentFilePath = '';  // full path for progress tracking
        let currentFile = '';      // short name for display
        let scrollFrame = 0;
        let autoSaveInterval = null;
        // --- 鼠标感应模式状态（由 Python 端 MouseSenseController 驱动） ---
        let senseHidden = false;        // 当前是否处于感应隐身
        let sensePrevPaused = false;    // 隐藏时的暂停状态（恢复依据）
        let senseResumePending = false; // 淡入后是否待自动恢复滚动

        function startScroll() {
            if (!content || isPaused || scrollFrame) return;
            scrollFrame = requestAnimationFrame(scroll);
        }

        function scroll(timestamp) {
            scrollFrame = 0;
            if (!lastTimestamp) lastTimestamp = timestamp;
            const delta = timestamp - lastTimestamp;
            lastTimestamp = timestamp;

            if (!isPaused && content) {
                if (isAutoMode) {
                    currentPosition += (scrollSpeed / 1000) * delta;
                    const textElement = document.getElementById('text-content');
                    textElement.style.transform = `translateY(-${currentPosition}px)`;

                    const displayHeight = document.getElementById('text-display').offsetHeight;
                    const contentHeight = textElement.offsetHeight;

                    if (currentPosition > contentHeight + displayHeight) {
                        currentPosition = -displayHeight;
                    }
                    updateProgressBar();  // 考古版只在翻页时刷新，自动滚动时是根木桩——补上
                }

                scrollFrame = requestAnimationFrame(scroll);
            }
        }

        // 模式 UI 同步（toggleMode 和 openFile 恢复上次模式共用）
        function syncModeUi(showIndicator) {
            const modeBtn = document.getElementById('mode-btn');
            const indicator = document.getElementById('mode-indicator');
            if (isAutoMode) {
                modeBtn.textContent = '自动';
                modeBtn.classList.add('active');
                indicator.textContent = '自动滚动';
            } else {
                modeBtn.textContent = '手动';
                modeBtn.classList.remove('active');
                indicator.textContent = '手动翻页';
            }
            if (showIndicator) {
                indicator.classList.add('show');
                setTimeout(() => indicator.classList.remove('show'), 1500);
            }
        }

        function toggleMode() {
            isAutoMode = !isAutoMode;
            if (!isAutoMode && content) {
                // 切回手动：自动滚动的任意像素位置对齐到行顶再开始翻页
                currentPosition = lineFloor(currentPosition);
                updatePagePosition();
                snapTopToRealRow();
            }
            syncModeUi(true);
            // 持久化模式选择，下次打开书恢复
            pywebview.api.set_auto_mode(isAutoMode).catch(() => {});
        }

        // --- 行对齐分页的工具函数 ---
        function getLineHeight() {
            const el = document.getElementById('text-content');
            const lh = parseFloat(getComputedStyle(el).lineHeight);
            if (lh && lh > 4) return lh;
            // 兜底：极老内核对无单位 line-height 可能返回 "normal"，按 CSS 定义 1.6 倍字号推算
            const fs = parseFloat(getComputedStyle(el).fontSize) || 14;
            return fs * 1.6;
        }
        function viewHeight() {
            return document.getElementById('text-display').offsetHeight;
        }
        function contentHeight() {
            return document.getElementById('text-content').offsetHeight;
        }
        // 把任意 y 回退对齐到行边界（所在行的行首；进度恢复用，最多回退一行，不跳内容）
        function lineFloor(y) {
            const lh = getLineHeight();
            return Math.max(0, Math.floor(y / lh) * lh);
        }
        // v3.0 闭环校准：数学推算的翻页位置随阅读推进会有亚像素级漂移
        // （emoji/生僻字撑高行盒、offsetHeight 取整、22.4px 小数行高…），
        // 累积几十页后首行变半截。这里用 caretRangeFromPoint 实测"视口顶
        // 首行"的真实行顶，把当前位置微调（≤半行）钉回真实行栅格——
        // 误差每页清零，永不累积。实测失败时静默跳过，退化为原算术行为。
        function snapTopToRealRow() {
            const el = document.getElementById('text-content');
            const display = document.getElementById('text-display');
            // 关键：#text-content 有 transition: transform 0.1s——设置位置后
            // 立即量测得到的是过渡起点（旧位置）的布局，全是失真值。
            // 量测期间必须禁用过渡并强制同步布局，量完再恢复。
            const prevTransition = el.style.transition;
            el.style.transition = 'none';
            updatePagePosition();  // 无过渡即时应用当前位置
            try {
                const dispTop = display.getBoundingClientRect().top;
                const cx = Math.floor(display.getBoundingClientRect().width / 2);
                let range = null;
                for (const dy of [1, 3, 6]) {          // 视口顶往下试几个采样点
                    try { range = document.caretRangeFromPoint(cx, dispTop + dy); } catch (err) {}
                    if (range && range.startContainer) break;
                }
                if (!range || !range.startContainer) return;
                // 圈住采样点的字符量行盒（collapsed range 的 rect 在部分内核不可靠）
                let rect = null;
                try {
                    const node = range.startContainer;
                    if (node.nodeType === 3 && range.startOffset < node.length) {
                        // emoji 等星外字符占 2 个 UTF-16 码元：offset 落在代理对
                        // 中间时 Range 量不出 rect，扩到完整字符
                        let end = range.startOffset + 1;
                        const cu = node.data.charCodeAt(range.startOffset);
                        if (cu >= 0xD800 && cu <= 0xDBFF && end < node.length) end++;
                        const r = document.createRange();
                        r.setStart(node, range.startOffset);
                        r.setEnd(node, end);
                        rect = r.getClientRects()[0];
                        if (!rect && end > range.startOffset + 1) {
                            r.setEnd(node, range.startOffset);   // 收缩到起点再试
                            rect = r.getClientRects()[0];
                        }
                    }
                    if (!rect) rect = range.getClientRects()[0];
                } catch (err) {}
                if (!rect) return;
                const rowTop = rect.top - dispTop;     // 首行顶相对视口顶的偏差
                if (!isFinite(rowTop) || Math.abs(rowTop) < 0.5) return;   // 已对齐
                if (Math.abs(rowTop) >= getLineHeight()) return;           // 异常值别动
                if (currentPosition <= 0) return;      // 书顶是坐标原点，不校准
                currentPosition = Math.max(0, currentPosition + rowTop);
                updatePagePosition();
            } finally {
                el.style.transition = prevTransition;
            }
        }

        // --- 进度条 + 统一跳转入口（进度条点击/百分比跳转/目录/搜索都走这里） ---
        function setProgressBarVisible(on) {
            document.body.classList.toggle('progress-bar-on', !!on);
        }
        function updateProgressBar() {
            if (!content) return;
            const maxScroll = Math.max(1, contentHeight() - viewHeight());
            // 自动模式允许越界值（循环滚动时短暂为负/超界），钳到 0–100 显示
            const pct = Math.min(100, Math.max(0, (currentPosition / maxScroll) * 100));
            document.getElementById('progress-fill').style.width = pct + '%';
        }
        function jumpToPosition(pos) {
            if (!content) return;
            currentPosition = Math.max(0, Math.min(pos, Math.max(0, contentHeight() - viewHeight())));
            if (!isAutoMode) {
                currentPosition = lineFloor(currentPosition);  // 手动模式对齐行边界
                updatePagePosition();                          // 先应用，实测才有意义
                snapTopToRealRow();                            // 钉回真实行栅格（估算像素→实测像素）
            }
            updatePagePosition();
            saveProgress();
            updateProgressBar();
        }
        function jumpToProgress(event) {
            if (!content) return;
            const bar = document.getElementById('progress-bar');
            const rect = bar.getBoundingClientRect();
            const pct = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
            const maxScroll = Math.max(0, contentHeight() - viewHeight());
            jumpToPosition(pct * maxScroll);
        }
        // 供设置面板的百分比跳转调用（0–100）
        function jumpToPercent(pct) {
            const maxScroll = Math.max(0, contentHeight() - viewHeight());
            jumpToPosition((pct / 100) * maxScroll);
        }

        // --- v3.0: 字符偏移 → 像素换算（目录/搜索跳转的基建） ---
        // 全文是 #text-content 里唯一一个文本节点；用 Range 量出"前 offset 个字符"
        // 渲染到了哪里，返回相对内容顶部的 y（与 currentPosition 同坐标系）。
        // offset 与 Python 端章节扫描同按 UTF-16 码元计，指哪打哪。
        function charOffsetToY(offset) {
            const el = document.getElementById('text-content');
            const node = el.firstChild;
            if (!node || node.nodeType !== 3 || !node.length) return 0;
            const off = Math.max(0, Math.min(offset | 0, node.length));
            if (off === 0) return 0;
            const range = document.createRange();
            range.setStart(node, 0);
            range.setEnd(node, off);
            const rects = range.getClientRects();
            if (!rects.length) return 0;
            // rects 是 translateY 变换后的视口坐标；减去内容自身顶部当前所在的
            // 视口位置，才得到内容坐标系里的 y（才与 currentPosition 可比）
            const elTop = el.getBoundingClientRect().top;
            return rects[rects.length - 1].bottom - elTop;
        }

        function flashNote(text) {
            const indicator = document.getElementById('mode-indicator');
            indicator.textContent = text;
            indicator.classList.add('show');
            setTimeout(() => indicator.classList.remove('show'), 1500);
        }

        // --- v3.0: Ctrl+F 迷你搜索条 ---
        let searchMatches = [];   // 全部命中处的字符偏移
        let searchIndex = -1;     // 当前命中（-1 = 尚未跳转）
        let searchWasPaused = false;
        let searchToken = 0;      // 输入防抖令牌

        function setSearchBarOpen(on) {
            const bar = document.getElementById('search-bar');
            const input = document.getElementById('search-input');
            if (on) {
                if (bar.classList.contains('open')) { input.focus(); return; }
                closeToc();
                searchWasPaused = isPaused;
                if (!isPaused) togglePause();   // 打字时文字别再滚
                bar.classList.add('open');
                setTimeout(() => input.focus(), 0);
            } else {
                if (!bar.classList.contains('open')) return;
                bar.classList.remove('open');
                input.blur();
                if (!searchWasPaused && isPaused) togglePause();
            }
        }
        function closeSearch() { setSearchBarOpen(false); }

        function runSearch(q) {
            searchMatches = [];
            searchIndex = -1;
            const needle = (q || '').trim();
            if (needle && content) {
                let i = content.indexOf(needle);
                while (i !== -1) {
                    searchMatches.push(i);
                    if (searchMatches.length >= 9999) break;  // 防御：超高频词封顶
                    i = content.indexOf(needle, i + needle.length);
                }
            }
            updateSearchCount();
        }
        function updateSearchCount() {
            const total = searchMatches.length;
            document.getElementById('search-count').textContent =
                total ? ((searchIndex + 1) + '/' + total) : (content ? '0/0' : '无书');
        }
        function gotoMatch(step) {
            const total = searchMatches.length;
            if (!total) return;
            if (searchIndex === -1) {
                // 首跳：从当前阅读位置附近往后找第一个命中，找不到就回卷首
                const approx = Math.floor(
                    (currentPosition / Math.max(1, contentHeight())) * content.length);
                searchIndex = 0;
                while (searchIndex < total && searchMatches[searchIndex] < approx) searchIndex++;
                if (searchIndex >= total) searchIndex = 0;
            } else {
                searchIndex = (searchIndex + step + total) % total;
            }
            // 命中行落在视口顶（摸鱼窗常常只有一两行高，留上下文会把命中顶出屏）
            jumpToPosition(charOffsetToY(searchMatches[searchIndex]) - getLineHeight());
            updateSearchCount();
        }
        document.getElementById('search-input').addEventListener('input', (e) => {
            const token = ++searchToken;
            setTimeout(() => { if (token === searchToken) runSearch(e.target.value); }, 200);
        });
        // 面板内按键不外泄（打字别触发翻页/模式切换），Esc/Enter 由自己处理
        document.getElementById('search-input').addEventListener('keydown', (e) => {
            e.stopPropagation();
            if (e.key === 'Escape') {
                e.preventDefault();
                closeSearch();
            } else if (e.key === 'Enter') {
                e.preventDefault();
                gotoMatch(e.shiftKey ? -1 : 1);
            }
        });

        // --- v3.0: 目录面板（Ctrl+T / 控件面板"目录"按钮；复用设置撑窗机制） ---
        // 阅读窗可能只有一行高，悬浮目录放不下：open_toc 由 Python 侧把窗口
        // 临时撑大到设置尺寸，本面板全屏覆盖其上；close_toc 恢复原窗。
        let tocWasPaused = false;
        let tocBusy = false;

        async function openToc() {
            if (settingsOpen || tocBusy) return;
            if (document.body.classList.contains('toc-open')) { closeToc(); return; }
            if (!content) { flashNote('还没打开电子书'); return; }
            tocBusy = true;
            try {
                closeSearch();
                tocWasPaused = isPaused;
                if (!isPaused) togglePause();
                let data;
                try {
                    data = await pywebview.api.open_toc();
                } catch (err) {
                    data = { chapters: [] };
                }
                buildTocList((data && data.chapters) || []);
                document.getElementById('toc-panel').hidden = false;
                document.body.classList.add('toc-open');
            } finally {
                tocBusy = false;
            }
        }
        async function closeToc() {
            if (!document.body.classList.contains('toc-open')) return;
            document.body.classList.remove('toc-open');
            document.getElementById('toc-panel').hidden = true;
            try { await pywebview.api.close_toc(); } catch (err) {}
            if (!tocWasPaused && isPaused) togglePause();
        }
        function buildTocList(chapters) {
            const list = document.getElementById('toc-list');
            list.textContent = '';
            document.getElementById('toc-count').textContent =
                chapters.length ? '(' + chapters.length + ')' : '';
            if (!chapters.length) {
                const tip = document.createElement('div');
                tip.className = 'toc-empty';
                tip.textContent = '没认出章节标题（认"第X章/节/卷/回、序章、楔子、番外…"）';
                list.appendChild(tip);
                return;
            }
            for (const ch of chapters) {
                const item = document.createElement('div');
                item.className = 'toc-item';
                item.textContent = ch.title;
                item.title = ch.title;
                item.onclick = async () => {
                    // 先关目录恢复阅读窗（行宽变了换行会变），再量像素跳转
                    await closeToc();
                    // 标题行落在视口顶（负值由 jumpToPosition 钳位兜底）
                    jumpToPosition(charOffsetToY(ch.offset) - getLineHeight());
                };
                list.appendChild(item);
            }
        }
        // 点卡片外空白处返回阅读（与设置面板同款逃生口）
        document.getElementById('toc-panel').addEventListener('click', (event) => {
            if (event.target === document.getElementById('toc-panel')) closeToc();
        });

        function togglePause() {
            senseResumePending = false;  // 任何手动/其他入口的暂停切换都取消待恢复
            isPaused = !isPaused;
            const pauseBtn = document.getElementById('pause-btn');
            if (isPaused) {
                cancelAnimationFrame(scrollFrame);
                scrollFrame = 0;
                pauseBtn.textContent = '继续';
            } else {
                pauseBtn.textContent = '暂停';
                lastTimestamp = 0;
                startScroll();
            }
        }

        function pageUp() {
            if (!isAutoMode && content) {
                if (currentPosition <= 0) return;
                const lh = getLineHeight();
                // pageDown(floor) 的镜像逆映射(ceil)：当前首行成为上一页的页尾腰斩行，
                // 再往上翻时它会完整重现——与下翻语义完全对称，来回翻页位置严格可逆
                let target = Math.ceil((currentPosition - viewHeight()) / lh) * lh;
                // 防御：视口不足一行时至少上翻一行
                if (target >= currentPosition) target = currentPosition - lh;
                currentPosition = Math.max(0, target);
                updatePagePosition();
                snapTopToRealRow();   // 闭环校准：必须先应用位置再实测，钉回真实行顶
                saveProgress();
                updateProgressBar();
            }
        }

        function pageDown() {
            if (!isAutoMode && content) {
                const lh = getLineHeight();
                // 下一页起点 = 视口底部所在行的行首（floor）：页尾被截断的行完整重现于下页开头，
                // 任何行都不会被跳过（ceil 会把腰斩行的下半截永远留在屏外，等于跳行）
                let target = Math.floor((currentPosition + viewHeight()) / lh) * lh;
                // 防御：视口不足一行时至少下翻一行
                if (target <= currentPosition) target = currentPosition + lh;
                // 剩余内容本页已显示完（下一页首行不存在）：到底，不再翻
                if (target >= contentHeight()) return;
                currentPosition = target;
                updatePagePosition();
                snapTopToRealRow();   // 闭环校准：必须先应用位置再实测，钉回真实行顶
                saveProgress();
                updateProgressBar();
            }
        }

        function updatePagePosition() {
            const textElement = document.getElementById('text-content');
            textElement.style.transform = `translateY(-${currentPosition}px)`;
        }

        function changeSpeed(value) {
            scrollSpeed = Number(value);
            document.getElementById('speed-value').textContent = value;
            document.querySelector('#speed-control input').value = value;
        }

        function saveProgress() {
            if (currentFilePath && content) {
                pywebview.api.save_progress(currentFilePath, currentPosition);
            }
        }

        // --- Auto-save every 5 seconds ---
        function startAutoSave() {
            if (autoSaveInterval) clearInterval(autoSaveInterval);
            autoSaveInterval = setInterval(() => {
                if (currentFilePath && content) {
                    saveProgress();
                }
            }, 5000);
        }

        function openFile() {
            pywebview.api.open_file().then(result => {
                if (result.success) {
                    content = result.content;
                    currentFile = result.filename;
                    currentFilePath = result.filepath;
                    currentPosition = result.position || 0;
                    // 恢复上次使用的翻页模式（自动/手动），但一律暂停起步——
                    // 不打开就开滚，避免"几秒钟滑走一大段"的狼狈（按空格/点继续才开滚）
                    isAutoMode = (result.auto_mode !== undefined) ? !!result.auto_mode : true;
                    isPaused = true;
                    lastTimestamp = 0;
                    if (scrollFrame) { cancelAnimationFrame(scrollFrame); scrollFrame = 0; }
                    document.getElementById('pause-btn').textContent = '继续';
                    syncModeUi(false);
                    searchMatches = [];    // 换书：搜索命中作废
                    searchIndex = -1;
                    updateSearchCount();
                    closeSearch();
                    closeToc();

                    document.getElementById('text-content').textContent = content;
                    // 手动模式：恢复进度时对齐到行边界——旧版本存的任意像素可能落在行中间，
                    // floor 回退让首行完整重读（最多回退一行，绝不跳内容）；自动模式保持任意像素平滑续滚
                    if (!isAutoMode) {
                        currentPosition = lineFloor(currentPosition);
                    }
                    document.getElementById('text-content').style.transform = `translateY(-${currentPosition}px)`;
                    if (!isAutoMode) {
                        snapTopToRealRow();   // 钉回真实行顶（估算像素→实测像素）
                    }
                    updateProgressBar();

                    startAutoSave();
                } else {
                    alert(result.error || '打开文件失败');
                }
            }).catch(err => alert('打开文件出错：' + err));
        }

        function closeApp() {
            if (autoSaveInterval) clearInterval(autoSaveInterval);
            saveProgress();
            pywebview.api.close();
        }

        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === ',') {
                e.preventDefault();
                openSettings();
                return;
            }
            if (e.ctrlKey && (e.key === 'h' || e.key === 'H')) {
                e.preventDefault();
                pywebview.api.sense_toggle().then(enabled => {
                    flashNote(enabled ? '鼠标感应：开' : '鼠标感应：关');
                }).catch(() => {});
                return;
            }
            if (settingsOpen) {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    closeSettings();
                }
                return;
            }
            // 面板优先级：目录 > 搜索条。开着时 Esc（或再按 Ctrl+T）关闭，
            // 其余全局键（翻页/退出/再开别的面板）不响应
            if (document.body.classList.contains('toc-open')) {
                if (e.key === 'Escape' || (e.ctrlKey && (e.key === 't' || e.key === 'T'))) {
                    e.preventDefault();
                    closeToc();
                }
                return;
            }
            if (document.getElementById('search-bar').classList.contains('open')) {
                if (e.key === 'Escape') { e.preventDefault(); closeSearch(); }
                return;
            }
            // v3.0: Ctrl+F 搜索条 / Ctrl+T 目录
            if (e.ctrlKey && (e.key === 'f' || e.key === 'F')) {
                e.preventDefault();
                setSearchBarOpen(true);
                return;
            }
            if (e.ctrlKey && (e.key === 't' || e.key === 'T')) {
                e.preventDefault();
                openToc();
                return;
            }
            if (e.key === 'Escape') {
                closeApp();
            } else if (e.key === 'm' || e.key === 'M') {
                toggleMode();
            } else if (e.key === 'ArrowUp' || e.key === 'PageUp') {
                e.preventDefault();
                pageUp();
            } else if (e.key === ' ' || e.key === 'Enter') {
                e.preventDefault();
                if (isAutoMode) {
                    // 自动模式：空格=暂停/继续（打开书是暂停起步，空格开滚）
                    togglePause();
                } else {
                    pageDown();
                }
            } else if (e.key.length === 1 && /[a-zA-Z]/.test(e.key)) {
                // Any single letter key = page down (looks like typing!)
                // 'm' for mode toggle still works above, so it won't reach here
                e.preventDefault();
                pageDown();
            } else if (e.key === 'ArrowDown' || e.key === 'PageDown') {
                e.preventDefault();
                pageDown();
            }
        });

        document.getElementById('text-display').addEventListener('contextmenu', (e) => {
            e.preventDefault();
            openFile();
        });

        document.getElementById('text-display').addEventListener('wheel', (e) => {
            if (!isAutoMode && !settingsOpen) {
                e.preventDefault();
                if (e.deltaY < 0) {
                    pageUp();
                } else {
                    pageDown();
                }
            }
        });

        // --- 自研窗口拖动：pointer 事件（鼠标/触摸/触控笔通吃）+ 指针捕获 ---
        // 取代 pywebview 的 easy_drag：其只监听 mousedown/mousemove 且无捕获，
        // 触摸屏机器合成鼠标事件不连续、快速拖动光标跑出小窗口会断流，都会"拖不动"。
        let moyuDragId = null;
        function moyuDragApi(name, ...args) {
            try {
                if (window.pywebview && pywebview.api && pywebview.api[name]) {
                    pywebview.api[name](...args).catch(() => {});
                }
            } catch (err) { /* 桥未就绪等竞态下静默 */ }
        }
        function moyuDragStop(e) {
            if (e.pointerId !== moyuDragId) return;
            moyuDragId = null;
            moyuDragApi('drag_end');
        }
        document.addEventListener('pointerdown', (e) => {
            if (moyuDragId !== null) return;          // 已有指针在拖（多指忽略）
            if (e.button !== 0) return;               // 只认主键/触摸
            // 仅真交互控件豁免（点击/滑杆自身要响应）；label、面板背景等照常可拖，
            // 与旧 easy_drag "任何位置可拖"行为保持一致——控件面板被 mouseenter 唤起
            // 覆盖在窗口上时，从其文字/空白处仍可拖动窗口
            // #progress-bar：点击是跳转语义；#search-bar/#toc-panel：交互面板，
            // 点击/滑动是面板自身的事——均豁免拖窗
            if (e.target.closest('button, input, select, textarea, #progress-bar, #search-bar, #toc-panel')) return;
            moyuDragId = e.pointerId;
            try { e.target.setPointerCapture(e.pointerId); } catch (err) {}
            moyuDragApi('drag_begin', e.screenX, e.screenY);
        });
        document.addEventListener('pointermove', (e) => {
            if (e.pointerId !== moyuDragId) return;
            moyuDragApi('drag_move', e.screenX, e.screenY);
        });
        document.addEventListener('pointerup', moyuDragStop);
        document.addEventListener('pointercancel', moyuDragStop);

        // --- 鼠标感应模式：由 Python 端 MouseSenseController 调用 ---
        function moyuSenseHide() {
            if (senseHidden) return;
            senseHidden = true;
            sensePrevPaused = isPaused;
            senseResumePending = false;
            if (!isPaused) togglePause();  // 隐藏时暂停滚动
            hideControls();
            document.body.classList.add('sense-hidden');
        }
        function moyuSenseShow() {
            if (!senseHidden) return;
            senseHidden = false;
            senseResumePending = !sensePrevPaused;  // 之前在滚 → 淡入后待恢复
            document.body.classList.remove('sense-hidden');
        }
        function moyuSenseResume() {
            if (senseHidden || !senseResumePending) return;
            senseResumePending = false;
            if (isPaused) togglePause();  // 恢复滚动
        }

        // --- 文字样式（字号/颜色/不透明度，Python 端保存后调用或启动时初始化） ---
        function applyFontStyle(size, color, opacity) {
            const m = /^#?([0-9a-fA-F]{6})$/.exec(color || '');
            if (!m) return;
            const r = parseInt(m[1].slice(0, 2), 16);
            const g = parseInt(m[1].slice(2, 4), 16);
            const b = parseInt(m[1].slice(4, 6), 16);
            const a = Math.min(1, Math.max(0.2, (Number(opacity) || 100) / 100));
            document.body.style.fontSize = Number(size) + 'px';
            document.body.style.color = 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
        }

        // Controls auto-hide: show on window entry, fade out after 3s.
        // Mouse movement inside the window does NOT re-trigger the panel;
        // only leaving the window and re-entering does.
        const controlsEl = document.getElementById('controls');
        let controlsTimer = null;
        function showControls() {
            controlsEl.classList.add('show');
            if (controlsTimer) clearTimeout(controlsTimer);
            controlsTimer = setTimeout(() => controlsEl.classList.remove('show'), 3000);
        }
        function hideControls() {
            if (controlsTimer) clearTimeout(controlsTimer);
            controlsEl.classList.remove('show');
        }
        document.getElementById('container').addEventListener('mouseenter', showControls);
        document.getElementById('container').addEventListener('mouseleave', hideControls);
        controlsEl.addEventListener('mouseenter', () => {
            if (controlsTimer) clearTimeout(controlsTimer);  // hovering the panel: stay visible
        });
        controlsEl.addEventListener('mouseleave', showControls);  // leaving panel: restart countdown

        window.addEventListener('resize', () => {
            // 窗口尺寸或字号变化会改变行高，当前页首可能落在行中间：重新对齐（floor 回退，不跳行）
            if (!isAutoMode && content && !settingsOpen) {
                currentPosition = lineFloor(currentPosition);
                updatePagePosition();
                snapTopToRealRow();   // 新行高下钉回真实行顶
            }
            updateProgressBar();  // 视口变了，进度比例跟着变
        });
    </script>
    <!-- SETTINGS -->
</body>
</html>
    """.replace('<!-- SETTINGS -->', get_settings_html())


def create_reader_window(api):
    cfg = api.config['window']

    window = webview.create_window(
        '摸鱼阅读器',
        html=get_html(),
        js_api=api,
        width=cfg['width'],
        height=cfg['height'],
        x=cfg['x'],
        y=cfg['y'],
        min_size=(150, 20),
        resizable=False,
        frameless=True,
        easy_drag=False,  # 拖动由自研 pointer 事件链实现（见 drag_begin/drag_move/drag_end），覆盖鼠标/触摸/触控笔
        on_top=True,
        transparent=True
    )
    # before_show runs on the GUI thread after the native handle is available.
    window.events.before_show += enable_windows_transparency
    api._window = window

    def _on_shown():
        window.resize(cfg['width'], cfg['height'])
        api.sense.attach(window)
        if api.config.get('mouse_sense'):
            api.sense.set_enabled(True)
    window.events.shown += _on_shown
    api.close = lambda: window.destroy()
    return window


if __name__ == '__main__':
    if not ensure_dependencies():
        sys.exit(0)
    api = BookReader()
    window = create_reader_window(api)
    webview.start()
