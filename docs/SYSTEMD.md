# Ubuntu/Debian 原生部署

原生模式适合直接部署在 VPS 上，使用 systemd 管理 Palworld 和面板服务。

## 支持系统

- Ubuntu 22.04 / 24.04
- Debian 12

## 快速开始

```bash
git clone https://github.com/Tensyd/palworld-server-panel.git
cd palworld-server-panel
sudo bash install.sh
```

安装器会：

- 安装系统依赖
- 创建或复用运行用户，默认 `demo`
- 安装 SteamCMD
- 下载 Palworld Dedicated Server
- 生成 `/etc/palworld-panel.env`
- 安装 `palworld.service`
- 安装 `palworld-panel.service`
- 配置受限 sudoers

## 自定义用户和目录

```bash
sudo PANEL_USER=palworld bash install.sh
```

常用环境变量：

```bash
PANEL_USER=demo
PANEL_HOME=/home/demo
PANEL_DIR=/home/demo/palworld-panel
PALWORLD_DIR=/home/demo/palworld
STEAMCMD_DIR=/home/demo/steamcmd
PANEL_PORT=8080
INSTALL_PALWORLD=true
```

## 只安装/修复面板，不下载 Palworld

```bash
sudo INSTALL_PALWORLD=false bash install.sh
```

## 服务管理

```bash
sudo systemctl status palworld-panel.service
sudo systemctl status palworld.service
sudo systemctl restart palworld-panel.service
sudo systemctl restart palworld.service
```

日志：

```bash
journalctl -u palworld-panel.service -f
journalctl -u palworld.service -f
```

## 环境变量文件

安装器会生成：

```text
/etc/palworld-panel.env
```

权限应为：

```text
600 root:root
```

里面包含 RCON 密码、面板密钥、安装路径和服务名。不要提交到公开仓库。

## 修复安装

如果 systemd unit、sudoers 或权限异常，可以使用面板“安装向导”的“修复安装”，也可以手动执行：

```bash
sudo python3 /usr/local/lib/palworld-panel/panel_install.py --repair
```

修复不会主动删除存档。

安装器会把 `panel_install.py` 复制一份到 `/usr/local/lib/palworld-panel/`（`root:root 755`），
`palworld-panel-install.service` 执行的是这份副本，而不是 `/home/demo/palworld-panel/` 里的原始文件。
原因是面板账户拥有自己的目录，同时又有权通过 sudoers 启动安装服务：如果 root 执行的是面板账户能改写的脚本，
拿到面板账户就等于拿到 root。手动修复时也请用上面这条路径。

改了 `panel_install.py` 之后要重新执行一次 `sudo bash install.sh`（或 `--repair`），副本才会更新。
