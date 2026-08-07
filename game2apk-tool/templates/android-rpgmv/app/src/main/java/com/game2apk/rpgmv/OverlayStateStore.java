package com.game2apk.rpgmv;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.LinkedHashMap;
import java.util.Map;

/** SharedPreferences persistence for overlay visibility, opacity, and button layout. */
public final class OverlayStateStore {
    /* Keep the preference name stable so an in-place APK update retains user settings. */
    private static final String PREFS_NAME = "game2apk.overlay.v1";
    private static final String HIDDEN = "hidden";
    private static final String OPACITY = "opacity";

    private final SharedPreferences preferences;

    public OverlayStateStore(Context context) {
        preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public State load(Game2ApkConfig config) {
        OverlayLayout defaults = OverlayLayout.fromConfig(config.buttons);
        Map<String, NormalizedRect> rects = new LinkedHashMap<>();
        for (Game2ApkConfig.ButtonConfig button : config.buttons) {
            rects.put(button.id, readRect(button.id, button.rect));
        }
        OverlayLayout layout;
        try {
            layout = new OverlayLayout(rects);
        } catch (IllegalArgumentException ignored) {
            // A layout saved by an older build or an interrupted edit must not
            // make the new activity fail to start.
            layout = defaults;
        }
        boolean hidden = preferences.getBoolean(HIDDEN, config.overlay.hiddenByDefault);
        float opacity = readOpacity(config.overlay.opacity);
        return new State(hidden, opacity, layout);
    }

    public void saveHidden(boolean hidden) {
        preferences.edit().putBoolean(HIDDEN, hidden).apply();
    }

    public void saveOpacity(float opacity) {
        preferences.edit().putFloat(OPACITY, clampOpacity(opacity)).apply();
    }

    public void saveLayout(OverlayLayout layout) {
        SharedPreferences.Editor editor = preferences.edit();
        for (Map.Entry<String, NormalizedRect> entry : layout.buttonRects().entrySet()) {
            NormalizedRect rect = entry.getValue();
            String prefix = "layout.button." + entry.getKey() + ".";
            editor.putFloat(prefix + "left", rect.left)
                    .putFloat(prefix + "top", rect.top)
                    .putFloat(prefix + "right", rect.right)
                    .putFloat(prefix + "bottom", rect.bottom);
        }
        editor.apply();
    }

    private NormalizedRect readRect(String id, NormalizedRect fallback) {
        String prefix = "layout.button." + id + ".";
        if (!preferences.contains(prefix + "left") || !preferences.contains(prefix + "top")
                || !preferences.contains(prefix + "right") || !preferences.contains(prefix + "bottom")) {
            return fallback;
        }
        try {
            return new NormalizedRect(
                    preferences.getFloat(prefix + "left", fallback.left),
                    preferences.getFloat(prefix + "top", fallback.top),
                    preferences.getFloat(prefix + "right", fallback.right),
                    preferences.getFloat(prefix + "bottom", fallback.bottom));
        } catch (IllegalArgumentException | ClassCastException e) {
            return fallback;
        }
    }

    private float readOpacity(float fallback) {
        try {
            return clampOpacity(preferences.getFloat(OPACITY, fallback));
        } catch (ClassCastException e) {
            return fallback;
        }
    }

    private static float clampOpacity(float opacity) {
        return Math.max(0.0f, Math.min(1.0f, opacity));
    }

    public static final class State {
        public final boolean hidden;
        public final float opacity;
        public final OverlayLayout layout;

        private State(boolean hidden, float opacity, OverlayLayout layout) {
            this.hidden = hidden;
            this.opacity = opacity;
            this.layout = layout;
        }
    }
}
