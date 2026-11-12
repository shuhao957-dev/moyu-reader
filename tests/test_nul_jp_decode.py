# -*- coding: utf-8 -*-
"""NUL 尾巴损坏文件 + 日文 cp932 解码回归（不影响项目文件）"""
import sys, types, tempfile, os
from pathlib import Path

for name in ('webview', 'ebooklib', 'ebooklib.epub', 'bs4', 'settings'):
    m = types.ModuleType(name)
    sys.modules[name] = m
sys.modules['ebooklib'].epub = sys.modules['ebooklib.epub']
sys.modules['ebooklib.epub'].read_epub = lambda *a, **k: None
sys.modules['bs4'].BeautifulSoup = object
sys.modules['settings'].get_settings_html = lambda: ''

sys.path.insert(0, r'D:\CC研究一下？\摸鱼阅读器')
import importlib

results = []
def check(module_name, label, raw, expect_substr, forbid='\x00'):
    mod = importlib.import_module(module_name)
    BookReader = mod.BookReader
    tmp = Path(tempfile.mkdtemp())
    p = tmp / f'{module_name}_{abs(hash(label))}.txt'
    p.write_bytes(raw)
    r = object.__new__(BookReader)
    r.load_txt(str(p))
    ok = expect_substr in r.content
    no_nul = forbid not in r.content
    results.append((module_name, label, ok and no_nul))
    preview = r.content[:28].replace('\n', ' ')
    print(f'{"PASS" if ok and no_nul else "FAIL"}  [{module_name}] {label}')
    print(f'       预览: {preview}  (含NUL={not no_nul})')

# 1) 真实坏文件：正文 GB18030 + 尾部 1.5MB NUL（项目里那份网络小说）
real = Path(r'D:\CC研究一下？\摸鱼阅读器\[番全]《我靠崩人设在男主手中苟命》作者：云非邪(2).txt')
if real.exists():
    raw = real.read_bytes()
    check('reader', '真实NUL尾巴文件(gb18030+1.5MB NUL)', raw, '我靠崩人设在男主手中苟命')
else:
    print('SKIP 真实文件不存在')

# 2) 生成的日文 cp932 文件（含假名+汉字）
jp = '初めまして、今日はいい天気です。第二章では猫と魚の話をする。'
check('reader', '日文cp932(假名+汉字)', jp.encode('cp932'), '初めまして')

# 3) 中文 gb18030 回归：必须仍是正确中文，不被误判成日文
cn = '第一章 今天也要努力摸鱼\n这是正文内容，需要能正常显示中文。'
check('reader', '中文gb18030回归', cn.encode('gb18030'), '今天也要努力摸鱼')

# 4) 中文 gbk 回归
check('reader', '中文gbk回归', cn.encode('gbk'), '今天也要努力摸鱼')

# 5) UTF-8 无 BOM 回归
check('reader', 'utf-8无BOM回归', cn.encode('utf-8'), '今天也要努力摸鱼')

overall = all(ok for *_, ok in results)
print('\n最终结论:', '全部通过' if overall else '存在失败项')
sys.exit(0 if overall else 1)
