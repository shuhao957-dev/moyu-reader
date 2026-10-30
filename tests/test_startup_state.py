# -*- coding: utf-8 -*-
"""启动状态测试（v3.0.2：打开书暂停起步 + 记住翻页模式 + 对话框默认 txt+epub 筛选）。

验证目标：
Python 侧：
1. 新配置默认 auto_mode=True；set_auto_mode 落盘，重开实例恢复
2. apply_settings 保存设置不丢 auto_mode（隐藏坑：字段挑着搬）
3. open_file 返回值带 auto_mode（上次模式）
JS 侧（真窗口）：
4. 自动模式 + 暂停起步时按空格 = 恢复滚动（togglePause），再按 = 暂停
5. 手动模式按空格 = 翻页（不触发 togglePause）
6. toggleMode 后模式按钮/文案同步，set_auto_mode 持久化被调用（盘上 config 变化）

运行：_build_venv/Scripts/python.exe tests/test_startup_state.py
"""
import sys
import time
import json
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reader as reader_mod

passed = 0
failed = 0


def check(name, ok):
    global passed, failed
    print(('PASS' if ok else 'FAIL') + ' | ' + name)
    if ok:
        passed += 1
    else:
        failed += 1


def test_python():
    tmp = tempfile.mkdtemp(prefix="moyu_startup_")
    api = reader_mod.BookReader(data_dir=tmp)
    check('新配置默认 auto_mode=True', api.config.get('auto_mode') is True)

    r = api.set_auto_mode(False)
    check('set_auto_mode(False) 成功', r['success'])
    check('set_auto_mode 立即生效', api.config['auto_mode'] is False)

    api2 = reader_mod.BookReader(data_dir=tmp)
    check('重开实例从盘上恢复 auto_mode=False', api2.config.get('auto_mode') is False)

    # 隐藏坑回归：apply_settings 字段挑着搬，必须保留 auto_mode
    api2.apply_settings(400, 60, 50, mouse_sense=False, progress_bar=False)
    check('apply_settings 保存不丢 auto_mode', api2.config.get('auto_mode') is False)

    # open_file 返回带上次模式（fake 窗口避开真对话框）
    txt = Path(tmp) / "sample.txt"
    txt.write_text("第一章 试\n正文行\n" * 60, encoding="utf-8")

    class FakeWin:
        def create_file_dialog(self, *a, **kw):
            return [str(txt)]

    api2._window = FakeWin()
    result = api2.open_file()
    check('open_file 返回带 auto_mode=False（上次手动）',
          result['success'] and result.get('auto_mode') is False)

    api3 = reader_mod.BookReader(data_dir=tmp)
    api3.set_auto_mode(True)
    api3._window = FakeWin()
    r3 = api3.open_file()
    check('切回自动后 open_file 返回 auto_mode=True',
          r3['success'] and r3.get('auto_mode') is True)


def test_js():
    tmp = tempfile.mkdtemp(prefix="moyu_startup_js_")
    api = reader_mod.BookReader(data_dir=tmp)
    window = reader_mod.create_reader_window(api)

    def run():
        try:
            time.sleep(1.5)
            # 铺开内容、模拟"打开书后暂停起步"状态（openFile 的等价状态）
            setup = """
            (function(){
                content = Array.from({length: 800}, (_, i) =>
                    '第' + String(i+1).padStart(4,'0') + '行 启动状态回归文本。').join('\\n');
                document.getElementById('text-content').textContent = content;
                isAutoMode = true; isPaused = true;
                document.getElementById('pause-btn').textContent = '继续';
                syncModeUi(false);
                updatePagePosition();
                return 'ready';
            })()"""
            assert window.evaluate_js(setup) == 'ready'

            # --- 空格（自动模式+暂停起步）→ 恢复滚动 ---
            window.evaluate_js(
                "document.dispatchEvent(new KeyboardEvent('keydown',"
                " {key:' ', bubbles:true, cancelable:true}));")
            time.sleep(0.2)
            r1 = window.evaluate_js(
                "(function(){return JSON.stringify({paused: isPaused,"
                " btn: document.getElementById('pause-btn').textContent,"
                " frame: scrollFrame !== 0});})()")
            d1 = json.loads(r1)
            check('自动模式暂停起步时空格恢复滚动 (paused=%s)' % d1['paused'],
                  d1['paused'] is False and d1['btn'] == '暂停')

            # --- 再按空格 → 暂停 ---
            window.evaluate_js(
                "document.dispatchEvent(new KeyboardEvent('keydown',"
                " {key:' ', bubbles:true, cancelable:true}));")
            time.sleep(0.2)
            r2 = window.evaluate_js('JSON.stringify({paused: isPaused})')
            check('滚动中再按空格暂停', json.loads(r2)['paused'] is True)

            # --- 手动模式：空格 = 翻页（不碰暂停） ---
            r3 = window.evaluate_js("""
            (function(){
                isAutoMode = false; isPaused = false;
                syncModeUi(false);
                var before = currentPosition;
                document.dispatchEvent(new KeyboardEvent('keydown',
                    {key:' ', bubbles:true, cancelable:true}));
                return JSON.stringify({moved: currentPosition > before,
                    paused: isPaused,
                    btn: document.getElementById('mode-btn').textContent});
            })()""")
            d3 = json.loads(r3)
            check('手动模式空格=翻页且不触发暂停 (moved=%s, paused=%s)'
                  % (d3['moved'], d3['paused']),
                  d3['moved'] is True and d3['paused'] is False)
            check('syncModeUi 同步手动模式按钮文案 (btn=%s)' % d3['btn'],
                  d3['btn'] == '手动')

            # --- toggleMode 持久化到 Python config ---
            cfg_before = api.config.get('auto_mode')
            window.evaluate_js("toggleMode();")
            time.sleep(0.6)   # 等过桥 set_auto_mode 落盘
            cfg_after = api.config.get('auto_mode')
            check('toggleMode 切回自动并持久化 (%s → %s)' % (cfg_before, cfg_after),
                  cfg_before is False and cfg_after is True)
        finally:
            time.sleep(0.3)
            try:
                window.destroy()
            except Exception:
                pass

    window.events.shown += lambda: threading.Thread(target=run, daemon=True).start()
    reader_mod.webview.start()


if __name__ == '__main__':
    test_python()
    test_js()
    print('\n总结: %d 通过, %d 失败' % (passed, failed))
    sys.exit(1 if failed else 0)
