# NRadio NBCPE (WT9111) · OpenWrt

为鲲鹏 NRadio NBCPE（WT9111）构建的 OpenWrt 固件。基于官方 `mediatek/filogic` Snapshot，使用主线 `mt76` Wi-Fi 驱动和官方 LuCI Bootstrap。OpenWrt 安装在 eMMC **第二系统**分区（`kernel_2nd` + `rootfs_2nd`），原厂系统完整保留、可随时切回。

适用于配备 MT7981B、MT7531 交换机、GPY211B 2.5G WAN PHY 和 MT5700M-CN 5G 模组的 NBCPE。

## 刷机教程

### 1. 准备固件

- 确认原厂固件 NROS **1.9.x**（本方案在 NROS-1.9.4.n3.c4 上逆向验证）。
- 下载 Release 中的 `openwrt-mediatek-filogic-nradio_nbcpe-squashfs-sysupgrade.bin` 和 `sha256sums`，校验应为 `OK`：

  ```sh
  awk '/-squashfs-sysupgrade[.]bin$/' sha256sums | shasum -a 256 -c
  ```

- 刷机前建议先备份原厂配置（原厂 Web「Backup / Flash Firmware → Download backup」）。原厂 `factory`（Wi-Fi 校准）、`bdinfo`（设备信息）等分区在 OpenWrt 下只读，刷机不会触碰。

### 2. 在原厂系统烧录第二系统

