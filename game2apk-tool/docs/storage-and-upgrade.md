# 存档与覆盖更新契约

当前发布候选为 versionCode `8`、versionName `1.3.0`，从 7/1.2.0 原地升级；包名、签名和 WebView 存储契约保持不变。

## 结论

在下列条件同时满足时，Android 的覆盖安装会保留游戏存档和悬浮按键设置：

1. `applicationId` 保持 `com.game2apk.xianyaoshengcanver22`；
2. 新 APK 使用创建旧 APK 时的同一签名证书；
3. 新 APK 的 `versionCode` 大于旧 APK（本次默认值为 `8`，`versionName` 为 `1.3.0`）；
4. 安装使用 `adb install -r <new.apk>` 或系统的“更新安装”，不卸载、不清除应用数据。

RPG Maker MV 的 `localStorage` 存档位于应用私有 WebView 数据目录，origin 固定为
`https://appassets.androidplatform.net/assets/www/`。模板启用 DOM storage，且启动和销毁流程不会调用
`clearCache`、`WebStorage.deleteAllData`、`deleteDatabase` 或清理应用私有目录。因此构建新 APK 时，重新写入
`assets/www` 只会更新只读资源，不会覆盖手机上已有的存档。

悬浮按键布局、可见性和透明度使用同一应用的 `SharedPreferences`，偏好名称保持为
`game2apk.overlay.v1`，也会随覆盖安装保留。

## 发布前检查

- 不要改变包名、签名 keystore 或 WebView asset origin；改变任一项都会得到新的数据空间，旧存档不会自动出现。
- 不要把 `www/save`、`*.rpgsave` 或手机数据目录复制进 APK；工具的 staging 和 build 校验会拒绝这些输入。
- 不要在升级流程中执行 `adb uninstall`、设置里的“清除存储”或删除应用数据。
- 若需要降级或更换证书，先在游戏内导出/备份存档；Android 不会把不同签名或更低 `versionCode` 的包当作覆盖更新。

## 本次版本

默认配置从 `versionCode=7`/`1.2.0` 提升为 `versionCode=8`/`1.3.0`，包名保持不变。这只满足 Android 的更新判定，
并不会主动迁移、重置或删除任何存档。
