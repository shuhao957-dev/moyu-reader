# -*- coding: utf-8 -*-
"""目录面板 + Ctrl+F 搜索条测试（v3.0）。

验证目标：
1. Python 章节扫描：识别"第X章/序章"，offset 与 JS 的 UTF-16 单位对齐
   （正文含星外字符 🐟 时 Python len() 会少算，必须按 utf-16 码元计）
2. 长正文行（以"第一章正文…"开头）不被误认成章节
3. get_chapters API 返回结构
4. charOffsetToY：offset 0 → 0；offset = 全长 → 内容底部；中点单调
5. Ctrl+F 唤起搜索条（合成键盘事件）；打开时自动暂停滚动
6. runSearch 计数 + gotoMatch 跳转 + 计数显示
7. 搜索输入框按键不外泄（打字不触发翻页/模式切换）
8. 目录面板：openToc 渲染章节列表；点击条目跳转并关面板
9. 目录面板上 pointerdown+move 不触发窗口拖动（豁免列表）
10. Esc 关闭搜索条并恢复滚动状态

运行：_build_venv/Scripts/python.exe tests/test_toc_search.py
"""
import sys
import json
import time
import tempfile
import threading
import ctypes
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reader as reader_mod


def find_window():
    return ctypes.windll.user32.FindWindowW(None, '摸鱼阅读器')


def rect_of(hwnd):
    rc = wintypes.RECT()
    if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return (rc.left, rc.top, rc.right, rc.bottom)
    return None


def make_book():
    """合成一本带章节标题、搜索关键词和星外字符的小书。
    🐟 是星外字符（UTF-16 代理对，2 码元 vs Python len()=1），
    专用于检验章节偏移的 UTF-16 对齐。"""
    lines = ['序章 起源']
    lines += ['序幕正文 %d 行 pangram quick brown fox。' % i for i in range(60)]
    lines += ['第一章 初入江湖']
    lines += ['第一章正文 %d 行 摸鱼搜索关键词 target。' % i for i in range(60)]
    lines += ['第二章 风起云涌']
    lines += ['🐟第二章正文 %d 行 摸鱼搜索关键词 target。' % i for i in range(60)]
    lines += ['第十二章 大结局']
    lines += ['尾声正文 %d 行 摸鱼搜索关键词 target。' % i for i in range(60)]
    return '\n'.join(lines)


