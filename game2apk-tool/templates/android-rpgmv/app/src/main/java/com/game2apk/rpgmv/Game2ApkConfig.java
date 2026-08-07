package com.game2apk.rpgmv;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Versioned Android control configuration injected by the Windows generator. */
public final class Game2ApkConfig {
    public static final int SUPPORTED_SCHEMA_VERSION = 1;
    private static final String[] REQUIRED_BUTTON_IDS = {
            "up", "down", "left", "right", "confirm", "cancel", "esc", "portrait"
    };

    public final int schemaVersion;
    public final TouchConfig touch;
    public final OverlayConfig overlay;
    public final List<ButtonConfig> buttons;

    private Game2ApkConfig(int schemaVersion, TouchConfig touch,
                           OverlayConfig overlay, List<ButtonConfig> buttons) {
        this.schemaVersion = schemaVersion;
        this.touch = touch;
        this.overlay = overlay;
        this.buttons = Collections.unmodifiableList(new ArrayList<>(buttons));
    }

    public static Game2ApkConfig parse(String json) throws ConfigException {
        if (json == null || json.trim().isEmpty()) {
            throw new ConfigException("game2apk config is empty");
        }
        try {
            JSONObject root = new JSONObject(json);
            if (!root.has("schemaVersion")) {
                throw new ConfigException("game2apk config is missing schemaVersion");
            }
            int schemaVersion = root.getInt("schemaVersion");
            if (schemaVersion != SUPPORTED_SCHEMA_VERSION) {
                throw new ConfigException("Unsupported game2apk config schemaVersion "
                        + schemaVersion + "; supported version is " + SUPPORTED_SCHEMA_VERSION);
            }
            if (root.has("tap") || root.has("joystick")) {
                throw new ConfigException("legacy tap/joystick controls are not supported");
            }

            JSONObject touchJson = requiredObject(root, "touch");
            int cancelKeyCode = checkedKeyCode(touchJson, "cancelKeyCode", "touch.cancelKeyCode");
            if (cancelKeyCode != 27) {
                throw new ConfigException("touch.cancelKeyCode must be 27 (ESC/cancel)");
            }
            int twoFingerWindowMs = requiredInt(touchJson, "twoFingerWindowMs", "touch.twoFingerWindowMs");
            if (twoFingerWindowMs < 50 || twoFingerWindowMs > 1000) {
                throw new ConfigException("touch.twoFingerWindowMs must be between 50 and 1000");
            }
            float touchSlopPx = requiredFloat(touchJson, "touchSlopPx", "touch.touchSlopPx");
            if (touchSlopPx < 1.0f || touchSlopPx > 128.0f) {
                throw new ConfigException("touch.touchSlopPx must be between 1 and 128");
            }
            TouchConfig touch = new TouchConfig(cancelKeyCode, twoFingerWindowMs, touchSlopPx);

            JSONObject overlayJson = requiredObject(root, "overlay");
            float opacity = requiredFloat(overlayJson, "opacity", "overlay.opacity");
            if (opacity < 0.0f || opacity > 1.0f) {
                throw new ConfigException("overlay.opacity must be in [0, 1]");
            }
            boolean hiddenByDefault = requiredBoolean(
                    overlayJson, "hiddenByDefault", "overlay.hiddenByDefault");
            OverlayConfig overlay = new OverlayConfig(opacity, hiddenByDefault);

            JSONArray buttonArray = requiredArray(root, "buttons");
            if (buttonArray.length() != REQUIRED_BUTTON_IDS.length) {
                throw new ConfigException("buttons must contain exactly four directions and four actions");
            }
            List<ButtonConfig> buttons = new ArrayList<>();
            Set<String> ids = new HashSet<>();
            for (int i = 0; i < buttonArray.length(); i++) {
                Object raw = buttonArray.get(i);
                if (!(raw instanceof JSONObject)) {
                    throw new ConfigException("buttons[" + i + "] must be an object");
                }
                JSONObject buttonJson = (JSONObject) raw;
                String id = requiredString(buttonJson, "id", "buttons[" + i + "].id");
                if (!ids.add(id)) {
                    throw new ConfigException("duplicate button id: " + id);
                }
                int expectedKeyCode = expectedKeyCode(id);
                String expectedMode = expectedMode(id);
                if (expectedKeyCode < 0) {
                    throw new ConfigException("unsupported button id: " + id);
                }
                String label = requiredString(buttonJson, "label", "buttons[" + i + "].label");
                int keyCode = checkedKeyCode(buttonJson, "keyCode", "buttons[" + i + "].keyCode");
                if (keyCode != expectedKeyCode) {
                    throw new ConfigException("button " + id + " must use keyCode " + expectedKeyCode);
                }
                String mode = requiredString(buttonJson, "mode", "buttons[" + i + "].mode");
                if (!expectedMode.equals(mode)) {
                    throw new ConfigException("button " + id + " must use mode " + expectedMode);
                }
                NormalizedRect rect = readButtonRect(buttonJson, i);
                buttons.add(new ButtonConfig(id, label, keyCode, mode, rect));
            }
            Set<String> required = new HashSet<>();
            Collections.addAll(required, REQUIRED_BUTTON_IDS);
            if (!required.equals(ids)) {
                throw new ConfigException("buttons must include up/down/left/right/confirm/cancel/esc/portrait");
            }
            for (int index = 0; index < buttons.size(); index++) {
                for (int other = index + 1; other < buttons.size(); other++) {
                    if (overlaps(buttons.get(index).rect, buttons.get(other).rect)) {
                        throw new ConfigException("button layouts overlap: "
                                + buttons.get(index).id + " and " + buttons.get(other).id);
                    }
                }
            }
            return new Game2ApkConfig(schemaVersion, touch, overlay, buttons);
        } catch (ConfigException e) {
            throw e;
        } catch (JSONException | ClassCastException | NumberFormatException e) {
            throw new ConfigException("invalid game2apk config JSON: " + e.getMessage(), e);
        }
    }

