# -*- coding: utf-8 -*-
"""测试鼠标感应模式：配置读写、控制器线程生命周期、开关切换。不碰 GUI。"""
import sys, types, tempfile, threading, time
from pathlib import Path

# 桩掉 GUI/epub 依赖，只测本体
for name in ('webview', 'ebooklib', 'ebooklib.epub', 'bs4'):
    m = types.ModuleType(name)
    sys.modules[name] = m
sys.modules['ebooklib'].epub = sys.modules['ebooklib.epub']
sys.modules['ebooklib.epub'].read_epub = lambda *a, **k: None
sys.modules['bs4'].BeautifulSoup = object

PROJ = Path(r'D:\CC研究一下？\摸鱼阅读器')
sys.path.insert(0, str(PROJ))
from reader import BookReader, MouseSenseController

results = []
def check(name, ok, detail=''):
    results.append(ok)
    print(f'{"PASS" if ok else "FAIL"}  {name}' + (f'  {detail}' if detail and not ok else ''))

tmp = Path(tempfile.mkdtemp())

# 1. 默认配置含 mouse_sense=False
r = BookReader(data_dir=tmp)
check('默认配置 mouse_sense=False', r.config.get('mouse_sense') is False)

# 2. 旧配置文件（无 mouse_sense 键）能正常加载，get 回退 False
(tmp / '.moyu_reader_config.json').write_text(
    '{"window": {"width": 400, "height": 60, "x": 1, "y": 1}, "speed": 30}', encoding='utf-8')
r2 = BookReader(data_dir=tmp)
check('旧配置兼容（无键回退 False）', r2.config.get('mouse_sense', False) is False)

# 3. 控制器线程生命周期：开→单线程运行，关→线程退出
ctrl = r2.sense
ctrl.set_enabled(True)
time.sleep(0.3)
threads = [t for t in threading.enumerate() if t.name == 'moyu-mouse-sense']
check('开启后线程运行', len(threads) == 1)
check('enabled 状态', ctrl.enabled is True)
ctrl.set_enabled(True)  # 重复开启不应起第二条线程
threads = [t for t in threading.enumerate() if t.name == 'moyu-mouse-sense']
check('重复开启不重复起线程', len(threads) == 1)
ctrl.set_enabled(False)
time.sleep(0.5)
threads = [t for t in threading.enumerate() if t.name == 'moyu-mouse-sense' and t.is_alive()]
check('关闭后线程退出', len(threads) == 0)
check('关闭后 enabled=False', ctrl.enabled is False)

# 4. toggle 切换
before = ctrl.enabled
ctrl.toggle()
time.sleep(0.2)
check('toggle 翻转', ctrl.enabled is (not before))
ctrl.toggle()
time.sleep(0.3)

# 5. apply_settings 带mouse_sense：写入配置 + 联动控制器
res = r2.apply_settings(400, 60, 30, True)
check('apply_settings 成功', res.get('success') is True)
check('配置已写 mouse_sense=True', r2.config.get('mouse_sense') is True)
time.sleep(0.2)
check('控制器随设置开启', r2.sense.enabled is True)
r2.sense.set_enabled(False)
time.sleep(0.3)

# 6. apply_settings 不传 mouse_sense：保持现有值
res = r2.apply_settings(500, 80, 40)
check('不传时配置保留 mouse_sense', res.get('success') is True and r2.config.get('mouse_sense') is True)
r2.sense.set_enabled(False)
time.sleep(0.3)

# 7. suspend/resume 不误伤未开启状态
r3 = BookReader(data_dir=tmp)
r3.sense.suspend()  # 未开启时应是 no-op，不抛异常
r3.sense.resume()
check('suspend/resume 对未开启模式无副作用', r3.sense.enabled is False)

print()
print('总结:', '全部通过' if all(results) else f'{results.count(False)} 项失败', f'({len(results)} 项)')
sys.exit(0 if all(results) else 1)
