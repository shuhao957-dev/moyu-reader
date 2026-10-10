"""Live Windows/WebView2 regression check; run on an unlocked desktop.

Uses the real reader window over a solid-color native window. Pixel samples
must follow that window's color, so checking CSS alpha alone cannot pass.
No books or user configuration are loaded. Only project dependencies are used.
"""

import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import webview
import reader


def main():
    if sys.platform != 'win32':
        raise SystemExit('This check requires Windows and an unlocked desktop.')

    data_dir = tempfile.TemporaryDirectory(prefix='moyu-regression-')
    api = reader.BookReader(data_dir.name)
    window = reader.create_reader_window(api)
    backdrop = None
    failures = []
    background = (17, 201, 127)

    def wait_js(condition):
        deadline = time.monotonic() + 5
        while not window.evaluate_js(condition):
            if time.monotonic() >= deadline:
                raise AssertionError(f'Timed out waiting for {condition}')
            time.sleep(0.1)

    def open_settings():
        window.run_js("document.getElementById('settings-btn').click()")
        wait_js("settingsOpen && !settingsBusy && !document.getElementById('moyu-settings').hidden")

    def save_settings(width, height, speed):
        window.run_js(f"setSetting('width', {width}); setSetting('height', {height}); setSetting('speed', {speed}); document.getElementById('settings-save').click()")
        wait_js("!settingsOpen && !settingsBusy")

    def on_ui(callback):
        from System import Action
        window.native.Invoke(Action(callback))

    def pixels():
        from System.Drawing import Bitmap, Graphics, Size

        rectangle = []
        on_ui(lambda: rectangle.append(
            window.native.RectangleToScreen(window.native.ClientRectangle)
        ))
        rect = rectangle[0]
        bitmap = Bitmap(1, 1)
        graphics = Graphics.FromImage(bitmap)
        try:
            values = []
            for fraction in (0.1, 0.5, 0.9):
                graphics.CopyFromScreen(
                    rect.Left + int(rect.Width * fraction),
                    rect.Top + int(rect.Height * 0.8), 0, 0, Size(1, 1)
                )
                color = bitmap.GetPixel(0, 0)
                values.append((color.R, color.G, color.B))
            return values
        finally:
            graphics.Dispose()
            bitmap.Dispose()

    def expect_transparent(label):
        # Allow WebView2/DWM to present the new frame, then check actual pixels.
        time.sleep(0.3)
        deadline = time.monotonic() + 2
        actual = pixels()
        while actual != [background] * 3 and time.monotonic() < deadline:
            time.sleep(0.1)
            actual = pixels()
        if actual != [background] * 3:
            raise AssertionError(f'{label}: expected {background}, got {actual}')
        print(f'PASS {label}', flush=True)

    def expect_mouse_target():
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL('user32')
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        state = []
        def read():
            rect = window.native.RectangleToScreen(window.native.ClientRectangle)
            state.append((window.native.Handle.ToInt64(), rect.Left, rect.Top))
        on_ui(read)
        handle, left, top = state[0]
        for x, y in ((12, 12), (200, 80)):
            target = user32.WindowFromPoint(wintypes.POINT(left + x, top + y))
            if user32.GetAncestor(target, 2) != handle:  # GA_ROOT
                raise AssertionError('Reader became click-through to the window behind it.')
        print('PASS native mouse targets text and transparent area', flush=True)

    def run():
        nonlocal backdrop, background
        try:
            if not window.events.loaded.wait(20):
                raise RuntimeError('Reader did not load within 20 seconds.')
            if webview.renderer != 'edgechromium':
                raise RuntimeError('Install Microsoft Edge WebView2 Runtime first.')
            wait_js("typeof settingsOpen !== 'undefined' && scrollSpeed === 50")

            def create_backdrop():
                nonlocal backdrop
                from System.Drawing import Color, Point, Size
                from System.Windows.Forms import Form, FormBorderStyle, FormStartPosition

                backdrop = Form()
                backdrop.Text = 'Moyu transparency test backdrop'
                backdrop.FormBorderStyle = getattr(FormBorderStyle, 'None')
                backdrop.StartPosition = FormStartPosition.Manual
                backdrop.Location = Point(80, 80)
                backdrop.Size = Size(1000, 750)
                backdrop.BackColor = Color.FromArgb(*background)
                backdrop.ShowInTaskbar = False
                backdrop.TopMost = True
                backdrop.Show()
                window.native.BringToFront()

            on_ui(create_backdrop)
            expect_transparent('startup')
            window.resize(600, 120)
            expect_transparent('resize larger')
            window.resize(400, 60)
            expect_transparent('resize smaller')
            window.minimize()
            time.sleep(0.3)
            window.restore()
            expect_transparent('minimize and restore')
            window.move(140, 140)
            expect_transparent('move')
            window.hide()
            time.sleep(0.2)
            window.show()
            expect_transparent('hide and show')

            # Prove that we see the live window behind, not stale painted pixels.
            background = (42, 110, 213)
            def recolor():
                from System.Drawing import Color
                backdrop.BackColor = Color.FromArgb(*background)
                backdrop.Refresh()
            on_ui(recolor)
            expect_transparent('background changes behind reader')

            expect_transparent('built-in settings hidden')
            body_style = window.evaluate_js('''({
                color: getComputedStyle(document.body).backgroundColor,
                image: getComputedStyle(document.body).backgroundImage
            })''')
            if body_style != {'color': 'rgba(0, 0, 0, 0)', 'image': 'none'}:
                raise AssertionError(f'Settings changed the reader background: {body_style}')

            window.run_js("content = 'A test book. '.repeat(100); document.getElementById('text-content').textContent = content; startScroll()")
            wait_js('currentPosition > 0')
            original_size = (window.width, window.height)
            open_settings()
            if len(webview.windows) != 1:
                raise AssertionError('Settings opened a second WebView window.')
            if window.evaluate_js('''(() => {
                let escaped = false;
                const listener = () => { escaped = true; };
                window.addEventListener('mousedown', listener);
                document.getElementById('settings-width').dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                window.removeEventListener('mousedown', listener);
                return escaped;
            })()'''):
                raise AssertionError('Editing settings triggered the window drag handler.')
            print('PASS settings inputs do not drag the window', flush=True)
            position = window.evaluate_js('currentPosition')
            time.sleep(0.5)
            if not window.evaluate_js('isPaused') or window.evaluate_js('currentPosition') != position:
                raise AssertionError('Reading continued while settings were open.')
            if pixels() == [background] * 3:
                raise AssertionError('The visible settings panel should paint its own background.')
            print('PASS settings open in the same window and pause reading', flush=True)
            window.run_js("setSetting('width', 777); document.getElementById('settings-cancel').click()")
            wait_js('!settingsOpen && !settingsBusy && !isPaused')
            if (window.width, window.height) != original_size or api.config_file.exists():
                raise AssertionError('Cancel changed the reader size or saved configuration.')
            window.run_js("content = ''; document.getElementById('text-content').textContent = ''")
            expect_transparent('cancel settings and resume transparent reading')

            open_settings()
            save_settings(600, 120, 95)
            expect_transparent('save settings and return to transparent reading')
            saved = json.loads(api.config_file.read_text(encoding='utf-8'))
            if (window.width, window.height) != (600, 120) or window.evaluate_js('scrollSpeed') != 95:
                raise AssertionError('Saved settings did not take effect immediately.')
            if saved['window']['width'] != 600 or saved['window']['height'] != 120 or saved['speed'] != 95:
                raise AssertionError(f'Unexpected saved configuration: {saved}')
            if reader.BookReader(data_dir.name).config != saved:
                raise AssertionError('Saved settings did not survive a new reader instance.')
            print('PASS dimensions and speed apply immediately and persist', flush=True)

            window.run_js("document.dispatchEvent(new KeyboardEvent('keydown', {key:',', ctrlKey:true}))")
            wait_js('settingsOpen && !settingsBusy')
            if window.evaluate_js("document.getElementById('settings-width').value") != '600':
                raise AssertionError('Reopened settings did not show the saved width.')
            window.run_js("setSetting('width', 4999); document.getElementById('settings-save').click()")
            time.sleep(0.2)
            if not window.evaluate_js('settingsOpen') or api.apply_settings(4999, 120, 95)['success']:
                raise AssertionError('Out-of-range dimensions were accepted.')
            window.run_js("document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape'}))")
            wait_js('!settingsOpen && !settingsBusy')
            expect_transparent('Ctrl+, opens settings; Escape cancels invalid input')

            window.minimize()
            time.sleep(0.3)
            window.restore()
            expect_transparent('minimize and restore after applying settings')
            expect_mouse_target()

            # Keep the reader's own controls functional after settings CSS loads.
            mode = window.evaluate_js("document.getElementById('mode-btn').click(); document.getElementById('mode-btn').textContent")
            if mode != '手动':
                raise AssertionError(f'Reader mode control stopped working: {mode}')
            print('PASS reader controls after loading settings CSS', flush=True)
            open_settings()
            save_settings(400, 30, 95)
            if (window.width, window.height) != (400, 30):
                raise AssertionError('Single-line dimensions were clamped to the old minimum.')
            expect_transparent('single-line size saved through built-in settings')
        except Exception:
            failures.append(traceback.format_exc())
        finally:
            try:
                if backdrop is not None:
                    on_ui(backdrop.Close)
            finally:
                window.destroy()

    webview.start(run)
    data_dir.cleanup()
    if failures:
        raise SystemExit('\n'.join(failures))
    print('All Windows transparency checks passed.')


if __name__ == '__main__':
    main()
