# -*- coding: utf-8 -*-
"""测试 reader.py / reader_v2.py 的 load_txt 编码自动检测（不影响项目文件）"""
import sys, types, tempfile, os
from pathlib import Path

# 桩掉 GUI/epub/settings 依赖，只测 BookReader.load_txt 本体
for name in ('webview', 'ebooklib', 'ebooklib.epub', 'bs4', 'settings'):
    m = types.ModuleType(name)
    sys.modules[name] = m
sys.modules['ebooklib'].epub = sys.modules['ebooklib.epub']
sys.modules['ebooklib.epub'].read_epub = lambda *a, **k: None
sys.modules['bs4'].BeautifulSoup = object
sys.modules['settings'].get_settings_html = lambda: ''

sys.path.insert(0, r'D:\CC研究一下？\摸鱼阅读器')
import importlib

text = '第一章 今天也要努力摸鱼\n这是正文内容，需要能正常显示中文。'

cases = {
    'utf-8(无BOM)': text.encode('utf-8'),
    'utf-8-sig(记事本UTF-8)': b'\xef\xbb\xbf' + text.encode('utf-8'),
    'utf-16(记事本Unicode,带BOM)': text.encode('utf-16'),   # python utf-16 自带 BOM
    'utf-16-le(无BOM)': text.encode('utf-16-le'),
    'gbk(老式ANSI)': text.encode('gbk'),
    'gb18030(生僻字㦡)': '这是个生僻字㦡测试'.encode('gb18030'),
}

tmp = Path(tempfile.mkdtemp())
overall = True
for module_name in ('reader', 'reader_v2'):
    mod = importlib.import_module(module_name)
    BookReader = mod.BookReader
    print(f'--- {module_name}.py load_txt 测试 ---')
    all_ok = True
    for name, raw in cases.items():
        p = tmp / f'{module_name}_{abs(hash(name))}.txt'
        p.write_bytes(raw)
        r = object.__new__(BookReader)  # 跳过 __init__，不碰进度文件
        r.load_txt(str(p))
        ok = text in r.content or '㦡' in r.content
        all_ok = all_ok and ok
        preview = r.content[:24].replace('\n', ' ')
        print(f'{"PASS" if ok else "FAIL"}  {name:28s} -> {preview}')

    # 模拟朋友的问题场景：UTF-16 文件，旧逻辑必然乱码
    p16 = tmp / f'{module_name}_friend.txt'
    p16.write_bytes(text.encode('utf-16'))
    r = object.__new__(BookReader)
    r.load_txt(str(p16))
    ok16 = text in r.content
    all_ok = all_ok and ok16
    print('朋友场景(UTF-16记事本文件)结果:', '正常' if ok16 else '仍乱码: ' + r.content[:30])
    print(f'{module_name}.py 总结:', '全部通过' if all_ok else '有失败项', '\n')
    overall = overall and all_ok

print('最终结论:', '两份文件全部通过' if overall else '存在失败项')
sys.exit(0 if overall else 1)
