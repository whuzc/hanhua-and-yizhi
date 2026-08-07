# android-rpgmv clean template

这是不包含真实游戏资源、存档或签名材料的 Android RPG Maker MV 声明式模板。生成器只应把已检查的 `www` 副本写入 `app/src/main/assets/www/`，并把版本化控制契约写入 `app/src/main/assets/game2apk/config.json`。

## 运行约束

- 单 Activity、`sensorLandscape`、离线 `WebViewAssetLoader`，只加载 `https://appassets.androidplatform.net/assets/www/index.html`。
- Manifest 不声明 `INTERNET`，不使用 `addJavascriptInterface`，外部导航和非 asset 请求拒绝。
- `applicationId`、versionCode、versionName 由生成器安全渲染；release 明确 `debuggable=false`。
- WebView 的 localStorage、MV 存档身份依赖 applicationId、签名和 asset origin；覆盖更新不能改包名、证书或 origin。
- `assembleRelease` 只是 unsigned 输入；上层工具必须使用同一稳定 keystore 签名后再验证和 promote。

## 新输入层

覆盖层只消费实际命中控件，空白游戏区不转成 Enter，而是让底层 WebView 成为原生 touch target。这样 MV 的 `Window_Selectable`/`Window_ChoiceList`、地图目的地和 `TouchInput.isLongPressed/isRepeated` 保持原生语义。

| 控件 | 形式 | MV keyCode |
| --- | --- | ---: |
| ↑ ↓ ← → | hold，抬起立即 release，多点独立 | 38 / 40 / 37 / 39 |
| 确认 | tap pulse / Enter | 13 |
| 取消 | tap pulse / X | 88 |
| ESC | tap pulse / Escape | 27 |
| 立绘 | tap pulse / A；Common Event 25 | 65 |

系统返回键和“两根手指都从游戏区开始”的短二指轻点产生一次 `27`。控制区多点不进入该候选；移动、超时、三指出现都永久失格。原生 WebView 单指流只有在需要接管时才被一份独立 `MotionEvent.obtain` 的 `ACTION_CANCEL` 取消，副本坐标会从 root 转为 WebView 坐标并及时 `recycle`，不会重放或递归派发原始点击。隐藏/恢复和三指长按恢复仍可用，并在页面切换或生命周期结束时 releaseAll。

## 配置契约

`schemaVersion` 为 `1`，要求 `touch`、`overlay` 和恰好八个不重叠按钮：`up/down/left/right/confirm/cancel/esc/portrait`。旧 `tap`、`joystick`、W 87、Ctrl 17 配置会被拒绝。

```json
{
  "schemaVersion": 1,
  "touch": {"cancelKeyCode": 27, "twoFingerWindowMs": 250, "touchSlopPx": 24},
  "overlay": {"opacity": 0.38, "hiddenByDefault": false},
  "buttons": [
    {"id":"left", "label":"←", "keyCode":37, "mode":"hold", "x":0.04, "y":0.80, "width":0.10, "height":0.12},
    {"id":"up", "label":"↑", "keyCode":38, "mode":"hold", "x":0.15, "y":0.67, "width":0.10, "height":0.12},
    {"id":"down", "label":"↓", "keyCode":40, "mode":"hold", "x":0.15, "y":0.82, "width":0.10, "height":0.12},
    {"id":"right", "label":"→", "keyCode":39, "mode":"hold", "x":0.26, "y":0.80, "width":0.10, "height":0.12},
    {"id":"confirm", "label":"OK", "keyCode":13, "mode":"tap", "x":0.67, "y":0.58, "width":0.14, "height":0.10},
    {"id":"cancel", "label":"X", "keyCode":88, "mode":"tap", "x":0.83, "y":0.58, "width":0.14, "height":0.10},
    {"id":"esc", "label":"ESC", "keyCode":27, "mode":"tap", "x":0.67, "y":0.71, "width":0.14, "height":0.10},
    {"id":"portrait", "label":"A", "keyCode":65, "mode":"tap", "x":0.83, "y":0.71, "width":0.14, "height":0.10}
  ]
}
```

## Build checks

```powershell
$env:GRADLE_USER_HOME = 'F:\code\汉化加转apk\.gradle-user-home'
.\gradlew.bat --no-daemon --max-workers=1 compileDebugUnitTestJavaWithJavac
.\gradlew.bat --no-daemon --max-workers=1 assembleDebug assembleRelease
```

独立 JUnitCore 应运行 `app/src/test` 编译出的测试类；Node/Python 回归在上层工具中运行。报告记录实际通过数量和命令退出码，不写易漂移的固定总数。生成器还必须执行 `aapt/aapt2`、`zipalign`、`apksigner`、ZIP asset 对账和 SHA-256 检查。
