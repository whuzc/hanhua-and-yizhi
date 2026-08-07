# 仙肴圣餐超魔改 Ver22 兼容性审计报告

审计日期：2026-08-07（Asia/Hong_Kong）  
审计范围：原游戏 F:\code\汉化加转apk\仙肴圣餐超魔改 Ver22，以及其中的旧 android 失败样本。  
边界：本次只读审计未修改原始 www、存档、旧 Android 源码或 APK；唯一新增文件是本报告。扫描未发现 DeepSeek/API key 集成，也未输出任何密钥。

## 结论

当前状态为 **No-Go，不具备真机发布验收条件**。

- 原游戏内容可以被完整复制到 Android 资产目录；原始 www 与旧样本的 assets/www 已逐文件 SHA-256 比对，2524 个文件全部字节一致。
- 旧 APK 的包名、版本、ZIP 对齐和签名格式可以静态核验，但它是 debug 构建，使用默认 Android Debug 证书，不是可复用的发布签名。
- 旧样本没有需求中的半透明方向摇杆、可关闭控制层、游戏区域单击确定/互动、双击返回/取消。
- 旧样本把原始 3 个存档同时放入 assets/www/save 和 assets/save_import，并在启动时无条件写入 localStorage，存在覆盖用户存档的风险。
- 旧构建脚本路径、SDK 路径和 Gradle 入口不一致，无法作为可复用构建基线；本审计未运行会同步/覆盖旧资产的构建脚本。
- 没有模拟器或真机安装、启动、音频、触控和存档回归证据，因此不能把“APK 存在”或“能静态验签”解释为运行成功。

旧 android 目录仅作为失败样本使用；新实现应从干净、独立、版本化的 Android 模板开始，不能在旧目录上继续修补或把它当作模板基线。

## 1. 原游戏识别与资源画像

