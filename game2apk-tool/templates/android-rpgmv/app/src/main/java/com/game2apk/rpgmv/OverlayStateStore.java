package com.game2apk.rpgmv;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** SharedPreferences persistence for overlay visibility, opacity, and button layout. */
public final class OverlayStateStore {
    /* Keep the preference name stable so an in-place APK update retains user settings. */
    private static final String PREFS_NAME = "game2apk.overlay.v1";
    private static final String HIDDEN = "hidden";
    private static final String OPACITY = "opacity";
    private static final String CUSTOM_BUTTONS = "customButtons";

    private final SharedPreferences preferences;

    public OverlayStateStore(Context context) {
        preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public State load(Game2ApkConfig config) {
        List<Game2ApkConfig.ButtonConfig> buttons = loadButtons(config);
        OverlayLayout defaults = OverlayLayout.fromConfig(buttons);
        Map<String, NormalizedRect> rects = new LinkedHashMap<>();
        for (Game2ApkConfig.ButtonConfig button : buttons) {
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
        return new State(hidden, opacity, layout, buttons);
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

    public void saveButtons(List<Game2ApkConfig.ButtonConfig> buttons) {
        if (buttons == null) return;
        SharedPreferences.Editor editor = preferences.edit();
        JSONArray custom = new JSONArray();
        for (Game2ApkConfig.ButtonConfig button : buttons) {
            String prefix = "button." + button.id + ".";
            editor.putString(prefix + "label", button.label)
                    .putInt(prefix + "keyCode", button.keyCode)
                    .putString(prefix + "mode", button.mode)
                    .putBoolean(prefix + "visible", button.visible);
            if (button.id.startsWith("custom_")) {
                JSONObject item = new JSONObject();
                try {
                    item.put("id", button.id);
                    item.put("label", button.label);
                    item.put("keyCode", button.keyCode);
                    item.put("mode", button.mode);
                    item.put("visible", button.visible);
                    item.put("x", button.rect.left);
                    item.put("y", button.rect.top);
                    item.put("width", button.rect.width());
                    item.put("height", button.rect.height());
                    custom.put(item);
                } catch (JSONException ignored) {
                    // Values are primitives and cannot fail in normal Android
                    // org.json implementations; skip only a malformed custom
                    // entry rather than corrupting the entire preferences.
                }
            }
        }
        editor.putString(CUSTOM_BUTTONS, custom.toString()).apply();
    }

    private List<Game2ApkConfig.ButtonConfig> loadButtons(Game2ApkConfig config) {
        List<Game2ApkConfig.ButtonConfig> buttons = new ArrayList<>();
        for (Game2ApkConfig.ButtonConfig button : config.buttons) {
            buttons.add(loadButtonOverride(button));
        }
        String rawCustom = preferences.getString(CUSTOM_BUTTONS, "[]");
        try {
            JSONArray custom = new JSONArray(rawCustom);
            for (int index = 0; index < custom.length() && buttons.size() < 40; index++) {
                JSONObject item = custom.optJSONObject(index);
                if (item == null) continue;
                String id = item.optString("id", "");
                if (!id.startsWith("custom_") || containsButton(buttons, id)) continue;
                String label = item.optString("label", "\u81ea\u5b9a\u4e49");
                int keyCode = item.optInt("keyCode", 65);
                String mode = item.optString("mode", "tap");
                boolean visible = item.optBoolean("visible", true);
                NormalizedRect fallback;
                try {
                    fallback = NormalizedRect.fromXYWH(
                            (float) item.optDouble("x", 0.67),
                            (float) item.optDouble("y", 0.40),
                            (float) item.optDouble("width", 0.14),
                            (float) item.optDouble("height", 0.10));
                } catch (IllegalArgumentException ignored) {
                    continue;
                }
                NormalizedRect rect = readRect(id, fallback);
                try {
                    buttons.add(Game2ApkConfig.ButtonConfig.custom(
                            id, label, keyCode, mode, visible, rect));
                } catch (IllegalArgumentException ignored) {
                    // Ignore a stale/corrupt runtime custom entry.
                }
            }
        } catch (JSONException ignored) {
            // Ignore corrupt runtime custom state and keep generated defaults.
        }
        return buttons;
    }

    private Game2ApkConfig.ButtonConfig loadButtonOverride(Game2ApkConfig.ButtonConfig button) {
        String prefix = "button." + button.id + ".";
        String label = preferences.getString(prefix + "label", button.label);
        int keyCode = readInt(prefix + "keyCode", button.keyCode);
        String mode = preferences.getString(prefix + "mode", button.mode);
        boolean visible = preferences.getBoolean(prefix + "visible", button.visible);
        if (!"tap".equals(mode) && !"hold".equals(mode)) mode = button.mode;
        if (keyCode < 0 || keyCode > 512) keyCode = button.keyCode;
        return button.withValues(label, keyCode, mode, visible, readRect(button.id, button.rect));
    }

    private int readInt(String key, int fallback) {
        try {
            return preferences.getInt(key, fallback);
        } catch (ClassCastException ignored) {
            return fallback;
        }
    }

    private static boolean containsButton(List<Game2ApkConfig.ButtonConfig> buttons, String id) {
        for (Game2ApkConfig.ButtonConfig button : buttons) {
            if (id.equals(button.id)) return true;
        }
        return false;
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
        public final List<Game2ApkConfig.ButtonConfig> buttons;

        private State(boolean hidden, float opacity, OverlayLayout layout,
                      List<Game2ApkConfig.ButtonConfig> buttons) {
            this.hidden = hidden;
            this.opacity = opacity;
            this.layout = layout;
            this.buttons = java.util.Collections.unmodifiableList(new ArrayList<>(buttons));
        }
    }
}