def main():
    results = []

    def check(name, ok):
        results.append((name, ok))
        print(('PASS' if ok else 'FAIL') + ' - ' + name)

    book = make_book()
    tmp = tempfile.mkdtemp(prefix='moyu_toc_test_')
    book_path = Path(tmp) / 'book.txt'
    book_path.write_text(book, encoding='utf-8')

    api = reader_mod.BookReader(data_dir=tmp)

    # ---------- Python 侧：章节扫描（不起窗口就能测） ----------
    api.load_txt(str(book_path))
    titles = [c['title'] for c in api.chapters]
    check('识别 4 个章节标题', titles == ['序章 起源', '第一章 初入江湖', '第二章 风起云涌', '第十二章 大结局'])
    check('长正文行（第一章正文…）不误判为章节', '第一章正文 0 行 摸鱼搜索关键词 target。' not in titles)

    # UTF-16 对齐：第十二章之前有大量 🐟（代理对），Python len 与 JS length 有差
    idx = book.find('第十二章 大结局')
    has_emoji_before = '🐟' in book[:idx]
    expected_off = len(book[:idx].encode('utf-16-le')) // 2
    naive_off = idx  # 若按 Python len() 累加会得到这个（偏小）
    ch12 = [c for c in api.chapters if c['title'] == '第十二章 大结局'][0]
    check('第十二章 offset 按 UTF-16 码元对齐 (off=%s, naive=%s, 含星外字符=%s)'
          % (ch12['offset'], naive_off, has_emoji_before),
          ch12['offset'] == expected_off and has_emoji_before and expected_off > naive_off)
    r = api.get_chapters()
    check('get_chapters 返回结构', isinstance(r, dict) and r['count'] == 4 and len(r['chapters']) == 4)

    # ---------- 500 行分段兜底（识别不出章节标题的书） ----------
    api2 = reader_mod.BookReader(data_dir=tmp)
    seg_lines = ['普通正文行 %d 没有任何章节标题' % i for i in range(1200)]
    api2.content = '\n'.join(seg_lines)
    api2._scan_chapters()
    seg_ok = (len(api2.chapters) == 3
              and api2.chapters[0]['offset'] == 0
              and '第1段' in api2.chapters[0]['title']
              and '行1-500' in api2.chapters[0]['title'])
    expected_seg2 = len('\n'.join(seg_lines[:500]).encode('utf-16-le')) // 2 + 1
    seg_ok = seg_ok and api2.chapters[1]['offset'] == expected_seg2
    check('无章节书按 500 行分段兜底 (3 段, 第2段 offset=%s)' % api2.chapters[1]['offset'], seg_ok)

    # ---------- v3.0.1 宽松档：纯数字独立行章节号（用户书库实测格式） ----------
    def scan(text):
        a = reader_mod.BookReader(data_dir=tmp)
        a.content = text
        a._scan_chapters()
        return a.chapters

    pure_num = '\n'.join(
        ['第一章 起点'] + ['正文'] * 40 + ['1'] + ['正文'] * 40
        + ['2'] + ['正文'] * 40 + ['12'])
    t = [c['title'] for c in scan(pure_num)]
    check('纯数字独立行识别为章节 (n=%d)' % len(t),
          t == ['第一章 起点', '1', '2', '12'])

    numbered = '\n'.join(
        ['一、初入江湖'] + ['正文'] * 40 + ['二、风云再起'] + ['正文'] * 40 + ['三、决战'])
    t = [c['title'] for c in scan(numbered)]
    check('中文数字编号式识别 (n=%d)' % len(t),
          t == ['一、初入江湖', '二、风云再起', '三、决战'])

    variant = '\n'.join(
        ['【第3章】 突袭'] + ['正文'] * 40 + ['第4章：追击'] + ['正文'] * 40 + ['卷二 北境'])
    t = [c['title'] for c in scan(variant)]
    check('括号/冒号变体与卷名识别 (n=%d)' % len(t),
          t == ['【第3章】 突袭', '第4章：追击', '卷二 北境'])

    # 密集编号列表（间隔中位数 < 8 行）必须拒绝宽松档，走分段兜底
    list_like = '\n'.join(['%d. 条目%d' % (i, i) for i in range(1, 21)])
    t = [c['title'] for c in scan(list_like)]
    check('密集编号列表不误判为目录（走分段兜底）',
          len(t) == 1 and '第1段' in t[0])

    # "1.5" 小数不是章节编号
    decimal_text = '\n'.join(
        ['正文开头'] + ['正文'] * 40 + ['1.5 小节'] + ['正文'] * 40 + ['1.6 小节'] + ['正文'] * 40)
    t = [c['title'] for c in scan(decimal_text)]
    check('"1.5" 小数行不误判为章节', t == ['第1段（行1-123）· 正文开头'])

    # ---------- v3.0.1 epub：spine 顺序 + 自带目录映射 ----------
    try:
        import ebooklib
        from ebooklib import epub as epub_mod

        eb = epub_mod.EpubBook()
        eb.set_identifier('t'); eb.set_title('测试书'); eb.set_language('zh')
        mk = lambda fn, tt: epub_mod.EpubHtml(
            title=tt, file_name=fn,
            content='<html><body><p>%s</p><p>该章正文若干行。</p></body></html>' % tt)
        c1, c2, c3 = mk('c1.xhtml', '第一章 甲'), mk('c2.xhtml', '第二章 乙'), mk('c3.xhtml', '第三章 丙')
        for c in (c1, c2, c3):
            eb.add_item(c)
        eb.toc = [epub_mod.Link('c2.xhtml', '第二章 乙', 'c2'),
                  (epub_mod.Section('第二卷'), [epub_mod.Link('c3.xhtml', '第三章 丙', 'c3')]),
                  epub_mod.Link('c1.xhtml', '第一章 甲', 'c1')]
        eb.add_item(epub_mod.EpubNcx()); eb.add_item(epub_mod.EpubNav())
        eb.spine = [c2, c1, c3]   # 故意乱序：验证按 spine 而非 manifest 顺序拼正文
        epub_path = Path(tmp) / 'test.epub'
        epub_mod.write_epub(str(epub_path), eb)

        api_epub = reader_mod.BookReader(data_dir=tmp)
        load_ok = api_epub.load_epub(str(epub_path))
        # spine 顺序 = c2, c1, c3 → 正文开头是"第二章 乙"
        head_ok = api_epub.content.startswith('第二章 乙')
        titles_epub = [c['title'].strip() for c in api_epub.chapters]
        offs = {c['title'].strip(): c['offset'] for c in api_epub.chapters}
        toc_ok = (titles_epub == ['第二章 乙', '第二卷', '第三章 丙', '第一章 甲']
                  and offs['第二章 乙'] == 0
                  and offs['第一章 甲'] > offs['第二章 乙'])
        check('epub 按 spine 顺序读正文（乱序书不串行）', load_ok and head_ok)
        check('epub 自带目录（含卷层级）映射到正确偏移',
              toc_ok and api_epub.get_chapters()['count'] == 4)
    except ImportError:
        check('epub 库不可用，跳过 epub 用例', True)

    # ---------- JS 侧：起真窗口 ----------
    window = reader_mod.create_reader_window(api)

    def run_tests():
        try:
            time.sleep(1.5)  # 等 JS 与 pywebview 注入完成

            # JS content 必须与 api.content 完全一致（offset 才能对上）
            setup = """
            (function() {
                content = %s;
                document.getElementById('text-content').textContent = content;
                isAutoMode = false;
                currentPosition = 0;
                updatePagePosition();
                return 'ready';
            })()
            """ % json.dumps(book)
            assert window.evaluate_js(setup) == 'ready'

            # --- charOffsetToY 基建 ---
            probe = window.evaluate_js(
                "(function(){var total=content.length;"
                " var mid=charOffsetToY(Math.floor(total/2));"
                " var end=charOffsetToY(total);"
                " return JSON.stringify({zero: charOffsetToY(0), mid: mid,"
                "  end: end, ch: contentHeight(), lh: getLineHeight()});})()")
            p = json.loads(probe)
            check('charOffsetToY(0) = 0', abs(p['zero']) < 0.01)
            check('charOffsetToY(全长) ≈ 内容总高 (end=%s, ch=%s)' % (round(p['end'], 1), round(p['ch'], 1)),
                  abs(p['end'] - p['ch']) <= p['lh'])
            check('偏移→像素单调递增 (mid=%s)' % round(p['mid'], 1),
                  p['zero'] < p['mid'] < p['end'])

            # --- Ctrl+F 唤起搜索条 ---
            was_paused = window.evaluate_js('isPaused')
            window.evaluate_js(
                "document.dispatchEvent(new KeyboardEvent('keydown',"
                " {key:'f', ctrlKey:true, bubbles:true, cancelable:true}));")
            time.sleep(0.3)
            bar_state = window.evaluate_js(
                "(function(){return JSON.stringify({open: document.getElementById('search-bar').classList.contains('open'),"
                " paused: isPaused});})()")
            b = json.loads(bar_state)
            check('Ctrl+F 打开搜索条', b['open'])
            check('打开搜索条自动暂停滚动', (not was_paused) and b['paused'])

            # --- 搜索与跳转 ---
            window.evaluate_js("runSearch('target');")
            time.sleep(0.3)
            expected_hits = book.count('target')
            s = window.evaluate_js(
                "(function(){return JSON.stringify({total: searchMatches.length,"
                " label: document.getElementById('search-count').textContent});})()")
            m = json.loads(s)
            check('搜索命中数正确 (%s 处)' % m['total'], m['total'] == expected_hits and m['total'] > 0)
            check('未跳转时计数显示 0/N', m['label'] == '0/%d' % expected_hits)

            window.evaluate_js("gotoMatch(1);")
            time.sleep(0.3)
            g = window.evaluate_js(
                "(function(){return JSON.stringify({pos: currentPosition,"
                " label: document.getElementById('search-count').textContent});})()")
            gm = json.loads(g)
            check('Enter 跳到第一个命中 (pos=%s)' % round(gm['pos'], 1), gm['pos'] > 0)
            check('计数显示 1/N', gm['label'] == '1/%d' % expected_hits)

            # --- 搜索输入框按键不外泄（打字别触发翻页/模式切换） ---
            leak = window.evaluate_js("""
            (function(){
                var modeBefore = document.getElementById('mode-btn').textContent;
                var posBefore = currentPosition;
                var input = document.getElementById('search-input');
                input.dispatchEvent(new KeyboardEvent('keydown',
                    {key:'m', bubbles:true, cancelable:true}));
                input.dispatchEvent(new KeyboardEvent('keydown',
                    {key:'x', bubbles:true, cancelable:true}));
                return JSON.stringify({modeSame: document.getElementById('mode-btn').textContent === modeBefore,
                    posSame: currentPosition === posBefore});
            })()""")
            lk = json.loads(leak)
            check('搜索框内打字不触发模式切换/翻页', lk['modeSame'] and lk['posSame'])

            # --- 目录面板（复用设置撑窗机制） ---
            window.evaluate_js("closeSearch();")   # 先关搜索条（也验证恢复暂停）
            time.sleep(0.2)
            paused_after_close = window.evaluate_js('isPaused')
            check('关闭搜索条恢复滚动状态', not paused_after_close)

            hwnd = find_window()
            rect_normal = rect_of(hwnd) if hwnd else None
            window.evaluate_js("openToc();")
            time.sleep(1.0)  # openToc 是 async（撑窗 + 过桥拿章节）
            t = window.evaluate_js(
                "(function(){var items = document.querySelectorAll('#toc-list .toc-item');"
                " return JSON.stringify({open: !document.getElementById('toc-panel').hidden"
                "  && document.body.classList.contains('toc-open'),"
                " n: items.length, first: items.length ? items[0].textContent : '',"
                " paused: isPaused});})()")
            tt = json.loads(t)
            check('openToc 打开目录面板', tt['open'])
            check('目录渲染 4 个章节', tt['n'] == 4)
            check('首个条目为序章', tt['first'] == '序章 起源')
            check('打开目录自动暂停滚动', tt['paused'])
            rect_toc = rect_of(hwnd) if hwnd else None
            toc_enlarged = (rect_toc is not None and rect_normal is not None
                            and rect_toc[3] - rect_toc[1] > rect_normal[3] - rect_normal[1] + 200)
            check('打开目录撑大窗口 (正常高=%s → 目录高=%s)'
                  % (rect_normal[3] - rect_normal[1] if rect_normal else '?',
                     rect_toc[3] - rect_toc[1] if rect_toc else '?'), toc_enlarged)

            # --- 点击第二个章节条目（第一章）：关面板恢复窗口后跳转 ---
            window.evaluate_js("""
            (function(){
                var items = document.querySelectorAll('#toc-list .toc-item');
                items[1].click();
                return 'clicked';
            })()""")
            time.sleep(1.2)  # onclick 是 async：closeToc（恢复窗口）→ 量像素 → 跳转
            j = json.loads(window.evaluate_js(
                "(function(){return JSON.stringify({pos: currentPosition,"
                " open: document.body.classList.contains('toc-open'),"
                " paused: isPaused});})()"))
            expected_y = window.evaluate_js(
                "charOffsetToY(%d)" % api.chapters[1]['offset'])
            check('点击第一章跳到对应位置 (pos=%s, 期望≈%s)' % (round(j['pos'], 1), round(expected_y, 1)),
                  abs(j['pos'] - max(0, expected_y)) <= 2 * 25)  # 行高约 22-25px，容差两行
            check('点击后目录关闭', not j['open'])
            check('关闭目录恢复滚动状态', not j['paused'])
            rect_back = rect_of(hwnd) if hwnd else None
            check('关闭目录恢复窗口尺寸', rect_back == rect_normal)

            # --- 目录面板不拖窗（豁免列表；窗口处于撑大状态） ---
            window.evaluate_js("openToc();")
            time.sleep(0.8)
            hwnd = find_window()
            if not hwnd:
                check('找到测试窗口', False)
            else:
                rect_before = rect_of(hwnd)
                window.evaluate_js("""
                (function(){
                    var panel = document.getElementById('toc-panel');
                    panel.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, button:0,
                        pointerId:9, screenX:500, screenY:500, clientX:50, clientY:50}));
                    document.dispatchEvent(new PointerEvent('pointermove', {bubbles:true,
                        pointerId:9, screenX:650, screenY:560, clientX:200, clientY:110}));
                    document.dispatchEvent(new PointerEvent('pointerup', {bubbles:true, pointerId:9}));
                    return 'done';
                })()""")
                time.sleep(0.8)
                rect_after = rect_of(hwnd)
                delta = None if (rect_before is None or rect_after is None) else (
                    rect_after[0] - rect_before[0], rect_after[1] - rect_before[1])
                # 合成 move 是 (+150, +60)：delta 恰好等于它 = 真拖动 bug；
                # 其他随机值 = 人类测试观察员碰了窗口（假失败）
                check('目录面板 pointerdown 不触发窗口拖动 (delta=%s)' % (delta,),
                      delta == (0, 0))

            # --- Esc 关闭目录 ---
            window.evaluate_js(
                "document.dispatchEvent(new KeyboardEvent('keydown',"
                " {key:'Escape', bubbles:true, cancelable:true}));")
            time.sleep(0.5)  # closeToc 恢复窗口是 async
            esc_closed = window.evaluate_js(
                "!document.body.classList.contains('toc-open')")
            check('Esc 关闭目录面板', esc_closed)

        except Exception as e:
            check('测试执行异常: %r' % e, False)
        finally:
            time.sleep(0.3)
            try:
                window.destroy()
            except Exception:
                pass

    window.events.shown += lambda: threading.Thread(target=run_tests, daemon=True).start()
    reader_mod.webview.start()

    failed = [n for n, ok in results if not ok]
    print()
    print('目录与搜索测试: %d/%d 通过' % (len(results) - len(failed), len(results)))
    if failed:
        print('失败项：', failed)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
