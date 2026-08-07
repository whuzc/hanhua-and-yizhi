package com.game2apk.rpgmv;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Tracks independently held direction pointers and releases each key safely. */
public final class HeldKeyStateMachine {
    private final Map<Integer, Integer> pointerKeys = new HashMap<>();
    private final Map<Integer, Integer> keyCounts = new HashMap<>();

    public List<KeyAction> onPointerDown(int pointerId, int keyCode) {
        if (pointerKeys.containsKey(pointerId)) {
            return new ArrayList<>();
        }
        pointerKeys.put(pointerId, keyCode);
        Integer count = keyCounts.get(keyCode);
        if (count == null) {
            keyCounts.put(keyCode, 1);
            return singleton(KeyAction.down(keyCode));
        }
        keyCounts.put(keyCode, count + 1);
        return new ArrayList<>();
    }

    public List<KeyAction> onPointerUp(int pointerId) {
        Integer keyCode = pointerKeys.remove(pointerId);
        if (keyCode == null) {
            return new ArrayList<>();
        }
        return releaseKey(keyCode);
    }

    public List<KeyAction> onPointerCancel(int pointerId) {
        return onPointerUp(pointerId);
    }

    public List<KeyAction> releaseAll() {
        List<KeyAction> actions = new ArrayList<>();
        for (Integer keyCode : new ArrayList<>(keyCounts.keySet())) {
            actions.add(KeyAction.up(keyCode));
        }
        pointerKeys.clear();
        keyCounts.clear();
        return actions;
    }

    public int activePointerCount() {
        return pointerKeys.size();
    }

    private List<KeyAction> releaseKey(int keyCode) {
        Integer count = keyCounts.get(keyCode);
        if (count == null) {
            return new ArrayList<>();
        }
        if (count <= 1) {
            keyCounts.remove(keyCode);
            return singleton(KeyAction.up(keyCode));
        }
        keyCounts.put(keyCode, count - 1);
        return new ArrayList<>();
    }

    private static List<KeyAction> singleton(KeyAction action) {
        List<KeyAction> actions = new ArrayList<>(1);
        actions.add(action);
        return actions;
    }
}
