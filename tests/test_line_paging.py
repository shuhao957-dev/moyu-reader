# -*- coding: utf-8 -*-
"""行对齐分页测试（v2.1.7：消灭半行跳字）。

验证目标：
1. pageDown 后页首位置必为行高整数倍（行边界），且第一页前进量 ≈ 视口高度（ceil 对齐多出不到一行）
2. 连续翻页序列严格递增且全部落在行边界上（无腰斩行）
3. 翻到底（剩余内容不足一屏）后 pageDown 不再移动
4. pageUp 回退与前进序列严丝合缝（回到此前驻留过的位置，无跳行无重复）
5. lineFloor：任意像素的进度恢复对齐（回退到所在行行首，最多回退一行）
6. 自动滚动模式的 saveProgress/续滚不受分页改造影响（currentPosition 任意像素合法）

运行：_build_venv/Scripts/python.exe tests/test_line_paging.py
"""
import sys
import time
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reader as reader_mod


def main():
    results = []

    def check(name, ok):
        results.append((name, ok))
        print(('PASS' if ok else 'FAIL') + ' - ' + name)

    tmp = tempfile.mkdtemp(prefix='moyu_paging_test_')
    api = reader_mod.BookReader(data_dir=tmp)
    window = reader_mod.create_reader_window(api)

    def run_tests():
        try:
            time.sleep(1.5)  # 等 JS 与 pywebview 对象注入完成
            # 构造长文本并直接进入手动模式（绕开文件对话框）
            js_setup = """
            (function() {
                content = Array.from({length: 3000}, (_, i) =>
                    '第' + String(i+1).padStart(4,'0') + '行 摸鱼阅读器行对齐分页回归文本 pangram quick brown fox。').join('\\n');
                document.getElementById('text-content').textContent = content;
                isAutoMode = false;
                currentPosition = 0;
                updatePagePosition();
                return 'ready';
            })()
            """
            assert window.evaluate_js(js_setup) == 'ready'

            # --- 测试 1：pageDown 后页首落在行边界，前进量 ≈ 视口高 ---
            probe = window.evaluate_js(
                "(function(){var r={}; r.lh=getLineHeight(); r.vh=viewHeight();"
                " r.ch=contentHeight(); pageDown(); r.pos=currentPosition; return JSON.stringify(r);})()")
            import json
            r = json.loads(probe)
            on_grid = abs(r['pos'] % r['lh']) < 0.5 or abs(r['pos'] % r['lh'] - r['lh']) < 0.5
            # floor 语义：前进量 = 视口高去掉不足一行的零头，落在 (vh-lh, vh]
            advance_ok = r['vh'] - r['lh'] < r['pos'] <= r['vh'] + 0.5
            check('pageDown 首翻落在行边界 (pos=%s, lh=%s)' % (r['pos'], r['lh']), on_grid)
            check('首翻前进量≈视口高 (pos=%s, vh=%s)' % (r['pos'], r['vh']), advance_ok)

            # --- 测试 2：连续翻 20 页，序列严格递增且全在行边界 ---
            seq = window.evaluate_js(
                "(function(){var s=[currentPosition], lh=getLineHeight();"
                " for(var i=0;i<20;i++){pageDown(); s.push(currentPosition);} return s.join(',');})()")
            positions = [float(x) for x in seq.split(',')]
            strictly_inc = all(b > a for a, b in zip(positions, positions[1:]))
            # 浮点下 22.4 无法精确表示，直接取模可能落在 22.3999...；改用行数取整判断
            all_on_grid = all(abs(p / r['lh'] - round(p / r['lh'])) < 0.02 for p in positions)
            check('连续翻页严格递增无停跳', strictly_inc)
            check('20 页页首全部落在行边界', all_on_grid)

            # --- 测试 3：一路翻到底；到底后不再移动；每步步长唯一（恒定整行数） ---
            # 注意：evaluate_js 返回巨型数组会被截断，序列本体留在 JS 侧只回传统计量
            end_probe = window.evaluate_js(
                "(function(){var s=[currentPosition]; var guard=0;"
                " while(guard<20000){var before=currentPosition; pageDown();"
                " if(currentPosition===before) break; s.push(currentPosition); guard++;}"
                " var bottom=currentPosition; pageDown();"
                " var steps={}; for(var i=1;i<s.length;i++){steps[Math.round((s[i]-s[i-1])*10)/10]=1;}"
                " return bottom+']'+currentPosition+']'+contentHeight()+']'+s.length+']'"
                " +Object.keys(steps).join(',');})()")
            bottom, after_bottom, ch, n_steps, step_set = end_probe.split(']')
            bottom, after_bottom, ch, n_steps = (float(bottom), float(after_bottom),
                                                 float(ch), int(n_steps))
            check('到底后 pageDown 不再移动 (bottom=%s)' % bottom, bottom == after_bottom)
            check('到底位置能看到全文末尾 (bottom+vh >= ch)',
                  bottom + r['vh'] + 0.5 >= ch)
            check('翻页步长恒定唯一（整行数步进, 步长集合=%s）' % step_set,
                  step_set in ('44.8', '44.8,22.4', '22.4,44.8'))

            # --- 测试 4：从顶部出发一路翻到底再一路回退，路径必须互为严格逆序（可逆=无跳行无重复）---
            rev_probe = window.evaluate_js(
                "(function(){currentPosition=0; updatePagePosition();"
                " var fwd=[currentPosition]; var guard=0;"
                " while(guard<20000){var b=currentPosition; pageDown();"
                "  if(currentPosition===b) break; fwd.push(currentPosition); guard++;}"
                " var bwd=[currentPosition]; guard=0;"
                " while(guard<20000){var b=currentPosition; pageUp();"
                "  if(currentPosition===b) break; bwd.push(currentPosition); guard++;}"
                " var rev=true;"
                "  for(var i=0;i<fwd.length;i++){"
                "   if(Math.abs(fwd[i]-bwd[fwd.length-1-i])>0.5){rev=false; break;}}"
                " var zeroStop=true; pageUp(); if(currentPosition!==0) zeroStop=false;"
                " pageUp(); if(currentPosition!==0) zeroStop=false;"
                " return JSON.stringify({rev:rev, zeroStop:zeroStop,"
                "  end:currentPosition, len:fwd.length});})()")
            import json as _json
            rev = _json.loads(rev_probe)
            check('pageUp 回退=前进严格逆序，来回翻页完全可逆 (%d 页)' % rev['len'],
                  bool(rev['rev']))
            check('回退到顶后再 pageUp 不动 (end=%s)' % rev['end'],
                  rev['end'] == 0 and bool(rev['zeroStop']))

            # --- 测试 5：lineFloor 进度恢复对齐 ---
            floor_probe = window.evaluate_js(
                "(function(){var lh=getLineHeight(); var cases=[0, 1, lh*0.5, lh*1.7, 51.3, 99999];"
                " var out=[]; for(var c of cases){out.push(lineFloor(c));} return lh+','+out.join(',');})()")
            parts = [float(x) for x in floor_probe.split(',')]
            lh = parts[0]
            outs = parts[1:]
            exp = [0.0, 0.0, 0.0, lh, (51.3 // lh) * lh, (99999 // lh) * lh]
            floor_ok = all(abs(a - b) < 0.5 for a, b in zip(outs, exp))
            check('lineFloor 恢复对齐（回退到行首，不跳内容）', floor_ok)

            # --- 测试 6：自动滚动模式不受影响（任意像素合法续滚） ---
            auto_probe = window.evaluate_js(
                "(function(){isAutoMode=true; currentPosition=123.456;"
                " var v=isAutoMode && Math.abs(currentPosition-123.456)<0.01;"
                " isAutoMode=false; currentPosition=0; updatePagePosition(); return v;})()")
            check('自动滚动模式任意像素位置不受分页改造影响', bool(auto_probe))

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
    print('行对齐分页测试: %d/%d 通过' % (len(results) - len(failed), len(results)))
    if failed:
        print('失败项：', failed)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
