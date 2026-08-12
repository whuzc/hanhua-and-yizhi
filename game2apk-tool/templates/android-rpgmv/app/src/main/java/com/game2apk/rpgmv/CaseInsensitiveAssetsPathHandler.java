package com.game2apk.rpgmv;

import android.content.Context;
import android.content.res.AssetManager;
import android.net.Uri;
import android.util.Log;
import android.webkit.WebResourceResponse;

import androidx.webkit.WebViewAssetLoader;

import java.io.IOException;
import java.io.InputStream;
import java.net.URLConnection;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/**
 * Serves APK assets with a case-insensitive fallback.
 *
 * Windows MV projects commonly contain a file such as Cursor.rpgmvp while a
 * plugin later requests cursor.rpgmvp.  The Windows filesystem hides this
 * mismatch, but APK/AssetManager paths are case-sensitive.  The fast path is
 * an exact AssetManager.open; only a missing exact path performs a bounded,
 * segment-by-segment directory lookup.
 */
public final class CaseInsensitiveAssetsPathHandler implements WebViewAssetLoader.PathHandler {
    private static final String TAG = "Game2ApkRuntime";
    private final AssetManager assets;

    public CaseInsensitiveAssetsPathHandler(Context context) {
        this.assets = context.getAssets();
    }

    @Override
    public WebResourceResponse handle(String path) {
        String decoded = Uri.decode(path);
        String safePath = safePath(decoded);
        if (safePath == null) {
            return null;
        }
        String resolvedPath = safePath;
        InputStream stream;
        try {
            stream = assets.open(safePath, AssetManager.ACCESS_STREAMING);
        } catch (IOException exactMiss) {
            resolvedPath = resolveCaseInsensitive(safePath);
            if (resolvedPath == null) {
                return null;
            }
            try {
                stream = assets.open(resolvedPath, AssetManager.ACCESS_STREAMING);
            } catch (IOException fallbackMiss) {
                return null;
            }
            Log.i(TAG, "case-insensitive asset fallback: " + safePath + " -> " + resolvedPath);
        }
        return new WebResourceResponse(mimeType(resolvedPath), textEncoding(resolvedPath), stream);
    }

    private String resolveCaseInsensitive(String path) {
        String[] pieces = path.split("/");
        StringBuilder current = new StringBuilder();
        for (int index = 0; index < pieces.length; index++) {
            String directory = current.toString();
            String wanted = pieces[index];
            String selected = null;
            try {
                String[] children = assets.list(directory);
                for (String child : children) {
                    if (child.equals(wanted)) {
                        selected = child;
                        break;
                    }
                    if (selected == null && child.equalsIgnoreCase(wanted)) {
                        selected = child;
                    }
                }
            } catch (IOException ignored) {
                return null;
            }
            if (selected == null) {
                return null;
            }
            if (current.length() > 0) {
                current.append('/');
            }
            current.append(selected);
        }
        return current.toString();
    }

    private static String safePath(String path) {
        if (path == null || path.isEmpty() || path.startsWith("/")
                || path.indexOf('\\') >= 0 || path.indexOf('\u0000') >= 0) {
            return null;
        }
        String[] pieces = path.split("/");
        for (String piece : pieces) {
            if (piece.isEmpty() || ".".equals(piece) || "..".equals(piece)) {
                return null;
            }
        }
        return path;
    }

    private static String mimeType(String name) {
        String mime = URLConnection.guessContentTypeFromName(name);
        if (mime != null) {
            return mime;
        }
        String lower = name.toLowerCase(Locale.ROOT);
        if (lower.endsWith(".js")) return "text/javascript";
        if (lower.endsWith(".json")) return "application/json";
        if (lower.endsWith(".css")) return "text/css";
        if (lower.endsWith(".html")) return "text/html";
        if (lower.endsWith(".rpgmvo")) return "audio/ogg";
        if (lower.endsWith(".rpgmvm")) return "audio/mp4";
        return "application/octet-stream";
    }

    private static String textEncoding(String name) {
        String lower = name.toLowerCase(Locale.ROOT);
        if (lower.endsWith(".js") || lower.endsWith(".json")
                || lower.endsWith(".css") || lower.endsWith(".html")) {
            return StandardCharsets.UTF_8.name();
        }
        return null;
    }
}
