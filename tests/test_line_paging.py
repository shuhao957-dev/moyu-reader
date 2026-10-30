# -*- coding: utf-8 -*-
"""行对齐分页测试（v2.1.7：消灭半行跳字；v3.0：闭环校准钉真实行顶）。

验证目标（v3.0 口径：位置对齐"真实渲染行栅格"而非 22.4px 数学栅格）：
1. pageDown 后页首前进量 ≈ 视口高度（±半行的校准余量内）
2. 连续翻页序列严格递增，且每页首行完整（视口顶首行行顶偏差 < 1px，无腰斩行）
3. 翻到底（剩余内容不足一屏）后 pageDown 不再移动
4. pageUp 回退与前进近似可逆（容差半行：snap 每页把位置钉回真实行顶，
   严格逐位相等让位于"每页首行完整"；容差 < 一行，不掩盖跳行/重复行）
5. lineFloor：任意像素的进度恢复对齐（回退到所在行行首，最多回退一行）
6. 自动滚动模式的 saveProgress/续滚不受分页改造影响（currentPosition 任意像素合法）
7. 行盒不均匀（emoji 撑高）时连续翻页首行依然完整——闭环校准的核心场景

运行：_build_venv/Scripts/python.exe tests/test_line_paging.py
"""
import sys
import time
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reader as reader_mod


