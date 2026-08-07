package com.game2apk.rpgmv;

import android.util.Log;
import android.webkit.WebView;

import java.util.HashSet;
import java.util.Set;

/**
 * Controlled native-to-MV input bridge. It only evaluates integer key-code
 * calls into the asset-owned game2apk-input.js; it never exposes a Java object
 * to page JavaScript.
 */
public final class RpgInputBridge implements KeySink {
    private static final String TAG = "Game2ApkInput";
    private final WebView webView;
    private final Set<Integer> pressedKeys = new HashSet<>();
    private boolean pageReady;

    public RpgInputBridge(WebView webView) {
        this.webView = webView;
    }

    public void setPageReady(boolean pageReady) {
        if (!pageReady) {
            releaseAll();
        }
        this.pageReady = pageReady;
    }

    @Override
    public void keyDown(int keyCode) {
        evaluate("keyDown", keyCode);
    }

    @Override
    public void keyUp(int keyCode) {
        evaluate("keyUp", keyCode);
    }

    private void evaluate(String method, int keyCode) {
        if (!pageReady) {
            return;
        }
        if (keyCode < 0 || keyCode > 512) {
            Log.w(TAG, "ignored out-of-range key code: " + keyCode);
            return;
        }
        if ("keyDown".equals(method)) {
            pressedKeys.add(keyCode);
        } else {
            pressedKeys.remove(keyCode);
        }
        String script = "window.Game2ApkInput && window.Game2ApkInput."
                + method + "(" + keyCode + ");";
        webView.evaluateJavascript(script, null);
    }

    public void releaseAll() {
        if (pressedKeys.isEmpty()) {
            return;
        }
        Set<Integer> keys = new HashSet<>(pressedKeys);
        pressedKeys.clear();
        if (!pageReady) {
            return;
        }
        for (Integer keyCode : keys) {
            evaluate("keyUp", keyCode);
        }
    }
}
