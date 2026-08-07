package com.game2apk.rpgmv;

import java.util.HashSet;
import java.util.Set;

/** Pure visibility state with a recovery handle and three-finger long press. */
public final class OverlayVisibilityStateMachine {
    public static final long THREE_FINGER_LONG_PRESS_MS = 800L;

    private final Set<Integer> activePointers = new HashSet<>();
    private boolean hidden;
    private long threeFingerStartMs = -1L;

    public OverlayVisibilityStateMachine(boolean hidden) {
        this.hidden = hidden;
    }

    public boolean hide() {
        if (hidden) {
            return false;
        }
        hidden = true;
        return true;
    }

    public boolean restoreByHandle() {
        if (!hidden) {
            return false;
        }
        hidden = false;
        return true;
    }

    public void onPointerDown(int pointerId, long timeMs) {
        activePointers.add(pointerId);
        if (activePointers.size() >= 3 && threeFingerStartMs < 0L) {
            threeFingerStartMs = timeMs;
        }
    }

    public void onPointerUp(int pointerId) {
        activePointers.remove(pointerId);
        if (activePointers.size() < 3) {
            threeFingerStartMs = -1L;
        }
    }

    public void onPointerCancel(int pointerId) {
        onPointerUp(pointerId);
    }

    /** Clears pointers after a parent/WebView cancellation or Activity destroy. */
    public void clearPointers() {
        activePointers.clear();
        threeFingerStartMs = -1L;
    }

    public boolean tick(long timeMs) {
        if (!hidden || activePointers.size() < 3 || threeFingerStartMs < 0L) {
            return false;
        }
        if (timeMs - threeFingerStartMs < THREE_FINGER_LONG_PRESS_MS) {
            return false;
        }
        hidden = false;
        threeFingerStartMs = -1L;
        return true;
    }

    public boolean isHidden() {
        return hidden;
    }

    public int activePointerCount() {
        return activePointers.size();
    }
}
