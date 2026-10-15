# -*- coding: utf-8 -*-
"""v2.1.2 回归测试：畸形编码文件绝不能让 load_txt 抛异常（v2.1.1 的 bug）"""
import sys, types, tempfile
from pathlib import Path

for name in ('webview', 'ebooklib', 'ebooklib.epub', 'bs4', 'settings'):
    sys.modules[name] = types.ModuleType(name)
sys.modules['ebooklib'].epub = sys.modules['ebooklib.epub']
sys.modules['ebooklib.epub'].read_epub = lambda *a, **k: None
sys.modules['bs4'].BeautifulSoup = object
sys.modules['settings'].get_settings_html = lambda: ''

sys.path.insert(0, r'D:\CC研究一下？\摸鱼阅读器')
import importlib

text = '第一章 今天也要努力摸鱼\n这是正文内容，测试用。'

pathological = {
    # v2.1.1 会抛异常的三大场景
    'UTF-16带BOM+奇数字节': text.encode('utf-16')[:-1],
    'UTF-8 BOM+GBK正文': b'\xef\xbb\xbf' + text.encode('gbk'),
    'UTF-16带BOM+孤立代理': text.encode('utf-16') + b'\x00\xd8',
    # 其他离谱输入
    '随机二进制': bytes(range(256)) * 4,
    '空文件': b'',
    '只有BOM': b'\xff\xfe',
    '奇数个字节的纯GBK': text.encode('gbk') + b'\xd6',
}

tmp = Path(tempfile.mkdtemp())
overall = True
for module_name in ('reader', 'reader_v2'):
    BookReader = importlib.import_module(module_name).BookReader
    print(f'--- {module_name}.py 畸形文件测试 ---')
    for name, raw in pathological.items():
        p = tmp / f'{module_name}_{name}.txt'
        p.write_bytes(raw)
        r = object.__new__(BookReader)
        try:
            r.load_txt(str(p))
            ok = isinstance(r.content, str)
        except Exception as e:
            ok = False
            name += f'  <-- 抛了 {type(e).__name__}!'
        overall = overall and ok
        print(f'{"PASS" if ok else "FAIL"}  {name}')

    # 可读性抽检：截断的 UTF-16 应该还能读出正文（替换坏字符）
    p = tmp / f'{module_name}_truncated.txt'
    p.write_bytes(text.encode('utf-16')[:-1])
    r = object.__new__(BookReader)
    r.load_txt(str(p))
    readable = '摸鱼' in r.content
    overall = overall and readable
    print(f'{"PASS" if readable else "FAIL"}  截断UTF-16正文可读 -> {r.content[:24]}')
    print()

print('最终结论:', '全部通过，load_txt 已不会抛异常' if overall else '仍有失败项！')
sys.exit(0 if overall else 1)
