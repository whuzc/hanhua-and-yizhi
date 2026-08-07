# 总设计师模块审查与集成放行条件

日期：2026-08-07

结论：**有条件不放行（No-Go）**。两条实现任务分别完成了可复现的模块级构建和测试，但在真实 `1.221 GiB` 游戏集成前，必须修复下列跨模块缺陷。旧的 `仙肴圣餐超魔改 Ver22/android` 仍只作为失败证据，不得成为模板、输入或产物来源。

## 已确认通过的模块证据

- 目标项目识别为 RPG Maker MV 1.6.1；最终逻辑分辨率为 `1024×768`，不是 MV 默认的 `816×624`。
- Android 模板：12/12 JVM 测试通过；Debug 和 unsigned Release 构建成功；release 非 debuggable、无 INTERNET 权限、zipalign 通过；合成输入桥可把整数键码交给 MV `Input.keyMapper`。
- Windows 工具：14/14 Python 测试和 compileall 通过；便携 CLI `--help` 实际返回 0；便携目录包含 Tcl/Tk 运行文件且不含游戏、存档、API key、keystore 或密码文件。
- 复核目标游戏得到 `2524` 个 `www` 文件、`1,311,499,268` 字节、70 个启用插件；现有工具正确识别 A→公共事件 25、W→公共事件 294、Ctrl→跳过。

## 必须修复的阻断项

### P0：短按脉冲可能完全不被 MV 帧采样

`TapGestureStateMachine` 的单击/双击和系统返回当前在同一调用中连续发送 key-down/key-up。MV 1.6.1 的 `Input.update()` 只在帧更新时比较 `_currentState`；若抬起发生在下一帧前，Enter/Esc 将从未呈现为按下状态。

放行要求：tap/系统返回/`mode=tap` 必须让 key-down 至少跨过一个渲染帧或一个有上界的最短时长后再 key-up；销毁、取消和页面切换必须释放所有键，且新增测试不能只断言 action 列表顺序，还要模拟 MV 帧采样。

### P0：MV 对话和滚动文本提取契约错误

当前测试夹具把 MV 的事件码 101 伪造成 5 参数并把正文塞进参数 4，又把 105 的参数 0 当正文。真实 MV 结构是：

- 101 通常有 4 个参数，正文位于后续 401 命令；
- 105 的参数是滚动设置，正文位于后续 405 命令。

目标游戏中实测有 `10,911` 个 101 和 `19,612` 个 401，而当前提取结果的 message 数是 `0`；因此 FakeTransport 测试通过不能证明翻译功能可用。

放行要求：按 MV 结构提取 101/401、105/405，并兼容可选的第五个说话人参数但不把它当唯一正文；用真实结构夹具覆盖多行、空行、选择、占位符、缓存恢复和失败不落盘。翻译仍只能修改标记工作副本。

### P0：生成目录删除发生在 marker 严格验证之前

`BuildService.prepare_template()` 会先根据传入的 `stage.staged_www` 推导并删除既有 `android` 目录，ASCII mapper 的 marker/project-id 校验却在之后才执行。伪造或损坏的 manifest 不得拥有任何递归删除能力。

放行要求：任何删除/覆盖前先验证精确结构 `.work/<project-id>/runs/<run-id>/staged/www`、项目 marker、project id、manifest 所属 run 和路径边界；加入恶意/伪造 manifest 回归，证明外部同名 `android` 目录保持不变。

## 真实集成前必须完成的高优先级项

- 源不变性快照必须遍历并哈希 `save/` 内的私人存档，同时把它们列入 excluded 清单；复制阶段仍排除它们。当前目录剪枝会让存档既不复制也不进入不变性证据。
- 日文检测必须统计平假名/片假名，不能把“含汉字的日文”自动判成已汉化；目标项目以中文为主时仍应默认跳过 DeepSeek。
- `buttons[].mode` 必须真正生效：A/W 的 `tap` 为有帧宽度的短按，Ctrl 的 `hold` 随触摸按住/释放。
- Activity 固定或传感器限制为横屏，并保持 4:3 游戏画面在不同手机比例上的可用性；不得硬编码 816×624。
- 便携目录必须携带干净的 `templates/android-rpgmv` 源模板（排除 build、缓存、APK、状态和签名材料），默认 GUI 模板路径应真实存在。
- GUI 必须允许设置正整数 `versionCode`；首次签名应安全生成或接收密码并稳定复用同一 applicationId 的证书。
- 完整 `run`/GUI 在静态验收通过后必须把签名 APK 复制到明确的 `dist` 交付路径；单独 `sign`/`verify` 命令也应发现已配置 Android 工具链。
- APK 验收除包名、版本、release 非调试、关键资产、存档排除、zipalign、apksigner、证书、SHA-256 和新鲜度外，还必须显式验证无 INTERNET 权限，并将 stage manifest 与 APK 内的 `assets/www` 清单对账。

## 真实游戏集成放行清单

1. 先修复以上项目并复跑 Python、Java、Node/MV 帧采样测试。
2. 对原 `www` 建立包含私人存档的完整 SHA-256 快照；只在 marker 保护的 `.work` 副本中补丁，默认跳过本游戏翻译。
3. 中文路径下仅通过临时 ASCII `subst` alias 加 `--no-daemon` 执行 Gradle；所有子进程退出后在 `finally` 解除映射。
4. 生成稳定 release keystore，签名后进行完整静态验收并把唯一合格 APK提升到 `dist`。
5. 无连接设备时只声明“已签名静态候选”；只有 `adb install -r`、冷/热启动、地图/菜单/战斗、加密图像/音频、存档和多点触控通过后，才可声明真机可玩。

