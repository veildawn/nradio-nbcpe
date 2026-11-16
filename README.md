# NRadio NBCPE (WT9111) · OpenWrt

为鲲鹏 NRadio NBCPE（WT9111）构建的 OpenWrt 固件。基于官方 `mediatek/filogic` Snapshot，使用主线 `mt76` Wi-Fi 驱动和官方 LuCI Bootstrap。OpenWrt 安装在 eMMC **第二系统**分区（`kernel_2nd` + `rootfs_2nd`），原厂系统完整保留、可随时切回。

适用于配备 MT7981B、MT7531 交换机、GPY115 2.5G WAN PHY 和 MT5700M-CN 5G 模组的 NBCPE。

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
| 有线端口 | `lan1`–`lan3`（MT7531）为 LAN；`wan`（GPY115 2.5G PHY）为有线 WAN 备用上行 |
| 5G 上行 | MT5700M-CN 自动 NCM 拨号（`wwan`，IPv4/IPv6） |

首次登录后请在 **系统 → 管理权** 设置密码，并在 **网络 → 无线** 修改初始无线密码。

## 日常使用

| LuCI 菜单 | 用途 |
| --- | --- |
| **网络 → 5G 蜂窝** | 管理 SIM1/SIM2，查看注册状态、信号（RSRP/SINR）、小区、温度与流量，配置 APN 与巡检 |
| **系统 → 双系统切换** | 查看下次启动目标，一键切回原厂系统并重启；原厂 Web 的 **Switch system** 可随时切回 OpenWrt |
| **系统 → 在线固件更新** | 检查本仓库 GitHub Release，下载并校验 SHA-256 后一键升级（同时刷新 `kernel_2nd` 与 `rootfs_2nd`，支持跨内核版本） |

OpenWrt 的只读 squashfs 根与可写 overlay 均位于 eMMC `rootfs_2nd` 分区（`/dev/mmcblk0p9`）内。启动保护会在 GPT 分区布局或根文件系统不符合第二系统预期时进入 failsafe，任何情况下都不会写原厂系统分区与 `factory`/`bdinfo` 校准数据。

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