| 项目 | 证据与结论 |
|---|---|
| 引擎 | www/js/rpg_core.js:173-183 明确为 RPG Maker MV 1.6.1。 |
| NW.js | 本地 node.dll 为 5,749,248 bytes，ASCII 元数据包含 v9.7.1；nw.dll 含 NW.js 标识，但 Windows 版本资源为空。结合 NW.js 官方 v0.29.0 发布说明中 Node.js 9.7.1 的对应关系，高置信识别为 NW.js 0.29.0；未执行运行期 process.versions.nw，所以精确二进制自报版本仍未验证。[NW.js v0.29.0 官方发布说明](https://nwjs.io/blog/v0.29.0/) |
| 实际逻辑画布 | rpg_managers.js:1792-1795 的 816×624 是 MV 默认值；启用的 YEP_CoreEngine 在 YEP_CoreEngine.js:895-896 读取 Screen Width=1024、Screen Height=768，并在 :1360-1363 覆盖 SceneManager 的 screen/box 尺寸。因此该游戏最终逻辑分辨率为 1024×768（4:3）。 |
| 外层 NW 窗口 | 外层 package.json 的 816×624 是 NW 窗口元数据/默认值，不是该游戏最终逻辑分辨率；它可能造成缩放或裁剪风险。 |
| 游戏 package metadata | www/package.json 的 window metadata 为 1024×768，与 YEP_CoreEngine 的最终逻辑分辨率一致。 |
| 系统数据 | www/data/System.json：gameTitle=[云心汉化组]永生之物魔改 by.呆毛阿卜、locale=ja_JP、versionId=47746208、hasEncryptedImages=true、hasEncryptedAudio=true。加密 key 确实存在，但本报告不记录其值。 |
| www 总量 | 2524 个文件，1,311,499,268 bytes，约 1250.74 MiB / 1.221 GiB。 |

主要扩展名统计：

| 扩展名 | 文件数 | bytes |
|---|---:|---:|
| .rpgmvp | 1718 | 685,426,917 |
| .rpgmvo | 391 | 590,581,679 |
| .json | 201 | 23,164,189 |
| .js | 96 | 4,514,803 |
| .txt | 102 | 483,816 |
| .ttf | 2 | 7,104,892 |
| .rpgsave | 3 | 103,528 |

其余文件包括 3 个普通 .png、3 个 .sfk、3 个 .sfl、1 个 HTML 和 1 个 CSS。代表性 .rpgmvp 与 .rpgmvo 的首 16 bytes 均为 52 50 47 4D 56 ...，即 RPGMV 资源头；rpg_core.js:9218-9266 负责校验头部、拆 key 并 XOR 解密，且将 .png/.ogg/.m4a 映射为 .rpgmvp/.rpgmvo/.rpgmvm。

当前没有 .webm、.m4a 或视频资源；但引擎仍含 video 和 WebAudio 路径。.rpgmvo 的 XHR、解密、Blob、AudioContext 解码必须在目标 Android 设备上实测，不能由静态文件存在性推断通过。普通 icon/icon.png、img/system/Loading.png、img/system/Window.png 是明文 PNG，迁移工具必须保留这些例外，不能简单把所有 PNG 改名为 .rpgmvp。

## 2. 插件与运行时兼容性

www/js/plugins.js 共 78 项，启用 70 项，禁用 8 项。以下为按插件清单逐项归类的静态结果；“兼容”只表示未发现当前文件中的 Node/NW 专属调用，不等于真机运行已通过。

### 2.1 静态兼容组：启用且未发现 Node/NW 专属调用的 66 项

SkipPartyCommand、TMEquipSlotEx、RandomTreasure、TinyGetInfoWnd、TMBattleMist、TMBattlerEx、MPP_ChoiceEX、YEP_MainMenuManager、MessageWindowHidden、UTA_MessageSkip、YEP_MessageCore、SceneGlossary、FTKR_SkillTreeSystem、dsPassiveSkill、TMGreedShop、YEP_EventMiniLabel、AnotherCurrencyShop、TMSoloMenu、DTextPicture、MenuCommonEvent、MPP_DeleteSelfSwitch、TemplateEvent、BMSP、BMSP_MapFog、PictureVariableSetting、TMBalloonLoop、dsShowBattleCommand、FTKR_ExBattleEvent、FTKR_ExVariablesChange、YEP_BaseTroopEvents、BeforeCommon、SupponShopStock、YEP_EventChasePlayer、BattleResultsPopup、BattleEffectPopup、TerraxLighting、TMCommonEventKey、Mano_GamePadConfig、MenubackGround、FixImageLoading、StopSelfMovementWithPlayer、TriggerOnEquipAndState、SSEP_BattleSpeedUp_v2、EmpBtMesNonView、ExcludeMaterialGuard、AltKeyDisable、gameEnd、BattleStartFlash、SRD_BattleLogUpgrade、setItemMax、DrainExtend、CustomizeAttackGuard、SAN_Imp_SkipParallelEventPreload、ChangeSurpriseRateByDir、EventNoLock、AutomaticState、YEP_RegionRestrictions、GraphicsRenderFix、HighSpeedBossCollapseEffect、EventReSpawn、nonStopCharacter、varIDforPlugin、BigEnemy、HIME_EnemyReinforcements、MyselfPlugins、BattleParallelEvent。

### 2.2 需补丁、配置或负向测试的 4 项

YEP_CoreEngine、GraphicalDesignMode、YEP_SkillCore、YEP_X_ActSeqPack1 含 require('nw.gui') 或 fs/path 相关路径，但当前均受 Utils.isNwjs()、测试模式或设计模式条件保护。Android WebView 中 require/process 不应存在；新模板仍应在构建时禁止 ?test/设计模式入口，并加入“启动、菜单、战斗、存档”负向测试，确认这些分支不会被触发。

### 2.3 当前禁用、Android 配置中必须禁止重新启用的 8 项

Escape100、Trb_VisualizationPassable、BackUpDatabase、MadeWithMv、YEP_BattleEngineCore、YEP_BattleAICore、YEP_ButtonCommonEvents、VanguardAndRearguard。

其中 BackUpDatabase 明确使用 require('fs')、require('path')、process.mainModule 和文件复制/写入；禁用的 YEP_BattleAICore 也含 require。若启用，将从浏览器 WebView 兼容问题升级为明确阻断。其他禁用项未作为当前运行路径验收，不应在 Android profile 中随意打开。

### 2.4 核心运行时风险清单

| 项目 | 静态证据 | 判定 |
|---|---|---|
| fs/path/require/process | rpg_core.js:206-208,3207-3210 和 rpg_managers.js 的 NW 本地存档分支；启用插件中有上面的 4 个受保护分支。 | WebView 当前应走非 NW 分支；需补丁/负向测试。 |
| Buffer | 未发现启用插件对 Node Buffer 的实际依赖；广搜命中主要是浏览器/Pixi 语义，不能当作 Node Buffer 证据。 | 暂无明确阻断，仍需打包后运行扫描。 |
| 存档 | StorageManager.isLocalMode 由 Utils.isNwjs() 决定；非 NW 路径使用 localStorage。 | 机制可迁移，但 WebView origin、容量、升级保留和异常恢复未真机验证。 |
| WebAudio | rpg_core.js:7707-7789 创建 AudioContext、加载解密音频并做 Blob 解码。 | 需真机验证 BGM、SE、暂停/恢复和低内存行为。 |
| 视频 | rpg_core.js:2113+、2498-2506 有 video 创建/播放路径；当前资源清单无视频。 | 当前内容未触发，未来内容为未知阻断。 |
| 大小写 | 2524 个路径未发现大小写不敏感重复；文本引用启发式未确认大小写错误，但动态数据库/插件路径仍未知。 | Android APK 区分大小写，迁移工具必须生成并校验路径 manifest。 |
| 鼠标/触摸/键盘 | TouchInput 监听鼠标和触摸；Scene_Map/窗口可消费触摸；Input 映射方向、Z=确定、X=取消。 | 基础 MV 触摸可用性未替代需求中的双击取消语义。 |

TMCommonEventKey 将 A(65)、W(87) 映射到插件参数中的公共事件 25、294；旧样本发送 A/W 不是通用的“物品/传送”接口，只是触发该游戏配置的公共事件。Mano_GamePadConfig 的 moveButtons=false 和 navigator.getGamepads 只涉及实体/浏览器手柄，不能视为已经有虚拟摇杆。

## 3. 原始 www 与旧 Android 资产对比

执行了全量相对路径、文件大小和 SHA-256 比较：

- 原始 www：2524 文件，1,311,499,268 bytes。
- android/app/src/main/assets/www：2524 文件，1,311,499,268 bytes。
- 缺失路径 0，多余路径 0，大小差异 0，字节差异 0。
- plugins.js、GraphicalDesignMode.js、BackUpDatabase.js 等抽样文件也字节一致。

因此旧样本相对当前原始 www 没有可证明的 Android 专用资源改动。README 中关于“禁用 BackUpDatabase、给 GraphicalDesignMode 加 try-catch”的文字只能说明历史意图，不能当作当前 Android 资产差异证据。

存档例外：

- 原始 www/save 有 config.rpgsave 272 bytes、file11.rpgsave 101,812 bytes、global.rpgsave 1,444 bytes，共 103,528 bytes。
- 旧样本另有 assets/save_import 的同名 3 个文件，逐个字节一致。
- APK 同时包含 assets/www/save/* 和 assets/save_import/*，所以存档在 APK 内重复。
- build.ps1:55-102 先全量复制 www（仅排除 save_import 目录），随后再把 www/save 复制到 assets/save_import。

全量复制还会把源目录中的备份/开发文件目录一并带入；当前没有源资产缺失，但没有版本化 manifest、排除规则和构建哈希，后续手工同步容易产生过时或重复资产。新工具应默认不把开发存档打入正式 APK。

## 4. 旧 Android 失败样本审查

### 4.1 WebView 与安全设置

MainActivity.java 使用 file:///android_asset/www/index.html，开启 JavaScript、DOM Storage、Database、file/content access、硬件加速、横屏 sensor，并设置 LOAD_NO_CACHE 和无需用户手势的媒体播放。没有 WebViewAssetLoader 或受控本地 origin；没有自定义 WebChromeClient 能力处理；AndroidSaveImport JavaScript bridge 只做了基本对象绑定，没有 caller/origin 校验。

Manifest 还声明了 INTERNET、usesCleartextTraffic=true、allowBackup=true 和 largeHeap=true。这是一个离线游戏，网络和明文流量设置没有被当前需求证明为必要；安全基线应在新模板中收紧。若未来使用 DeepSeek，只应在 Windows 翻译工具阶段调用，运行时 APK 不应携带 key 或依赖网络。

### 4.2 触控、按键和返回键

布局只有 3 个半透明 ImageButton（alpha 约 0.35）：

- 左上 Skip：短按发送 Ctrl(17)，长按发送 PageDown(34)；
- 右上 Item：发送 A(65)；
- 右侧中部 Warp：发送 W(87)。

不存在方向摇杆、确定/取消键、可关闭/隐藏控制层或多点触控状态。按钮覆盖 WebView 区域，会拦截所在区域的触摸；“不遮挡游戏操作”只是注释，不是行为证据。sendKeyToGame 通过合成 KeyboardEvent 注入 80 ms 的 keydown/keyup，是否被目标 WebView/MV 版本稳定接收未验证。

原 MV 的普通 TouchInput 可能支持单击地图/窗口，但旧样本没有实现游戏区域单击与双击的应用级状态机。onBackPressed 的逻辑是 Android 返回键双击退出应用，不是游戏区域双击发送取消/返回，因此不满足需求。

### 4.3 存档导入

onPageFinished 每次页面完成后都会调用 importSavesIfPresent，把 assets/save_import 内容写入 RPGMV_* localStorage key；没有一次性迁移标记，也没有导出/备份/冲突选择。独立的 save_import_helper.js 虽然尝试“仅当 key 不存在才写入”，但 native 代码已经无条件写入，不能消除覆盖风险。

### 4.4 构建可复用性

- build.gradle 使用 Android Gradle Plugin 8.13.2，wrapper properties 声明 Gradle 8.13，但目录没有 gradlew.bat。
- build_apk.bat 硬编码旧路径 F:\code\仙肴圣餐超魔改 Ver22\android 和不存在的 Gradle 8.2 安装路径。
- local.properties 指向不存在的 C:\Users\24713\AppData\Local\Android\Sdk；实际可见 SDK 为 F:\AndroidDev\android-sdk。
- build.ps1 会同步/写入旧 assets，不符合本次只读边界，因此未执行。

## 5. 现有 APK 静态验收

目标文件：android/app/build/outputs/apk/debug/app-debug.apk

| 项目 | 实测结果 |
|---|---|
| 大小 | 1,302,561,098 bytes，约 1242.22 MiB / 1.213 GiB |
| 创建时间 | 2026-05-14 01:59:18 +08:00 |
| 最后写入 | 2026-05-14 01:59:20 +08:00 |
| SHA-256 | CE8869E385B660B229A3ACF3F27D269BF4C63EBFD87177A49711AA4F31B7A590 |
| 包名 | com.ambrosia.game |
| versionCode / versionName | 1 / 1.2 |
| minSdk / targetSdk | 24 / 34 |
| compile SDK | 34 |
| 标签 | 永生之物 |
| debug | debuggable=true |
| 对齐 | zipalign -c -v 4 通过 |
| 签名 | apksigner verify --verbose 通过；v2=true，v1/v3/v3.1/v4=false |
| 证书 | 默认 C=US, O=Android, CN=Android Debug，RSA-2048；证书 SHA-256 为 384fa615647c2871f19e47d0f977d604e99b17cd344a51fec645b0b0c23c5f58 |

APK ZIP 检查确认 assets/www 2524 项、未压缩总量 1,311,499,268 bytes，并同时存在 assets/www/save 与 assets/save_import 两份存档。当前只找到 debug APK，没有可验收的 release APK 和可复用发布证书。

AAB/PAD/Google Play 不在本项目目标内，本审计不展开。

针对大型单 APK，发布门槛应额外要求：构建机和目标设备有足够的 staging/install 空间，建议可用内部空间至少为当前 APK 的 2 倍并按 3 GiB 预算；必须实际侧载安装并启动，不得仅以 APK 文件生成、静态验签或编译成功作为结论。

## 6. 已执行检查与明确未验证项

已执行的只读检查：

1. 盘点原游戏、旧 Android 目录、资源扩展名、文件数量、总字节数和时间戳。
2. 解析 MV package.json、System.json、plugins.js、Android Manifest；确认 70/8 插件状态。
3. 对原始 www 与 assets/www 的 2524 个相对路径逐一做大小和 SHA-256 比较。
4. 检查加密资源头、明文 PNG 例外、Node/NW/fs/path/require/process/Buffer、WebAudio/video、localStorage、键盘/触摸和大小写路径。
5. 对 APK 执行 ZIP 内容检查、aapt dump badging、aapt dump xmltree、zipalign 校验、apksigner verify 和证书打印。
6. 扫描 www 与 Android 源码中的 DeepSeek/API key 关键词；未发现匹配，未输出任何密钥。

明确未验证：

- **未真机验证**，也未完成模拟器安装/启动；没有 adb install、首次启动、升级安装和真实存档回归证据。
- 未验证 WebView 对 1024×768（4:3）缩放、触摸坐标、合成键、WebAudio、BGM/SE、视频、后台恢复、内存峰值和超大 APK 安装空间的行为。
- 未验证 Android 文件系统大小写在全部动态资源路径上的运行结果。
- 未执行旧样本 Gradle 构建，因为无 wrapper、入口路径过时且资产同步脚本会改变旧目录。

## 7. 推荐的新架构：迁移工具 + 版本化 Android 模板 + 翻译流水线

### 7.1 干净的迁移工具

建立独立的 migration-tool，输入只读原游戏目录，输出带版本号的 staging 目录和 manifest：

- 自动识别 MV 版本、NW.js 版本证据、YEP_CoreEngine 最终 1024×768（4:3）逻辑画布、加密扩展和明文例外。
- 生成大小写敏感路径清单、每个文件 SHA-256、源版本和生成时间；复制前后做完整性校验。
- 默认排除 www/save、开发备份和临时文件；用户存档走运行时导入/导出，不随正式 APK 固定打包。
- 保持 .rpgmvp/.rpgmvo 原样，由 MV 运行时代码解密；禁止把普通 PNG 例外误处理。
- 以失败即停的规则拒绝缺文件、大小写歧义、重复目标路径、加密头异常和 manifest 漂移。

### 7.2 独立、版本化 Android 模板

新建例如 android-template-v1，与旧 android 完全隔离：

- 使用可锁定的 Gradle wrapper、SDK/build-tools、JDK 和构建参数；路径由配置注入，不硬编码个人目录。
- 用受控的本地资源加载方案（优先 WebViewAssetLoader 或等效安全 origin），关闭不必要的网络、明文流量和宽泛 file access。
- Native/JS 控制层实现多点触控方向摇杆、关键按键、半透明可关闭/隐藏状态，并把逻辑坐标固定映射到 1024×768（4:3）；外层 816×624 NW 窗口值不得作为 Android 逻辑画布。
- 为游戏区域建立单击/双击状态机：单击发送 MV 确定/互动，双击发送取消/返回；在窗口、地图、消息和战斗场景分别测试，避免与原有 TouchInput 竞争。
- 由 OnBackPressedDispatcher 分离 Android 系统返回、游戏取消和退出确认；不把返回键双击退出混同为游戏区域双击。
- 存档导入只允许显式一次性迁移，有版本标记、冲突策略和可选导出；不覆盖已有存档。
- 发布构建必须使用仓库外或安全存储中的 release keystore；记录包名、versionCode、versionName、证书指纹和升级兼容策略，禁止把 debug 证书当发布身份。

### 7.3 离线翻译流水线

Windows 工具负责从数据库、事件、插件参数和可识别文本中抽取稳定 ID，生成源文本哈希、译文、审校状态和回滚记录。DeepSeek 仅作为可选的预翻译后端，凭据由用户在工具运行时提供并留在凭据存储/环境中；不写入源码、翻译包、日志或 APK。运行期使用已经审校的离线译文，不依赖网络。

### 7.4 单 APK 体积策略

本项目目标是大型单 APK 侧载：消除重复存档、源备份和无用临时资产，按扩展名明确压缩/不压缩规则，构建后固定记录 APK SHA-256；在目标设备上以“可用空间预算、安装、首次启动、加载大图/音频”作为一个整体验收。若目标设备无法在足够空间下完成侧载、安装或启动，应直接 No-Go，而不是用“编译通过”替代。

## 8. MVP、后续增强与 Go/No-Go 门槛

### MVP

1. 原始资源 manifest 全量一致，默认不打包样例存档。
2. 干净模板可生成并稳定签名一个 release 单 APK。
3. 1024×768（4:3）游戏区域正确显示，摇杆八方向/斜向输入可用。
4. 单击确定/互动、双击取消/返回，控制层可关闭/恢复。
5. localStorage 存档新建、保存、读取、一次性导入和升级保留通过。
6. BGM、SE、地图、菜单、战斗和大资源加载通过。

### 后续增强

可配置按键布局和透明度、外接手柄、存档导出/导入 UI、崩溃/资源诊断、翻译审校界面、增量资源包和多游戏 profile。它们不能降低 MVP 的真机门槛。

### Go 条件

- 源/生成 manifest 和 SHA-256 无漂移，无缺失、大小写冲突和意外存档。
- release APK 使用固定可复用证书；zipalign 通过，apksigner 验证通过，包名和版本符合升级策略。
- 目标真机有足够安装空间，成功侧载安装并首次启动；退出、重启、后台恢复和升级安装不丢档。
- 摇杆、单击、双击、按键隐藏/恢复、菜单/战斗、BGM/SE 和超大资源均有真机记录。

### No-Go 条件

任何关键资源缺失或大小写失败、Node/NW 分支在 WebView 被触发、存档被无条件覆盖、只有 debug 签名、安装空间不足、无法真实安装启动、关键输入语义不符，均不得发布。
