package com.game2apk.rpgmv;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

final class KeyActions {
    private KeyActions() {
    }

    static List<KeyAction> press(int keyCode) {
        List<KeyAction> actions = new ArrayList<>(2);
        actions.add(KeyAction.down(keyCode));
        actions.add(KeyAction.up(keyCode));
        return actions;
    }

    static List<KeyAction> transition(int[] previous, int[] next) {
        if (sameSet(previous, next)) {
            return Collections.emptyList();
        }
        List<KeyAction> actions = new ArrayList<>();
        for (int keyCode : previous) {
            if (!contains(next, keyCode)) {
                actions.add(KeyAction.up(keyCode));
            }
        }
        for (int keyCode : next) {
            if (!contains(previous, keyCode)) {
                actions.add(KeyAction.down(keyCode));
            }
        }
        return actions;
    }

    static void apply(List<KeyAction> actions, KeySink sink) {
        for (KeyAction action : actions) {
            if (action.down) {
                sink.keyDown(action.keyCode);
            } else {
                sink.keyUp(action.keyCode);
            }
        }
    }

    static boolean isPulse(List<KeyAction> actions) {
        return actions != null
                && actions.size() == 2
                && actions.get(0).down
                && !actions.get(1).down
                && actions.get(0).keyCode == actions.get(1).keyCode;
    }

    private static boolean sameSet(int[] left, int[] right) {
        if (left.length != right.length) {
            return false;
        }
        for (int keyCode : left) {
            if (!contains(right, keyCode)) {
                return false;
            }
        }
        return true;
    }

    private static boolean contains(int[] values, int needle) {
        for (int value : values) {
            if (value == needle) {
                return true;
            }
        }
        return false;
    }
}
