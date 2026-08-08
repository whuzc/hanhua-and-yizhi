package com.game2apk.rpgmv;

import android.app.Activity;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.content.pm.ActivityInfo;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

import androidx.webkit.WebViewAssetLoader;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** Single-activity, offline RPG Maker MV WebView shell. */
public final class MainActivity extends Activity {
    private static final String TAG = "Game2ApkRuntime";
    private static final String ASSET_HOST = "appassets.androidplatform.net";
    private static final String EXIT_SCHEME = "game2apk";
    // This URL is part of the save-data contract. Keep the asset origin
    // stable across release updates so WebView's localStorage remains the
    // same store.
    private static final String START_URL =
            "https://appassets.androidplatform.net/assets/www/index.html";

    private WebView webView;
    private RpgInputBridge inputBridge;
    private OverlayView overlay;
    private KeyPulseStateMachine systemPulses;
    private Game2ApkConfig config;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
        try {
            config = Game2ApkConfig.parse(readAsset("game2apk/config.json"));
        } catch (IOException | Game2ApkConfig.ConfigException e) {
            showStartupError("Cannot load game2apk/config.json: " + e.getMessage());
            return;
        }

        webView = new WebView(this);
        configureWebView(webView);
        inputBridge = new RpgInputBridge(webView);
        OverlayStateStore stateStore = new OverlayStateStore(this);
        OverlayStateStore.State state = stateStore.load(config);
        InputRootLayout root = new InputRootLayout(this);
        root.setWebView(webView);
        systemPulses = new KeyPulseStateMachine(inputBridge, new KeyPulseStateMachine.Scheduler() {
            @Override
            public void postDelayed(Runnable runnable, long delayMs) {
                root.postDelayed(runnable, delayMs);
            }

            @Override
            public void removeCallbacks(Runnable runnable) {
                root.removeCallbacks(runnable);
            }
        });
        overlay = new OverlayView(this, config, inputBridge, stateStore, state);
        root.setOverlay(overlay);
        root.setBackgroundColor(Color.BLACK);
        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        root.addView(overlay, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(root);
        webView.loadUrl(START_URL);
    }

    private void configureWebView(WebView target) {
        WebSettings settings = target.getSettings();
        settings.setJavaScriptEnabled(true);
        // RPG Maker MV saves use DOM localStorage. Do not replace this with a
        // temporary/session store and do not clear WebView data on startup.
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        // MV uses WebAudio and HTML media for BGM/SE. The injected bridge
        // resumes a suspended AudioContext after the first real gesture.
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        if (android.os.Build.VERSION.SDK_INT >= 21) {
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        }
        target.setLayerType(View.LAYER_TYPE_HARDWARE, null);
        target.setOverScrollMode(View.OVER_SCROLL_NEVER);
        target.setBackgroundColor(Color.BLACK);

        WebViewAssetLoader assetLoader = new WebViewAssetLoader.Builder()
                .setDomain(ASSET_HOST)
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();
        target.setWebViewClient(new OfflineAssetWebViewClient(assetLoader));
    }

    private void showStartupError(String message) {
        TextView error = new TextView(this);
        error.setText(message);
        error.setTextColor(Color.WHITE);
        error.setTextSize(16.0f);
        error.setPadding(32, 32, 32, 32);
        error.setBackgroundColor(Color.rgb(40, 20, 20));
        setContentView(error);
        Log.e(TAG, message);
    }

    private String readAsset(String path) throws IOException {
        try (InputStream input = getAssets().open(path)) {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int read;
            while ((read = input.read(buffer)) != -1) {
                output.write(buffer, 0, read);
            }
            return output.toString(StandardCharsets.UTF_8.name());
        }
    }

    @Override
    public void onBackPressed() {
        if (systemPulses != null && config != null) {
            systemPulses.pulse(config.touch.cancelKeyCode);
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (overlay != null) {
            overlay.releaseAllInput();
            overlay = null;
        }
        if (systemPulses != null) {
            systemPulses.releaseAll();
            systemPulses = null;
        }
        if (inputBridge != null) {
            inputBridge.setPageReady(false);
        }
        if (webView != null) {
            webView.stopLoading();
            webView.setWebViewClient(null);
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    private final class OfflineAssetWebViewClient extends WebViewClient {
        private final WebViewAssetLoader assetLoader;

        private OfflineAssetWebViewClient(WebViewAssetLoader assetLoader) {
            this.assetLoader = assetLoader;
        }

        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (isInternalAsset(uri)) {
                return assetLoader.shouldInterceptRequest(uri);
            }
            Log.w(TAG, "blocked non-asset request: " + uri);
            return blockedResponse();
        }

        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, String url) {
            Uri uri = Uri.parse(url);
            if (isInternalAsset(uri)) {
                return assetLoader.shouldInterceptRequest(uri);
            }
            Log.w(TAG, "blocked non-asset request: " + url);
            return blockedResponse();
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            if (handleExitRequest(request.getUrl())) {
                return true;
            }
            if (isInternalAsset(request.getUrl())) {
                return false;
            }
            Log.w(TAG, "blocked external navigation: " + request.getUrl());
            return true;
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            if (handleExitRequest(Uri.parse(url))) {
                return true;
            }
            if (isInternalAsset(Uri.parse(url))) {
                return false;
            }
            Log.w(TAG, "blocked external navigation: " + url);
            return true;
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            super.onPageFinished(view, url);
            if (isInternalAsset(Uri.parse(url)) && inputBridge != null) {
                inputBridge.setPageReady(true);
            }
        }

        @Override
        public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
            super.onPageStarted(view, url, favicon);
            if (handleExitRequest(Uri.parse(url))) {
                return;
            }
            if (isInternalAsset(Uri.parse(url))) {
                if (overlay != null) {
                    overlay.releaseAllInput();
                }
                if (inputBridge != null) {
                    inputBridge.setPageReady(false);
                }
            }
        }

        private boolean handleExitRequest(Uri uri) {
            if (uri == null || !EXIT_SCHEME.equalsIgnoreCase(uri.getScheme())
                    || !"exit".equalsIgnoreCase(uri.getHost())) {
                return false;
            }
            Log.i(TAG, "game requested application exit");
            if (android.os.Build.VERSION.SDK_INT >= 21) {
                finishAndRemoveTask();
            } else {
                finish();
            }
            return true;
        }
    }

    private static boolean isInternalAsset(Uri uri) {
        return uri != null
                && "https".equalsIgnoreCase(uri.getScheme())
                && ASSET_HOST.equalsIgnoreCase(uri.getHost())
                && uri.getPath() != null
                && uri.getPath().startsWith("/assets/");
    }

    private static WebResourceResponse blockedResponse() {
        return new WebResourceResponse(
                "text/plain", "UTF-8", 403, "Blocked by offline runtime",
                null, new ByteArrayInputStream(new byte[0]));
    }
}