1. 网线连接电脑与路由器 **LAN** 口，登录 [192.168.10.1](http://192.168.10.1/)（原厂管理密码）。
2. 进入 **高级设置 → 系统 → Backup / Flash Firmware**。
3. 在 **Flash second system** 区域点击 **Image** 选择已校验的 `sysupgrade.bin`，点击 **Flash**。该镜像为未签名 `ustar` 格式的 OpenWrt 标准升级包，原厂烧录器会将其写入 `kernel_2nd`（内核 FIT）与 `rootfs_2nd`（squashfs + f2fs overlay）。
4. 等待页面提示烧录成功。点击同页面的 **Switch system**，确认后设备重启进入第二系统（OpenWrt）。

### 3. 首次进入 OpenWrt

保持网线连接 LAN 口，电脑通过 DHCP 获得 `192.168.1.x` 地址后访问 [192.168.1.1](http://192.168.1.1/)。

| 项目 | 全新安装默认值 |
| --- | --- |
| OpenWrt 管理地址 | `http://192.168.1.1` |
| LuCI 账号 | `root`，首次登录密码为空 |
| 2.4 GHz Wi-Fi | `NRadio-NBCPE-2G`，默认开启 |
| 5 GHz Wi-Fi | `NRadio-NBCPE-5G`，默认开启 |
| 无线密码 | 两个频段均为 `12345678`，WPA2/WPA3 混合加密 |
| 有线端口 | `lan1`–`lan3`（MT7531）为 LAN；`wan`（GPY211B 2.5G PHY）为 PoE/5G 桥接上行 |
| 5G 上行 | MT5700M-CN 经网口桥接，`wan` DHCP 与 `wan6` 共用同一物理口 |

首次登录后请在 **系统 → 管理权** 设置密码，并在 **网络 → 无线** 修改初始无线密码。

## 日常使用

| LuCI 菜单 | 用途 |
| --- | --- |
| **网络 → 5G 蜂窝** | 通过网口 AT 接口采集 SIM、注册、信号、小区和温度；支持手动切换内置/外置 SIM，显示上行接口计数 |
| **系统 → 双系统切换** | 查看下次启动目标，一键切回原厂系统并重启；原厂 Web 的 **Switch system** 可随时切回 OpenWrt |
| **系统 → 在线固件更新** | 检查本仓库 GitHub Release，下载并校验 SHA-256 后一键升级（同时刷新 `kernel_2nd` 与 `rootfs_2nd`，支持跨内核版本） |

OpenWrt 的只读 squashfs 根与可写 overlay 均位于 eMMC `rootfs_2nd` 分区（`/dev/mmcblk0p9`）内。启动保护会在 GPT 分区布局或根文件系统不符合第二系统预期时进入 failsafe，升级流程只选择第二系统的 `kernel_2nd` / `rootfs_2nd`。原厂配置在 `mmcblk0p7` 的 overlay 中，第二系统配置在 `mmcblk0p9` 的 overlay 中，不挂载、导入或共用原厂配置。双系统切换只修改启动环境的 `boot_system`。

### 网口蜂窝通信

原厂 NROS 的 `freq.json` 为 MT5700M-CN 定义 TCP `192.168.8.1:20249`。原厂链路为 LuCI → `infocd` 缓存 → `atsd` → AT over TCP；指令以回车结束。第二系统独立实现默认只读采样，不复制原厂配置或守护进程。已实测 `AT^HCSQ?`、`AT^MONSC`、`AT^CHIPTEMP?` 等响应。

默认网口模式不会执行 USB 重训练、断电恢复、NVRAM 修复或自动改写 SIM/APN。手动切换仅提供“内置 SIM / 外置 SIM”两种，经原厂映射验证；切换会重启模组并暂时中断 5G 上行。SIM 是同一物理模组的状态，两系统都会观察到当前选择，但不会共用路由器配置文件。物理端口共四个：一个 PoE/5G 上行和三个 LAN；`wan6` 是同一上行口的 IPv6 协议接口。针对实测只有一个 /64、没有 PD 的蜂窝上游，默认启用 odhcpd 混合中继，使 LAN/Wi-Fi 客户端也能获得 IPv6。页面统计为接口字节计数，不作为运营商账单。

## 构建与测试

### GitHub Actions

在 Actions 中选择 **OpenWrt ImageBuilder (NRadio NBCPE)**，点击 **Run workflow**。可通过 `extra_packages` 指定预装包，从运行结果的 **Artifacts** 下载固件。工作流运行回归测试并检查镜像元数据、FIT 内核魔数、squashfs 根与设备树。[构建工作流](.github/workflows/imagebuilder.yml)

### 本地 ImageBuilder

在 x86-64 Linux 上从本仓库根目录运行：

```sh
curl -fL -o ib.tar.zst \
  https://downloads.openwrt.org/snapshots/targets/mediatek/filogic/openwrt-imagebuilder-mediatek-filogic.Linux-x86_64.tar.zst
mkdir -p ib
tar --use-compress-program=unzstd -xf ib.tar.zst -C ib --strip-components=1

python3 -B board/inject_imagebuilder.py ib
make -C ib image PROFILE=nradio_nbcpe FILES=files-nbcpe \
  PACKAGES="kmod-usb-net-cdc-ether luci luci-ssl luci-proto-ncm luci-i18n-base-zh-cn luci-i18n-firewall-zh-cn luci-i18n-package-manager-zh-cn iw-full usbutils picocom"
```

输出位于 `ib/bin/targets/mediatek/filogic/`。

### 完整源码编译

在干净的 OpenWrt 源码树中运行：

```sh
./scripts/feeds update -a
./scripts/feeds install -a
python3 -B /path/to/nradio-nbcpe/board/apply.py .
cp /path/to/nradio-nbcpe/board/defconfig .config
make defconfig
make -j"$(nproc)"
```

### 回归测试

```sh
python3 -m unittest discover -s tests -v
```

LuCI 浏览器用例需要 Playwright 和 Chromium：`python3 -m pip install 'playwright>=1.50,<2' && python3 -m playwright install chromium`。

## 仓库目录

| 路径 | 内容 |
| --- | --- |
| [board/](board/) | 设备树、源码与 ImageBuilder 注入脚本、随固件安装的板级文件（mt5700 守护、LuCI 应用、原厂 `ubenv`） |
| [tests/](tests/) | eMMC 启动保护、固件更新、蜂窝状态和 LuCI 交互回归测试 |
| [MT5700M-CN 模组文档](https://github.com/veildawn/nradio-c2000-ultra/tree/main/docs/mt5700m) | 硬件与 AT 指令参考（见 nradio-c2000-ultra 仓库） |

## 致谢

本项目结构与板级方案延续 [nradio-c2000-ultra](https://github.com/veildawn/nradio-c2000-ultra)。
