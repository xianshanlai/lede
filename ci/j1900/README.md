# J1900 旁路由通用固件

本目录用于在 `xianshanlai/lede` 的 GitHub Actions 中编译 Intel J1900 固件。
编译方法参考了 P3TERX/Actions-OpenWrt、eSirPlayground/AutoBuild-OpenWrt、
KFERMercer/OpenWrt-CI 的分步构建思路，工作流和配置针对当前源码重新编写。

## 固件内容

- x86_64，UEFI 和 Legacy BIOS 两种 SquashFS 磁盘镜像。
- 内核分区 64 MiB，根分区 1024 MiB。
- 中文 LuCI、防火墙 firewall4、OpenClash 和 Mihomo。
- Mihomo 固定使用 **amd64-v1** 构建；J1900 不适合需要 AVX/AVX2 的 v2/v3 构建。
- Samba4、Windows 网络发现 wsdd2、USB 存储、NTFS3、exFAT 和 UTF-8 文件名。
- Aria2、AriaNg、Vlmcsd KMS 服务及对应 LuCI 管理页面。
- DiskMan 磁盘管理、TTYD 网页终端、hd-idle 硬盘休眠、MiniDLNA 媒体共享及对应 LuCI 页面。
- 排除 ksmbd、autosamba 和旧 automount，使用按 UUID 配置的 block-mount。
- 源码、feeds、OpenClash 使用完整 commit 锁定；Mihomo 使用固定版本和 SHA256。

`sources.lock.json` 中的 LEDE 源码目前使用 Linux 6.18、LuCI 25.12。
它不是旧版 6.6 固件的原样重编译。升级前应单独备份当前配置，并评估跨版本恢复。

## 启动编译

1. 打开本仓库的 **Actions**，如有提示，先启用 fork 的 Actions。
2. 选择 **J1900 LEDE firmware** → **Run workflow**。
3. 首次可选择 `config-check`，验证包名、依赖和最终 Kconfig 配置。
4. 选择 `firmware` 进行完整编译。
5. 完成后从该次运行的 **Artifacts** 下载：
   - `j1900-firmware-*`：固件、清单和重新计算的 SHA256。
   - `j1900-packages-*`：本次构建配套软件包，特别是匹配内核的软件包。
   - `j1900-buildinfo-*`：完整编译配置、版本锁和日志；失败时也会尽量上传。

产物保留 14 天。工作流只提供手动触发，不启用定时全量编译、远程 SSH 调试、
第三方网盘上传、自动删除历史运行或自动刷机。原通用工作流也改为手动触发。

## 选择镜像

- UEFI 启动：`*-squashfs-combined-efi.img.gz`。
- Legacy BIOS 启动：`*-squashfs-combined.img.gz`。

下载后可解压 `.gz` 用于写盘，或根据当前 x86 系统升级方式选择镜像。
固件文件名中包含 `efi` 与否决定启动方式。编译成功不代表已通过实体机器启动测试。

## 首次接入家庭网络

全新配置启动时，本固件采用旁路由方式：

- `eth0` 和 `eth2` 为 LAN 桥接端口；使用其中一个连接主路由 LAN。
- 管理地址由主路由 DHCP 分配，主机名为 `LEDE-J1900`。
- 在主路由客户端列表中查找此主机，建议随后设置 DHCP 地址预留。
- 本机不提供 DHCP、DHCPv6 或 RA 服务，WAN 接口不会自动拨号。
- 首次初始化会修改管理地址，请在主路由中查找，而不是继续使用默认地址。
- 上游通用 LEDE 的默认登录账号是 `root`、默认密码为 `password`，首次登录后修改。

初始化脚本仅在识别到默认 LAN 配置时应用旁路由设置；已有非默认网络配置时跳过。
恢复旧备份时仍需检查网口、网关、DNS、防火墙及插件版本，不建议整包覆盖新系统。
IPv4 网关设置不会接管客户端的 IPv6；需要代理的终端须另外处理 IPv6。

## 配置插件

固件不包含任何个人订阅、节点、拨号账号、共享密码、硬盘 UUID 或配置备份。

- **OpenClash**：Mihomo 已内置；导入自己的订阅后再启用，并按规则需要下载 Geo 数据。
  初始不启用代理，开机启动等待时间预设为 60 秒。
- **Samba4**：创建独立共享账号，按所需分区 UUID 挂载并添加共享。不要改用旧 ksmbd 设置。
- **Aria2**：默认停用。先挂载可写数据分区，并设置下载目录和 RPC 密码，再启用。
  `/mnt/downloads` 只是占位目录，不能在未挂载硬盘时直接开始下载。
- **Vlmcsd**：保留功能，默认停用，可在 LuCI 中按需配置并启用。
- **DiskMan**：查看磁盘、分区与挂载信息；SMART 是否可用取决于 USB 硬盘盒支持。
- **TTYD**：默认绑定 LAN，终端使用 `/bin/login`，需要输入系统账号和密码。
- **hd-idle**：默认停用，先在 LuCI 中选择正确的移动硬盘并设置休眠时间，再启用。
- **MiniDLNA**：默认停用，先挂载硬盘并选择需要共享的媒体目录，再启用。
- **硬盘挂载**：在 LuCI 挂载点中按 UUID 设置；不会自动挂载或自动共享所有插入的分区。

修改 `config.seed` 仅影响之后手动触发的编译。已经开始的运行使用其触发时的提交，
不会因后续修改配置而改变，也不会因推送这些修改自动启动新的编译。

## 更新锁定版本

更新 `sources.lock.json` 中的 commit 时，LEDE 与 LuCI/feeds 应保持兼容。
更换 Mihomo 版本时同时更新版本、下载 URL、SHA256，并保持 `linux-amd64-v1`。
每次先运行 `config-check`；如果某个包未被选中或被依赖强制改变，准备阶段会明确失败，
不会悄悄产出缺少所需功能的固件。

本机静态检查：

```sh
python3 ci/j1900/prepare.py --check-inputs
```

真正的 `make defconfig` 和固件编译需要 Linux，均由 GitHub Actions 执行。
