# -*- coding: utf-8 -*-
"""exe 端到端拖动冒烟：真 Win32 鼠标事件按下-移动-抬起，验证窗口真实位移。

运行：_build_venv/Scripts/python.exe tests/test_drag_exe.py [exe路径]
默认测 dist/MoyuReader_v2.1.7.exe。
"""
import subprocess
import sys
import time
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
EXE = sys.argv[1] if len(sys.argv) > 1 else r"D:\CC研究一下？\摸鱼阅读器\dist\MoyuReader_v2.1.7.exe"
TITLE = "摸鱼阅读器"


def find_window(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, TITLE)
        if hwnd:
            return hwnd
        time.sleep(0.5)
    return None


def rect_of(hwnd):
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def child_pids(root_pid):
    """Toolhelp32Snapshot 枚举 root_pid 的全部子进程（onefile 引导进程的应用子进程）。"""
    TH32CS_SNAPPROCESS = 0x2
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD),
                    ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', ctypes.c_long),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_wchar * 260)]
    snap = user32 and ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return set()
    children = set()
    parents = {}
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    ok = ctypes.windll.kernel32.Process32FirstW(snap, ctypes.byref(entry))
    while ok:
        parents[entry.th32ProcessID] = entry.th32ParentProcessID
        ok = ctypes.windll.kernel32.Process32NextW(snap, ctypes.byref(entry))
    ctypes.windll.kernel32.CloseHandle(snap)
    # 闭包式下钻：从 root 往下收所有后代
    frontier = {root_pid}
    while frontier:
        found = {p for p, par in parents.items() if par in frontier and p not in children}
        children |= found
        frontier = found
    return children


def main():
    proc = subprocess.Popen([EXE])
    try:
        hwnd = find_window()
        if not hwnd:
            print("FAIL - 未找到窗口（exe 未启动成功？）")
            return 1
        # 窗口归属校验：窗口必须属于刚启动的进程树，排除历史孤儿窗口
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        own_pids = {proc.pid} | child_pids(proc.pid)
        if pid.value not in own_pids:
            print(f"FAIL - 找到的窗口属于别的进程 PID={pid.value}（历史孤儿？），本进程树={sorted(own_pids)}")
            return 1
        print(f"窗口归属正确: PID={pid.value}")
        time.sleep(3.0)  # 等 JS 与 pywebview 注入完成（exe 冷启动更慢，给足）

        def attempt_drag(label):
            """一轮真实拖动；返回位移。"""
            r = rect_of(hwnd)
            cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
            # 拖动方向朝屏幕中心，避免把窗口拖出屏
            sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
            ddx = 150 if cx < sw // 2 else -150
            ddy = 90 if cy < sh // 2 else -90
            # 鼠标进窗（若感应模式隐藏中，给恢复时间）
            user32.SetCursorPos(cx, cy)
            time.sleep(1.2)
            # 复核光标没被真实鼠标抢走
            cur = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(cur))
            if (cur.x, cur.y) != (cx, cy):
                print(f"[{label}] 光标被真实鼠标移动（{cur.x},{cur.y}），本轮结果不可信")
                return None, (ddx, ddy)
            LEFTDOWN, LEFTUP = 0x0002, 0x0004
            user32.mouse_event(LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.08)
            steps = 12
            for i in range(1, steps + 1):
                user32.SetCursorPos(cx + ddx * i // steps, cy + ddy * i // steps)
                time.sleep(0.03)
            user32.mouse_event(LEFTUP, 0, 0, 0, 0)
            time.sleep(1.2)
            r2 = rect_of(hwnd)
            moved = (r2[0] - r[0], r2[1] - r[1]) if r2 else None
            print(f"[{label}] 位移: {moved}  期望: ({ddx}, {ddy})")
            return moved, (ddx, ddy)

        moved, expect = attempt_drag('第1轮')
        if moved is None or not (abs(moved[0] - expect[0]) <= 6 and abs(moved[1] - expect[1]) <= 6):
            # 首轮失败：再等 3 秒做第 2 轮（排除冷启动 JS 桥未就绪）
            time.sleep(3.0)
            moved, expect = attempt_drag('第2轮')

        r1 = rect_of(hwnd)
        if r1 is None:
            print("FAIL - 拖动后取不到窗口矩形")
            return 1
        ok = moved is not None and abs(moved[0] - expect[0]) <= 6 and abs(moved[1] - expect[1]) <= 6
        print("PASS - exe 真实鼠标拖动正常" if ok else "FAIL - 窗口未跟随移动")
        return 0 if ok else 1
    finally:
        # 杀整棵进程树（onefile 的应用进程是子进程，terminate 只杀引导进程会留孤儿）
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)],
                       capture_output=True)


if __name__ == "__main__":
    sys.exit(main())
