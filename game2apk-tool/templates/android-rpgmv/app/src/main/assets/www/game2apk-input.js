(function (global) {
    'use strict';

    function makeEvent(type, keyCode) {
        return {
            type: type,
            keyCode: keyCode,
            which: keyCode,
            code: '',
            repeat: false,
            ctrlKey: false,
            altKey: false,
            shiftKey: false,
            metaKey: false,
            preventDefault: function () {},
            stopPropagation: function () {}
        };
    }

    function invoke(method, keyCode) {
        var input = global.Input;
        var numericKeyCode = Number(keyCode);
        if (!input || typeof input[method] !== 'function'
                || !isFinite(numericKeyCode) || numericKeyCode < 0) {
            return false;
        }
        if (method === '_onKeyDown' && global.Game2ApkInput) {
            global.Game2ApkInput.unlockAudio();
        }
        numericKeyCode = Math.floor(numericKeyCode);
        // Do not translate the code here. MV's Input.keyMapper remains the
        // final authority, including project/plugin remappings.
        input[method](makeEvent(method === '_onKeyDown' ? 'keydown' : 'keyup', numericKeyCode));
        return true;
    }

    global.Game2ApkInput = {
        _resumeAudioContext: function (context) {
            if (!context || typeof context.resume !== 'function' || context.state !== 'suspended') {
                return;
            }
            try {
                var result = context.resume();
                if (result && typeof result.catch === 'function') {
                    result.catch(function () {});
                }
            } catch (_) {}
        },
        unlockAudio: function () {
            var webAudio = global.WebAudio;
            if (webAudio && webAudio._context) {
                global.Game2ApkInput._resumeAudioContext(webAudio._context);
                // MV's own unlock handler primes a zero-length source.  Keep
                // that step for Android WebView/Bluetooth routes as well;
                // it is harmless when the context is already unlocked.
                if (typeof webAudio._onTouchStart === 'function') {
                    try { webAudio._onTouchStart(); } catch (_) {}
                }
            }
            return true;
        },
        requestExit: function () {
            try {
                global.location.href = 'game2apk://exit';
                return true;
            } catch (_) {
                return false;
            }
        },
        keyDown: function (keyCode) {
            return invoke('_onKeyDown', keyCode);
        },
        keyUp: function (keyCode) {
            return invoke('_onKeyUp', keyCode);
        }
    };
    global.Game2ApkInput.installExitHook = function () {
        var manager = global.SceneManager;
        if (manager && typeof manager.exit === 'function' && !manager._game2apkExitHook) {
            manager.exit = function () { return global.Game2ApkInput.requestExit(); };
            manager._game2apkExitHook = true;
        }
        if (typeof global.close === 'function' && !global._game2apkCloseHook) {
            global.close = function () { return global.Game2ApkInput.requestExit(); };
            global._game2apkCloseHook = true;
        }
        return Boolean(manager && manager._game2apkExitHook);
    };
    if (global.document && global.document.addEventListener) {
        global.document.addEventListener('touchstart', global.Game2ApkInput.unlockAudio, { passive: true });
        global.document.addEventListener('pointerdown', global.Game2ApkInput.unlockAudio, { passive: true });
        global.document.addEventListener('keydown', global.Game2ApkInput.unlockAudio, { passive: true });
        global.document.addEventListener('visibilitychange', global.Game2ApkInput.unlockAudio, { passive: true });
    }
    if (global.addEventListener) {
        global.addEventListener('focus', global.Game2ApkInput.unlockAudio, { passive: true });
    }
    global.Game2ApkInput.installExitHook();
    if (global.setTimeout) {
        (function retryExitHook(attempts) {
            if (global.Game2ApkInput.installExitHook() || attempts <= 0) return;
            global.setTimeout(function () { retryExitHook(attempts - 1); }, 50);
        }(40));
    }
    // Game-area touch is intentionally not converted to a key here. Android
    // leaves it on WebView/MV TouchInput so choices, map destinations, NPC
    // interaction, and long-press message acceleration retain MV semantics.
}(window));
