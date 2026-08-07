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
        numericKeyCode = Math.floor(numericKeyCode);
        // Do not translate the code here. MV's Input.keyMapper remains the
        // final authority, including project/plugin remappings.
        input[method](makeEvent(method === '_onKeyDown' ? 'keydown' : 'keyup', numericKeyCode));
        return true;
    }

    global.Game2ApkInput = {
        keyDown: function (keyCode) {
            return invoke('_onKeyDown', keyCode);
        },
        keyUp: function (keyCode) {
            return invoke('_onKeyUp', keyCode);
        }
    };
    // Game-area touch is intentionally not converted to a key here. Android
    // leaves it on WebView/MV TouchInput so choices, map destinations, NPC
    // interaction, and long-press message acceleration retain MV semantics.
}(window));
