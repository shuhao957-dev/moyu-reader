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
        padding: 16px;
        color: #333;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-app-region: no-drag;
    }
    #moyu-settings .settings-card {
        max-width: 500px;
        margin: 0 auto;
        padding: 20px;
        background: white;
        border-radius: 12px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
    }
    #moyu-settings h1 { font-size: 20px; margin-bottom: 12px; }
    #moyu-settings label { display: block; font-weight: bold; margin: 10px 0 4px; }
    #moyu-settings input {
        width: 100%; padding: 8px; font-size: 16px;
        border: 1px solid #ccc; border-radius: 6px;
        user-select: text;
    }
    #moyu-settings .presets { display: flex; gap: 8px; margin-top: 8px; }
    #moyu-settings button {
        margin: 0; padding: 8px 12px; font-size: 14px;
        border: 1px solid #ddd; border-radius: 6px; cursor: pointer;
        background: #f3f4f8; color: #333;
    }
    #moyu-settings .presets button { flex: 1; }
    #moyu-settings .actions { display: flex; gap: 10px; margin-top: 18px; }
    #moyu-settings .actions button { flex: 1; }
    #moyu-settings #settings-save { background: #667eea; border-color: #667eea; color: white; }
    #moyu-settings .hint { margin-top: 12px; color: #777; font-size: 12px; }
    #moyu-settings #settings-error { color: #b42318; margin-top: 10px; }
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
        <p id="settings-error" role="alert"></p>
        <div class="actions">
            <button type="button" id="settings-cancel" onclick="closeSettings()">取消</button>
            <button type="submit" id="settings-save">保存并返回</button>
        </div>
        <p class="hint">保存后立即生效。Ctrl+, 打开设置，Esc 返回阅读。</p>
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

    function setSetting(name, value) {
        document.getElementById('settings-' + name).value = value;
    }

    async function openSettings() {
        if (settingsOpen || settingsBusy) return;
        settingsBusy = true;
        settingsOpen = true;
        settingsWasPaused = isPaused;
        if (!isPaused) togglePause();
        try {
            const config = await pywebview.api.open_settings();
            setSetting('width', config.window.width);
            setSetting('height', config.window.height);
            setSetting('speed', scrollSpeed);
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
        if (!isAutoMode && content) updatePageInfo();
        if (!settingsWasPaused && isPaused) togglePause();
    }

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
                Number(document.getElementById('settings-speed').value)
            );
            if (!result.success) {
                document.getElementById('settings-error').textContent = result.message;
                return;
            }
            changeSpeed(result.config.speed);
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
    });
</script>
    """
