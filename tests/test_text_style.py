# -*- coding: utf-8 -*-
"""文字样式（字号/颜色/透明度）+ 设置窗口防出屏 测试"""
import sys
import os
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reader


def make_reader(tmp, config=None):
    if config is not None:
        (Path(tmp) / '.moyu_reader_config.json').write_text(
            json.dumps(config, ensure_ascii=False), encoding='utf-8')
    return reader.BookReader(data_dir=tmp)


def main():
    results = []

    def check(name, ok):
        results.append(ok)
        print(('PASS ' if ok else 'FAIL ') + name)

    with tempfile.TemporaryDirectory() as tmp:
        # 1. 老配置文件（无新键）→ 自动补默认值
        r = make_reader(tmp, config={
            'window': {'width': 400, 'height': 60, 'x': 1, 'y': 2},
            'speed': 55, 'mouse_sense': True})
        check('老配置补默认 font_size=14', r.config.get('font_size') == 14)
        check('老配置补默认 text_color=#333333', r.config.get('text_color') == '#333333')
        check('老配置补默认 text_opacity=100', r.config.get('text_opacity') == 100)
        check('老配置原有键不受影响', r.config['speed'] == 55 and r.config['mouse_sense'] is True)

        # 2. apply_settings 带文字样式 → 持久化
        r._window = None
        res = r.apply_settings(300, 60, 50, False, 18, '#1a5fb4', 60)
        check('新参数保存成功', res.get('success') is True)
        check('配置写入 font_size=18', r.config['font_size'] == 18)
        check('配置写入 text_color', r.config['text_color'] == '#1a5fb4')
        check('配置写入 text_opacity=60', r.config['text_opacity'] == 60)
        on_disk = json.loads((Path(tmp) / '.moyu_reader_config.json').read_text(encoding='utf-8'))
        check('磁盘配置同步三件套', on_disk.get('font_size') == 18 and on_disk.get('text_color') == '#1a5fb4' and on_disk.get('text_opacity') == 60)

        # 3. 旧式调用（4 参数）→ 文字样式保持现值
        res = r.apply_settings(300, 60, 50, False)
        check('旧式调用不丢文字样式', res['success'] and r.config['font_size'] == 18 and r.config['text_opacity'] == 60)

        # 4. 非法值 → 拒绝且不落盘
        bad = r.apply_settings(300, 60, 50, False, 9, '#333333', 100)
        check('字号 9 被拒', bad['success'] is False)
        bad = r.apply_settings(300, 60, 50, False, 14, '#33g333', 100)
        check('非法颜色被拒', bad['success'] is False)
        bad = r.apply_settings(300, 60, 50, False, 14, '#333333', 10)
        check('透明度 10 被拒', bad['success'] is False)
        on_disk = json.loads((Path(tmp) / '.moyu_reader_config.json').read_text(encoding='utf-8'))
        check('被拒后磁盘配置未变', on_disk.get('font_size') == 18)

        # 5. 大写十六进制颜色合法
        res = r.apply_settings(300, 60, 50, False, 14, '#1A5FB4', 100)
        check('大写 #RRGGBB 合法', res['success'] is True)

        # 6. 工作区数值合理（左上<=右下，非零）
        try:
            l, t, rt, b = reader.BookReader._work_area()
            check('工作区数值合理', l <= rt - 100 and t <= b - 100)
        except Exception as e:
            check('工作区数值合理(异常:%s)' % e, False)

        # 7. 设置打开期间保存新尺寸 → _reader_size 更新尺寸保留位置
        class FakeWin:
            x, y, width, height = 10, 20, 300, 60
            def resize(self, w, h): self.width, self.height = w, h
            def move(self, x, y): self.x, self.y = x, y
        r2 = make_reader(tmp)
        r2._window = FakeWin()
        r2.open_settings()
        check('打开设置记录原位置', r2._reader_size == (10, 20, 300, 60))
        r2.apply_settings(500, 120, 50, None)
        check('设置期间保存更新尺寸保留位置', r2._reader_size == (10, 20, 500, 120))
        r2.close_settings()
        check('关闭设置恢复位置尺寸', (r2._window.x, r2._window.y, r2._window.width, r2._window.height) == (10, 20, 500, 120))
        check('关闭后状态清空', r2._reader_size is None)

        # 8. 贴边场景：窗口在右下角 → open_settings 平移进工作区
        wa = reader.BookReader._work_area()
        fw = FakeWin()
        fw.x, fw.y = wa[2] - 10, wa[3] - 10  # 贴右下角
        r3 = make_reader(tmp)
        r3._window = fw
        r3.open_settings()
        W, H = reader.BookReader.SETTINGS_SIZE
        inside = (fw.x + W <= wa[2] + 1) and (fw.y + H <= wa[3] + 1)
        check('贴右下角时设置窗口被平移进工作区', inside)
        r3.close_settings()
        check('关闭后移回右下角原位', (fw.x, fw.y) == (wa[2] - 10, wa[3] - 10))

    total, passed = len(results), sum(results)
    print('\n总结: %s (%d/%d 项)' % ('全部通过' if passed == total else '有失败', passed, total))
    return passed == total


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
