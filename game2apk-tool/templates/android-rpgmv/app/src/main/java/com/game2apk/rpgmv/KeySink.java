package com.game2apk.rpgmv;

/** Destination for key transitions. Kept free of Android types for unit tests. */
public interface KeySink {
    void keyDown(int keyCode);

    void keyUp(int keyCode);
}
