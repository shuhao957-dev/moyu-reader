"""Settings panel embedded in the reader's existing WebView window."""


def get_settings_html():
    return """
<style>
    body.settings-open #container { visibility: hidden; }
    body.settings-open #controls { display: none; }
    #moyu-settings[hidden] { display: none; }
    #moyu-settings, #moyu-settings * { box-sizing: border-box; }
    #moyu-settings {
        position: fixed;
        inset: 0;
        z-index: 2000;
        overflow: auto;
        padding: 12px;
        color: #333;
        background: #f7f7f8;
        -webkit-app-region: no-drag;
    }
    #moyu-settings .settings-card {
        max-width: 380px;
        margin: 0 auto;
        padding: 14px 16px;
        background: white;
        border: 1px solid #e3e3e6;
        border-radius: 8px;
        box-shadow: 0 4px 14px rgba(0,0,0,0.08);
    }
    #moyu-settings h1 { font-size: 16px; margin: 0 0 8px; }
    #moyu-settings label { display: block; font-weight: normal; font-size: 13px; margin: 8px 0 3px; }
    #moyu-settings .check-row {
        display: flex; align-items: center; gap: 8px;
        font-weight: normal; font-size: 13px; margin: 10px 0 2px; cursor: pointer;
    }
    #moyu-settings .check-row input { width: auto; flex: none; }
    #moyu-settings .check-hint { color: #888; font-size: 11px; margin: 2px 0 0 26px; }
    #moyu-settings .mini-hint { color: #888; font-size: 11px; margin: 2px 0 0; }
    #moyu-settings input {
        width: 100%; padding: 5px 7px; font-size: 13px;
        border: 1px solid #ccc; border-radius: 5px;
        user-select: text;
    }
    #moyu-settings input[type="color"] { padding: 2px; height: 30px; flex: 1; }
    #moyu-settings input[type="range"] { padding: 0; accent-color: #666; }
    #moyu-settings .presets { display: flex; gap: 6px; margin-top: 5px; }
    #moyu-settings button {
        margin: 0; padding: 5px 9px; font-size: 12px;
        border: 1px solid #ddd; border-radius: 5px; cursor: pointer;
        background: #f3f4f8; color: #333;
    }
    #moyu-settings .presets button { flex: 1; }
    #moyu-settings .inline-row { display: flex; gap: 6px; align-items: center; }
    #moyu-settings .swatch {
        width: 24px; height: 24px; padding: 0; flex: none;
        border-radius: 5px; border: 1px solid #bbb;
    }
    #moyu-settings .opacity-row { display: flex; align-items: center; gap: 8px; }
    #moyu-settings .opacity-row input { flex: 1; }
    #moyu-settings .opacity-val { width: 42px; text-align: right; font-size: 12px; color: #555; flex: none; }
    #moyu-settings .actions { display: flex; gap: 8px; margin-top: 12px; }
    #moyu-settings .actions button { flex: 1; }
    #moyu-settings #settings-save { background: #555b66; border-color: #555b66; color: white; }
    #moyu-settings .hint { margin-top: 8px; color: #888; font-size: 11px; }
    #moyu-settings #settings-error { color: #b42318; margin-top: 8px; font-size: 12px; }
</style>
<section id="moyu-settings" hidden aria-label="阅读设置">
    <form class="settings-card" id="settings-form">
        <h1>阅读设置</h1>
        <label for="settings-width">窗口宽度（px）</label>
        <input id="settings-width" type="number" min="150" max="1200" step="1" required>
        <div class="presets">
            <button type="button" onclick="setSetting('width', 200)">窄 · 200</button>
            <button type="button" onclick="setSetting('width', 400)">中 · 400</button>
            <button type="button" onclick="setSetting('width', 600)">宽 · 600</button>
        </div>
        <label for="settings-height">窗口高度（px）</label>
        <input id="settings-height" type="number" min="20" max="600" step="1" required>
        <div class="presets">
            <button type="button" onclick="setSetting('height', 30)">一行 · 30</button>
            <button type="button" onclick="setSetting('height', 60)">两行 · 60</button>
            <button type="button" onclick="setSetting('height', 120)">多行 · 120</button>
        </div>
        <label for="settings-speed">滚动速度</label>
        <input id="settings-speed" type="number" min="10" max="200" step="1" required>
        <label for="settings-font-size">文字字号（px）</label>
        <input id="settings-font-size" type="number" min="10" max="48" step="1" required>
        <div class="presets">
            <button type="button" onclick="setSetting('font-size', 12)">小 · 12</button>
            <button type="button" onclick="setSetting('font-size', 16)">中 · 16</button>
            <button type="button" onclick="setSetting('font-size', 22)">大 · 22</button>
        </div>
        <label for="settings-color">文字颜色</label>
        <div class="inline-row">
            <input id="settings-color" type="color" value="#333333">
            <button type="button" class="swatch" style="background:#333333" title="深灰" onclick="setColor('#333333')"></button>
            <button type="button" class="swatch" style="background:#000000" title="纯黑" onclick="setColor('#000000')"></button>
            <button type="button" class="swatch" style="background:#1a5fb4" title="藏蓝" onclick="setColor('#1a5fb4')"></button>
            <button type="button" class="swatch" style="background:#b33a3a" title="暗红" onclick="setColor('#b33a3a')"></button>
        </div>
        <label for="settings-opacity">文字不透明度（%）</label>
        <div class="opacity-row">
            <input id="settings-opacity" type="range" min="20" max="100" step="5" value="100"
                   oninput="document.getElementById('settings-opacity-val').textContent = this.value + '%'">
            <span class="opacity-val" id="settings-opacity-val">100%</span>
        </div>
        <p class="mini-hint">调低后文字变淡，可透出后面的工作内容。</p>
        <label class="check-row" for="settings-mouse-sense">
            <input id="settings-mouse-sense" type="checkbox">
            鼠标感应模式
        </label>
        <p class="check-hint">开启后：鼠标离开窗口 0.5 秒自动隐藏并暂停滚动，点击可穿透到下层窗口；鼠标移回即恢复。Ctrl+H 可随时开关。</p>
        <label class="check-row" for="settings-progress-bar">
            <input id="settings-progress-bar" type="checkbox">
            显示底部进度条
        </label>
        <p class="check-hint">底部 3px 半透明细条，显示当前阅读位置，点击条上任意位置可跳转。</p>
        <label for="settings-jump-pct">跳转到（全书百分比）</label>
        <div class="inline-row">
            <input id="settings-jump-pct" type="number" min="0" max="100" step="1" placeholder="0 – 100">
            <button type="button" id="settings-jump-btn" onclick="doPercentJump()">跳转</button>
        </div>
        <p class="mini-hint">百分比按全书高度估算，配合底部进度条使用更直观。</p>
        <details class="hotkeys">
            <summary>快捷键速查</summary>
            <ul>
                <li><kbd>Ctrl+F</kbd> 搜索全书（Enter 下一处，Shift+Enter 上一处，Esc 关闭）</li>
                <li><kbd>Ctrl+T</kbd> 打开目录，点章节直达（Esc 关闭）</li>
                <li><kbd>Ctrl+,</kbd> 打开本设置面板</li>
                <li><kbd>Ctrl+H</kbd> 鼠标感应模式开关</li>
                <li><kbd>空格</kbd> / <kbd>Enter</kbd>：自动模式=暂停/继续滚动（打开书默认暂停起步，按空格开滚）；手动模式=下一页</li>
                <li><kbd>任意字母键</kbd> / 方向键 / PageUp·Down：手动模式翻页</li>
                <li><kbd>Esc</kbd> 关闭面板；无面板打开时退出阅读器</li>
            </ul>
        </details>
        <p id="settings-error" role="alert"></p>
        <div class="actions">
            <button type="button" id="settings-cancel" onclick="closeSettings()">取消</button>
            <button type="submit" id="settings-save">保存并返回</button>
        </div>
        <p class="hint">保存后立即生效。Esc 或点击空白处返回阅读，Ctrl+H 切换鼠标感应模式。</p>
    </form>
</section>
<script>
    let settingsOpen = false;
    let settingsBusy = false;
    let settingsWasPaused = false;

    // Keep pywebview's easy-drag handler from moving the window while editing.
    document.getElementById('moyu-settings').addEventListener('mousedown', (event) => {
        event.stopPropagation();
    });
    // Escape hatch: clicking the blank area around the card closes settings.
    document.getElementById('moyu-settings').addEventListener('click', (event) => {
        if (event.target === document.getElementById('moyu-settings')) closeSettings();
    });

    function setSetting(name, value) {
        document.getElementById('settings-' + name).value = value;
    }

    function setColor(color) {
        document.getElementById('settings-color').value = color;
    }

    async function openSettings() {
        if (settingsOpen || settingsBusy) return;
        // 先关掉搜索条/目录（各自恢复暂停与窗口状态），避免两套记账打架；
        // closeToc 涉及窗口恢复必须 await 完，否则撑窗尺寸互相踩
        if (typeof closeSearch === 'function') closeSearch();
        if (typeof closeToc === 'function') { try { await closeToc(); } catch (e) {} }
        settingsBusy = true;
        settingsOpen = true;
        settingsWasPaused = isPaused;
        if (!isPaused) togglePause();
        try {
            const config = await pywebview.api.open_settings();
            setSetting('width', config.window.width);
            setSetting('height', config.window.height);
            setSetting('speed', scrollSpeed);
            setSetting('font-size', config.font_size || 14);
            document.getElementById('settings-color').value = config.text_color || '#333333';
            document.getElementById('settings-opacity').value = config.text_opacity || 100;
            document.getElementById('settings-opacity-val').textContent = (config.text_opacity || 100) + '%';
            document.getElementById('settings-mouse-sense').checked = !!config.mouse_sense;
            document.getElementById('settings-progress-bar').checked = !!config.progress_bar;
            document.getElementById('settings-error').textContent = '';
            document.body.classList.add('settings-open');
            document.getElementById('moyu-settings').hidden = false;
            document.getElementById('settings-width').focus();
        } catch (error) {
            settingsOpen = false;
            if (!settingsWasPaused && isPaused) togglePause();
            alert('打开设置失败：' + error);
        } finally {
            settingsBusy = false;
        }
    }

    async function finishSettings() {
        await pywebview.api.close_settings();
        document.getElementById('moyu-settings').hidden = true;
        document.body.classList.remove('settings-open');
        settingsOpen = false;
        if (!isAutoMode && content) {
            // 字号可能已改（行高变了），页首重新对齐行边界。
            // v2.1.7 分页重写删掉了 updatePageInfo，这里的旧调用其实是潜伏的
            // ReferenceError，一直靠外层 catch 吞掉才没露馅——现在改为显式对齐
            currentPosition = lineFloor(currentPosition);
            updatePagePosition();
            updateProgressBar();
        }
        if (!settingsWasPaused && isPaused) togglePause();
    }

    // 百分比跳转：关面板 → 回到阅读窗 → 跳（jumpToPercent 由主脚本提供）
    async function doPercentJump() {
        if (settingsBusy) return;
        if (!content) {
            document.getElementById('settings-error').textContent = '还没有打开电子书，跳不了。';
            return;
        }
        const raw = document.getElementById('settings-jump-pct').value;
        const v = Number(raw);
        if (raw === '' || !(v >= 0 && v <= 100)) {
            document.getElementById('settings-error').textContent = '百分比须为 0–100。';
            document.getElementById('settings-jump-pct').focus();
            return;
        }
        document.getElementById('settings-error').textContent = '';
        await closeSettings();
        jumpToPercent(v);
    }
    // 输入框里按回车 = 跳转（拦截隐式表单提交，防误触"保存并返回"）
    document.getElementById('settings-jump-pct').addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            doPercentJump();
        }
    });

    async function closeSettings() {
        if (!settingsOpen || settingsBusy) return;
        settingsBusy = true;
        try {
            await finishSettings();
        } catch (error) {
            document.getElementById('settings-error').textContent = '返回阅读失败：' + error;
        } finally {
            settingsBusy = false;
        }
    }

    document.getElementById('settings-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        if (settingsBusy) return;
        settingsBusy = true;
        try {
            const result = await pywebview.api.apply_settings(
                Number(document.getElementById('settings-width').value),
                Number(document.getElementById('settings-height').value),
                Number(document.getElementById('settings-speed').value),
                document.getElementById('settings-mouse-sense').checked,
                Number(document.getElementById('settings-font-size').value),
                document.getElementById('settings-color').value,
                Number(document.getElementById('settings-opacity').value),
                document.getElementById('settings-progress-bar').checked
            );
            if (!result.success) {
                document.getElementById('settings-error').textContent = result.message;
                return;
            }
            changeSpeed(result.config.speed);
            setProgressBarVisible(!!result.config.progress_bar);
            await finishSettings();
        } catch (error) {
            document.getElementById('settings-error').textContent = '保存失败：' + error;
        } finally {
            settingsBusy = false;
        }
    });

    window.addEventListener('pywebviewready', async () => {
        const config = await pywebview.api.get_config();
        changeSpeed(config.speed);
        applyFontStyle(config.font_size || 14, config.text_color || '#333333', config.text_opacity || 100);
        setProgressBarVisible(!!config.progress_bar);
    });
</script>
    """
