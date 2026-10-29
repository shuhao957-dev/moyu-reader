# -*- coding: utf-8 -*-
"""自研 pointer 拖动链路冒烟测试（v2.1.6 → 拖不动修复）。

验证目标：
1. 合成 pointerdown/pointermove/pointerup 事件序列能真实移动窗口（锚点式 SetWindowPos）
2. 拖动结束后 anchor 清空，后续 pointermove 不再移动窗口
3. 控件区（#controls）上的 pointerdown 不启动拖动
4. 非主键（button=2 右键）pointerdown 不启动拖动
5. pywebview easy_drag 已关闭（避免双拖动打架）——通过行为间接验证

运行：_build_venv/Scripts/python.exe tests/test_drag_pointer.py
"""
import sys
import time
import ctypes
import tempfile
import threading
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reader as reader_mod

user32 = ctypes.windll.user32


def get_rect(hwnd):
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top)


DISPATCH_JS = """
(function() {{
    var target = document.querySelector('{sel}') || document.body;
    var base = {{bubbles: true, cancelable: true, pointerId: 1, button: {button},
                clientX: 50, clientY: 30, screenX: {sx}, screenY: {sy}}};
    var id = target.dispatchEvent(new PointerEvent('pointerdown', base));
    var mv = Object.assign({{}}, base, {{screenX: {sx} + {dx}, screenY: {sy} + {dy}}});
    target.dispatchEvent(new PointerEvent('pointermove', mv));
    var up = Object.assign({{}}, mv);
    target.dispatchEvent(new PointerEvent('pointerup', up));
    return 'ok';
}})()
"""


def main():
    results = []

    def check(name, ok):
        results.append((name, ok))
        print(('PASS' if ok else 'FAIL') + ' - ' + name)

    tmp = tempfile.mkdtemp(prefix='moyu_drag_test_')
    api = reader_mod.BookReader(data_dir=tmp)
    window = reader_mod.create_reader_window(api)
    hwnd_holder = {}

    def run_tests():
        try:
            time.sleep(1.5)  # 等 JS 与 pywebview 对象注入完成

            hwnd = window.native.Handle.ToInt64()
            hwnd_holder['hwnd'] = hwnd

            # --- 测试 1：正文区拖动 +40/+30 ---
            r0 = get_rect(hwnd)
            window.evaluate_js(
                DISPATCH_JS.format(sel='#text-display', button=0,
                                   sx=r0[0] + 100, sy=r0[1] + 40, dx=40, dy=30))
            time.sleep(1.0)  # 等 js_api 线程完成 SetWindowPos
            r1 = get_rect(hwnd)
            check('pointer 拖动真实移动窗口 (+40/+30)',
                  r1 is not None and r0 is not None
                  and abs(r1[0] - r0[0] - 40) <= 2 and abs(r1[1] - r0[1] - 30) <= 2)

            # --- 测试 2：拖动结束后 anchor 清空，散逸 pointermove 不再动窗 ---
            window.evaluate_js(
                "document.dispatchEvent(new PointerEvent('pointermove', "
                "{bubbles:true, pointerId:1, button:0, screenX:9999, screenY:9999}))")
            time.sleep(0.6)
            r2 = get_rect(hwnd)
            check('拖动结束后散逸事件不再移动窗口', r2 == r1)

            # --- 测试 3：真交互控件（滑杆）上 pointerdown 不拖动 ---
            r3_before = get_rect(hwnd)
            window.evaluate_js(
                DISPATCH_JS.format(sel='#controls input[type="range"]', button=0,
                                   sx=r3_before[0] + 50, sy=r3_before[1] + 10, dx=80, dy=60))
            time.sleep(0.8)
            r3_after = get_rect(hwnd)
            check('滑杆等真交互控件不触发拖窗', r3_after == r3_before)

            # --- 测试 3b：控件面板被唤起时，从 label/面板文字仍可拖窗（旧 easy_drag 行为） ---
            r3b_before = get_rect(hwnd)
            window.evaluate_js(
                DISPATCH_JS.format(sel='#controls label', button=0,
                                   sx=r3b_before[0] + 50, sy=r3b_before[1] + 10, dx=55, dy=35))
            time.sleep(0.8)
            r3b_after = get_rect(hwnd)
            check('控件区 label/空白仍可拖窗',
                  r3b_after is not None and r3b_before is not None
                  and abs(r3b_after[0] - r3b_before[0] - 55) <= 2
                  and abs(r3b_after[1] - r3b_before[1] - 35) <= 2)

            # --- 测试 4：右键 pointerdown 不拖动 ---
            window.evaluate_js(
                DISPATCH_JS.format(sel='#text-display', button=2,
                                   sx=r3b_before[0] + 100, sy=r3b_before[1] + 40, dx=70, dy=50))
            time.sleep(0.8)
            r4_after = get_rect(hwnd)
            check('非主键 pointerdown 不触发拖窗', r4_after == r3b_after)
        except Exception as e:
            print('EXCEPTION:', e)
            results.append(('异常中断', False))
        finally:
            time.sleep(0.3)
            try:
                window.destroy()
            except Exception:
                pass

    window.events.shown += lambda: threading.Thread(target=run_tests, daemon=True).start()
    reader_mod.webview.start()

    failed = [name for name, ok in results if not ok]
    print()
    print('=' * 50)
    print('拖动链路冒烟：%d/%d 通过' % (len(results) - len(failed), len(results)))
    if failed:
        print('失败项：', failed)
        sys.exit(1)
    print('全部通过')


if __name__ == '__main__':
    main()