    private static int expectedKeyCode(String id) {
        if ("up".equals(id)) return 38;
        if ("down".equals(id)) return 40;
        if ("left".equals(id)) return 37;
        if ("right".equals(id)) return 39;
        if ("confirm".equals(id)) return 13;
        if ("cancel".equals(id)) return 88;
        if ("esc".equals(id)) return 27;
        if ("portrait".equals(id)) return 65;
        return -1;
    }

    private static String expectedMode(String id) {
        return "up".equals(id) || "down".equals(id) || "left".equals(id) || "right".equals(id)
                ? "hold" : "tap";
    }

    private static boolean overlaps(NormalizedRect left, NormalizedRect right) {
        return left.left < right.right && right.left < left.right
                && left.top < right.bottom && right.top < left.bottom;
    }

    private static NormalizedRect readButtonRect(JSONObject json, int index)
            throws JSONException, ConfigException {
        if (!json.has("x") || !json.has("y") || !json.has("width") || !json.has("height")) {
            throw new ConfigException("buttons[" + index + "] layout requires x, y, width and height");
        }
        float x = requiredFloat(json, "x", "buttons[" + index + "].x");
        float y = requiredFloat(json, "y", "buttons[" + index + "].y");
        float width = requiredFloat(json, "width", "buttons[" + index + "].width");
        float height = requiredFloat(json, "height", "buttons[" + index + "].height");
        try {
            return NormalizedRect.fromXYWH(x, y, width, height);
        } catch (IllegalArgumentException e) {
            throw new ConfigException("buttons[" + index + "] layout must be normalized and non-empty", e);
        }
    }

    private static JSONObject requiredObject(JSONObject root, String key) throws JSONException, ConfigException {
        Object value = root.opt(key);
        if (!(value instanceof JSONObject)) {
            throw new ConfigException(key + " must be an object");
        }
        return (JSONObject) value;
    }

    private static JSONArray requiredArray(JSONObject root, String key) throws JSONException, ConfigException {
        Object value = root.opt(key);
        if (!(value instanceof JSONArray)) {
            throw new ConfigException(key + " must be an array");
        }
        return (JSONArray) value;
    }

    private static String requiredString(JSONObject json, String key, String path)
            throws JSONException, ConfigException {
        if (!json.has(key) || json.isNull(key)) {
            throw new ConfigException(path + " is required");
        }
        String value = json.getString(key).trim();
        if (value.isEmpty()) {
            throw new ConfigException(path + " must not be empty");
        }
        return value;
    }

    private static int checkedKeyCode(JSONObject json, String key, String path)
            throws JSONException, ConfigException {
        int value = requiredInt(json, key, path);
        if (value < 0 || value > 512) {
            throw new ConfigException(path + " must be between 0 and 512");
        }
        return value;
    }

    private static int requiredInt(JSONObject json, String key, String path)
            throws JSONException, ConfigException {
        if (!json.has(key) || json.isNull(key)) {
            throw new ConfigException(path + " is required");
        }
        return json.getInt(key);
    }

    private static float requiredFloat(JSONObject json, String key, String path)
            throws JSONException, ConfigException {
        if (!json.has(key) || json.isNull(key)) {
            throw new ConfigException(path + " is required");
        }
        return (float) json.getDouble(key);
    }

    private static boolean requiredBoolean(JSONObject json, String key, String path)
            throws JSONException, ConfigException {
        if (!json.has(key) || json.isNull(key)) {
            throw new ConfigException(path + " is required");
        }
        Object value = json.get(key);
        if (!(value instanceof Boolean)) {
            throw new ConfigException(path + " must be boolean");
        }
        return (Boolean) value;
    }

    public static final class TouchConfig {
        public final int cancelKeyCode;
        public final int twoFingerWindowMs;
        public final float touchSlopPx;

        private TouchConfig(int cancelKeyCode, int twoFingerWindowMs, float touchSlopPx) {
            this.cancelKeyCode = cancelKeyCode;
            this.twoFingerWindowMs = twoFingerWindowMs;
            this.touchSlopPx = touchSlopPx;
        }
    }

    public static final class OverlayConfig {
        public final float opacity;
        public final boolean hiddenByDefault;

        private OverlayConfig(float opacity, boolean hiddenByDefault) {
            this.opacity = opacity;
            this.hiddenByDefault = hiddenByDefault;
        }
    }

    public static final class ButtonConfig {
        public final String id;
        public final String label;
        public final int keyCode;
        public final String mode;
        public final NormalizedRect rect;

        private ButtonConfig(String id, String label, int keyCode, String mode, NormalizedRect rect) {
            this.id = id;
            this.label = label;
            this.keyCode = keyCode;
            this.mode = mode;
            this.rect = rect;
        }
    }

    public static final class ConfigException extends Exception {
        public ConfigException(String message) {
            super(message);
        }

        public ConfigException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
