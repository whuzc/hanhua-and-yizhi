package com.game2apk.rpgmv;

/** A single key transition emitted by a pure input state machine. */
public final class KeyAction {
    public final int keyCode;
    public final boolean down;

    private KeyAction(int keyCode, boolean down) {
        this.keyCode = keyCode;
        this.down = down;
    }

    public static KeyAction down(int keyCode) {
        return new KeyAction(keyCode, true);
    }

    public static KeyAction up(int keyCode) {
        return new KeyAction(keyCode, false);
    }

    @Override
    public String toString() {
        return (down ? "down:" : "up:") + keyCode;
    }
}
