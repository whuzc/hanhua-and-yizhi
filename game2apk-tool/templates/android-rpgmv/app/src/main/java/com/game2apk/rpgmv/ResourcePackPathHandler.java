package com.game2apk.rpgmv;

import android.webkit.WebResourceResponse;

import androidx.webkit.WebViewAssetLoader;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.FilterInputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.net.URLConnection;
import java.nio.charset.StandardCharsets;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Serves ``www/*`` entries from an external ZIP64 resource pack. */
public final class ResourcePackPathHandler implements WebViewAssetLoader.PathHandler {
    private final File archiveFile;
    private final ResourcePackSpec spec;

    public ResourcePackPathHandler(File archiveFile, ResourcePackSpec spec) {
        this.archiveFile = archiveFile;
        this.spec = spec;
    }

    @Override
    public WebResourceResponse handle(String path) {
        String entryName = safeEntryName(path);
        if (entryName == null) {
            return null;
        }
        ZipFile archive = null;
        try {
            final ZipFile openedArchive = new ZipFile(archiveFile, StandardCharsets.UTF_8);
            archive = openedArchive;
            ZipEntry entry = openedArchive.getEntry(spec.entryRoot + "/" + entryName);
            if (entry == null || entry.isDirectory()) {
                openedArchive.close();
                return null;
            }
            InputStream source = openedArchive.getInputStream(entry);
            InputStream managed = new FilterInputStream(source) {
                @Override
                public void close() throws IOException {
                    try {
                        super.close();
                    } finally {
                        openedArchive.close();
                    }
                }
            };
            return new WebResourceResponse(mimeType(entryName), null, managed);
        } catch (IOException e) {
            if (archive != null) {
                try { archive.close(); } catch (IOException ignored) { }
            }
            return null;
        }
    }

    /** Validate the central directory and required MV entries without hashing gigabytes. */
    public static String validate(File archiveFile, ResourcePackSpec spec) {
        if (!archiveFile.isFile()) {
            return "resource pack is missing";
        }
        if (archiveFile.length() != spec.packBytes) {
            return "resource pack size does not match the APK metadata";
        }
        try (ZipFile archive = new ZipFile(archiveFile, StandardCharsets.UTF_8)) {
            ZipEntry metadata = archive.getEntry("game2apk-resource.json");
            if (metadata == null) {
                return "resource pack manifest is missing";
            }
            JSONObject manifest = new JSONObject(readText(archive.getInputStream(metadata)));
            if (!spec.projectId.equals(manifest.optString("projectId"))) {
                return "resource pack belongs to a different staged project";
            }
            if (spec.fileCount != manifest.optInt("fileCount", -1)
                    || spec.sourceBytes != manifest.optLong("sourceBytes", -1L)) {
                return "resource pack manifest does not match the APK metadata";
            }
            String[] required = {"index.html", "js/rpg_core.js", "js/game2apk-input.js"};
            for (String item : required) {
                if (archive.getEntry(spec.entryRoot + "/" + item) == null) {
                    return "resource pack is missing www/" + item;
                }
            }
            return null;
        } catch (IOException | JSONException e) {
            return "resource pack cannot be opened: " + e.getMessage();
        }
    }

    private static String safeEntryName(String path) {
        if (path == null || path.isEmpty() || path.startsWith("/")
                || path.contains("\\") || path.contains("\u0000")) {
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

    private static String readText(InputStream input) throws IOException {
        try (InputStream source = input) {
            byte[] buffer = new byte[8192];
            StringBuilder output = new StringBuilder();
            int read;
            while ((read = source.read(buffer)) != -1) {
                output.append(new String(buffer, 0, read, StandardCharsets.UTF_8));
            }
            return output.toString();
        }
    }

    private static String mimeType(String name) {
        String mime = URLConnection.guessContentTypeFromName(name);
        if (mime != null) return mime;
        String lower = name.toLowerCase(java.util.Locale.ROOT);
        if (lower.endsWith(".js")) return "text/javascript";
        if (lower.endsWith(".json")) return "application/json";
        if (lower.endsWith(".css")) return "text/css";
        if (lower.endsWith(".html")) return "text/html";
        if (lower.endsWith(".ogg")) return "audio/ogg";
        if (lower.endsWith(".m4a")) return "audio/mp4";
        return "application/octet-stream";
    }
}
