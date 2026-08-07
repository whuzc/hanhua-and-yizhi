package com.game2apk.rpgmv;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/** Persistable normalized button layout, independent of the WebView canvas size. */
public final class OverlayLayout {
    private final Map<String, NormalizedRect> buttonRects;

    public OverlayLayout(Map<String, NormalizedRect> buttonRects) {
        if (buttonRects == null || buttonRects.isEmpty()) {
            throw new IllegalArgumentException("button layout is required");
        }
        Map<String, NormalizedRect> copy = new LinkedHashMap<>();
        for (Map.Entry<String, NormalizedRect> entry : buttonRects.entrySet()) {
            if (entry.getKey() == null || entry.getValue() == null) {
                throw new IllegalArgumentException("button layout contains a null entry");
            }
            copy.put(entry.getKey(), entry.getValue());
        }
        for (Map.Entry<String, NormalizedRect> left : copy.entrySet()) {
            for (Map.Entry<String, NormalizedRect> right : copy.entrySet()) {
                if (left.getKey().equals(right.getKey())) {
                    continue;
                }
                if (overlaps(left.getValue(), right.getValue())) {
                    throw new IllegalArgumentException("button layouts overlap: "
                            + left.getKey() + " and " + right.getKey());
                }
            }
        }
        this.buttonRects = Collections.unmodifiableMap(copy);
    }

    public static OverlayLayout fromConfig(java.util.List<Game2ApkConfig.ButtonConfig> buttons) {
        Map<String, NormalizedRect> rects = new LinkedHashMap<>();
        for (Game2ApkConfig.ButtonConfig button : buttons) {
            rects.put(button.id, button.rect);
        }
        return new OverlayLayout(rects);
    }

    public Map<String, NormalizedRect> buttonRects() {
        return buttonRects;
    }

    public NormalizedRect buttonRect(String id) {
        return buttonRects.get(id);
    }

    public OverlayLayout withButtonRect(String id, NormalizedRect rect) {
        Map<String, NormalizedRect> copy = new LinkedHashMap<>(buttonRects);
        copy.put(id, rect);
        return new OverlayLayout(copy);
    }

    private static boolean overlaps(NormalizedRect left, NormalizedRect right) {
        return left.left < right.right && right.left < left.right
                && left.top < right.bottom && right.top < left.bottom;
    }
}