# 量"视口顶首行行顶相对视口顶的偏差"——>0 首行悬空，<0 首行上沿被裁（半截字）
# 注意：text-content 有 transition: transform 0.1s，量测前必须禁用过渡，
# 否则量到的是过渡中间帧的布局（失真）。
ROW_TOP_PROBE = """
function rowTopDelta() {
    var el = document.getElementById('text-content');
    var prev = el.style.transition;
    el.style.transition = 'none';
    var display = document.getElementById('text-display');
    var dt = display.getBoundingClientRect().top;
    var cx = Math.floor(display.getBoundingClientRect().width / 2);
    var range = document.caretRangeFromPoint(cx, dt + 1);
    var out = null;
    try {
        if (range && range.startContainer) {
            var node = range.startContainer, rect = null;
            if (node.nodeType === 3 && range.startOffset < node.length) {
                var end = range.startOffset + 1;
                var cu = node.data.charCodeAt(range.startOffset);
                if (cu >= 0xD800 && cu <= 0xDBFF && end < node.length) end++;
                var r = document.createRange();
                r.setStart(node, range.startOffset);
                r.setEnd(node, end);
                rect = r.getClientRects()[0];
            }
            if (!rect) rect = range.getClientRects()[0];
            out = rect ? (rect.top - dt) : null;
        }
    } finally {
        el.style.transition = prev;
    }
    return out;
}
"""


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
            assert window.evaluate_js(ROW_TOP_PROBE) is None  # 注入 rowTopDelta 探针

            # --- 测试 1：pageDown 后前进量 ≈ 视口高（±半行校准余量），首行完整 ---
            probe = window.evaluate_js(
                "(function(){var r={}; r.lh=getLineHeight(); r.vh=viewHeight();"
                " r.ch=contentHeight(); pageDown(); r.pos=currentPosition;"
                " r.rt=rowTopDelta(); return JSON.stringify(r);})()")
            import json
            r = json.loads(probe)
            first_row_ok = r['rt'] is not None and abs(r['rt']) < 1.0
            # floor 语义：前进量 = 视口高去掉不足一行的零头，再叠加 ±半行闭环校准
            advance_ok = r['vh'] - 2 * r['lh'] < r['pos'] <= r['vh'] + r['lh']
            check('pageDown 首行完整钉在真实行顶 (pos=%s, rowTop=%s)'
                  % (r['pos'], r['rt']), first_row_ok)
            check('首翻前进量≈视口高 (pos=%s, vh=%s)' % (r['pos'], r['vh']), advance_ok)

            # --- 测试 2：连续翻 20 页，序列严格递增且每页首行完整 ---
            seq = window.evaluate_js(
                "(function(){var s=[currentPosition], lh=getLineHeight(), rts=[], bad=0;"
                " for(var i=0;i<20;i++){pageDown(); s.push(currentPosition);"
                "  var rt=rowTopDelta(); rts.push(rt); if(rt===null||Math.abs(rt)>=1.0) bad++;}"
                " return s.join(',')+']'+bad;})()")
            positions, bad_rows = seq.split(']')
            positions = [float(x) for x in positions.split(',')]
            strictly_inc = all(b > a for a, b in zip(positions, positions[1:]))
            check('连续翻页严格递增无停跳', strictly_inc)
            check('20 页页首全部完整（rowTop<1px, 违例=%s）' % bad_rows, int(bad_rows) == 0)

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
            # v3.0：snap 校准让步长不再是恒定整行数，改为界内检查（约一屏，不跳多页）
            steps = [float(x) for x in step_set.split(',') if x]
            steps_ok = bool(steps) and all(0.5 * r['lh'] < s <= r['vh'] + r['lh'] for s in steps)
            check('翻页步长均约一屏（步长集合=%s）' % step_set, steps_ok)

            # --- 测试 4：往返全程不变量（v3.0 口径）---
            # snap 闭环校准后，去/回程"每页行数节奏"不同（去程偶尔 1 行步，
            # 因为残行要完整重现），逐项配对位置不再成立。改为验证本质不变量：
            # a) 双向可达同一端点（0 ↔ 底部，无卡死）
            # b) 去程严格递增、回程严格递减（不重复不倒退）
            # c) 每步幅度界内（>0 且 ≤ vh+lh：跳过整页才算跳行）
            rev_probe = window.evaluate_js(
                "(function(){currentPosition=0; updatePagePosition();"
                " var lh=getLineHeight(), vh=viewHeight();"
                " var fwdInc=true, fwdStep=true, guard=0;"
                " while(guard<20000){var b=currentPosition; pageDown();"
                "  if(currentPosition===b) break;"
                "  if(currentPosition<=b) fwdInc=false;"
                "  var d=currentPosition-b; if(d<=0||d>vh+lh) fwdStep=false;"
                "  guard++;}"
                " var bottom=currentPosition; var fwdN=guard;"
                " var bwdDec=true, bwdStep=true; guard=0;"
                " while(guard<20000){var b=currentPosition; pageUp();"
                "  if(currentPosition===b) break;"
                "  if(currentPosition>=b) bwdDec=false;"
                "  var d=b-currentPosition; if(d<=0||d>vh+lh) bwdStep=false;"
                "  guard++;}"
                " var zeroStop=(currentPosition===0);"
                " pageUp(); if(currentPosition!==0) zeroStop=false;"
                " pageUp(); if(currentPosition!==0) zeroStop=false;"
                " return JSON.stringify({fwdN:fwdN, bottom:bottom, fwdInc:fwdInc,"
                "  fwdStep:fwdStep, bwdN:guard, bwdDec:bwdDec, bwdStep:bwdStep,"
                "  zeroStop:zeroStop, end:currentPosition});})()")
            import json as _json
            rev = _json.loads(rev_probe)
            check('往返双向可达 (去%d页/回%d页, bottom=%.0f)'
                  % (rev['fwdN'], rev['bwdN'], rev['bottom']),
                  rev['end'] == 0 and rev['zeroStop'] and rev['bottom'] > 0)
            check('去程严格递增且步长界内（不跳行不重复）',
                  bool(rev['fwdInc']) and bool(rev['fwdStep']))
            check('回程严格递减且步长界内（不跳行不重复）',
                  bool(rev['bwdDec']) and bool(rev['bwdStep']))

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

            # --- 测试 7：行盒不均匀（emoji 撑高个别行）时连续翻页首行依然完整 ---
            # 这是 v3.0 闭环校准的核心场景：真实行栅格偏离 22.4px 数学栅格并
            # 随页数累积（旧算法翻几十页后首行变半截），snap 必须每页拉回。
            drift = window.evaluate_js("""
            (function(){
                var lines = [];
                for (var i = 0; i < 400; i++) {
                    lines.push('第' + i + '行 常规文本行，用于铺满行栅格。');
                    if (i % 7 === 3) lines.push('🦊😀🚀🎯 字体回退行盒可能被撑高 🎯🚀😀🦊');
                }
                content = lines.join('\\n');
                document.getElementById('text-content').textContent = content;
                currentPosition = 0; updatePagePosition();
                var maxAbs = 0, nPages = 0, lh = getLineHeight();
                for (var p = 0; p < 30; p++) {
                    pageDown(); nPages++;
                    var rt = rowTopDelta();
                    if (rt === null) return 'probe-null@' + p;
                    if (Math.abs(rt) > maxAbs) maxAbs = Math.abs(rt);
                }
                return JSON.stringify({maxAbs: maxAbs, nPages: nPages, lh: lh});
            })()""")
            if isinstance(drift, str) and drift.startswith('probe-null'):
                check('emoji 撑高行盒下 30 页翻页首行始终完整 (%s)' % drift, False)
            else:
                d = json.loads(drift)
                check('emoji 撑高行盒下 30 页翻页首行始终完整 (最大偏差=%s px)' % round(d['maxAbs'], 2),
                      d['maxAbs'] < 1.0)

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
