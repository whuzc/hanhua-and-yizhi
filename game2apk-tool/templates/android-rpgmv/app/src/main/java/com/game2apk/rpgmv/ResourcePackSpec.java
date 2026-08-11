package com.game2apk.rpgmv;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.regex.Pattern;

/** APK metadata describing a ZIP64 game resource pack stored outside the APK. */
public final class ResourcePackSpec {
    private static final Pattern SHA256 = Pattern.compile("[0-9a-fA-F]{64}");
    public final int schemaVersion;
    public final String fileName;
    public final String projectId;
    public final String packSha256;
    public final long packBytes;
    public final long sourceBytes;
    public final int fileCount;
    public final String deviceRelativePath;
    public final String entryRoot;
    public final String startPath;

    private ResourcePackSpec(int schemaVersion, String fileName, String projectId,
                             String packSha256, long packBytes, long sourceBytes,
                             int fileCount, String deviceRelativePath,
                             String entryRoot, String startPath) {
        this.schemaVersion = schemaVersion;
        this.fileName = fileName;
        this.projectId = projectId;
        this.packSha256 = packSha256;
        this.packBytes = packBytes;
        this.sourceBytes = sourceBytes;
        this.fileCount = fileCount;
        this.deviceRelativePath = deviceRelativePath;
        this.entryRoot = entryRoot;
        this.startPath = startPath;
    }

    public static ResourcePackSpec parse(String json) throws Game2ApkConfig.ConfigException {
        try {
            JSONObject root = new JSONObject(json);
            int schema = root.getInt("schemaVersion");
            if (schema != 1) {
                throw new Game2ApkConfig.ConfigException("unsupported resource pack schemaVersion " + schema);
            }
            String fileName = required(root, "fileName");
            if (fileName.contains("/") || fileName.contains("\\") || fileName.contains("..")) {
                throw new Game2ApkConfig.ConfigException("resource pack fileName is unsafe");
            }
            String projectId = required(root, "projectId");
            String sha = required(root, "packSha256");
            if (!SHA256.matcher(sha).matches()) {
                throw new Game2ApkConfig.ConfigException("resource pack packSha256 is invalid");
            }
            long packBytes = root.getLong("packBytes");
            long sourceBytes = root.getLong("sourceBytes");
            int fileCount = root.getInt("fileCount");
            if (packBytes <= 0 || sourceBytes <= 0 || fileCount <= 0) {
                throw new Game2ApkConfig.ConfigException("resource pack sizes must be positive");
            }
            String devicePath = required(root, "deviceRelativePath");
            String entryRoot = root.optString("entryRoot", "www");
            String startPath = root.optString("startPath", "index.html");
            if (!"www".equals(entryRoot) || startPath.contains("..") || startPath.startsWith("/")) {
                throw new Game2ApkConfig.ConfigException("resource pack entry path is invalid");
            }
            return new ResourcePackSpec(schema, fileName, projectId, sha, packBytes,
                    sourceBytes, fileCount, devicePath, entryRoot, startPath);
        } catch (Game2ApkConfig.ConfigException e) {
            throw e;
        } catch (JSONException | NumberFormatException e) {
            throw new Game2ApkConfig.ConfigException("invalid resource pack metadata: " + e.getMessage(), e);
        }
    }

    private static String required(JSONObject root, String key)
            throws JSONException, Game2ApkConfig.ConfigException {
        if (!root.has(key) || root.isNull(key)) {
            throw new Game2ApkConfig.ConfigException("resource pack metadata is missing " + key);
        }
        String value = root.getString(key).trim();
        if (value.isEmpty()) {
            throw new Game2ApkConfig.ConfigException("resource pack metadata " + key + " is empty");
        }
        return value;
    }
}
