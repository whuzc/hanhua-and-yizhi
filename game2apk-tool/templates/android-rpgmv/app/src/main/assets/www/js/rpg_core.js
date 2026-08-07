(function (global) {
    'use strict';

    var input = {
        keyMapper: {
            13: 'ok',
            27: 'cancel',
            37: 'left',
            38: 'up',
            39: 'right',
            40: 'down',
            65: 'portrait',
            87: 'warp',
            17: 'skip'
        },
        _currentState: {},
        _events: [],
        _onKeyDown: function (event) {
            var name = this.keyMapper[event.keyCode];
            if (name) {
                this._currentState[name] = true;
            }
            this._events.push({ type: 'down', keyCode: event.keyCode, mapped: name || null });
        },
        _onKeyUp: function (event) {
            var name = this.keyMapper[event.keyCode];
            if (name) {
                this._currentState[name] = false;
            }
            this._events.push({ type: 'up', keyCode: event.keyCode, mapped: name || null });
        }
    };

    global.Input = input;
}(window));
