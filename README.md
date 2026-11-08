# E-SOPS 电子作业指导书系统

E-SOPS 面向生产现场管理电子作业指导书，将产品、SOP、生产排产和工位作业连接起来。本仓库包含管理后台、服务端和 Web 工位端；实体一体机客户端只提供安装包，不包含客户端源码。

- 在线演示：[https://esops.cc](https://esops.cc)
- 详细使用教程：[https://esops.cc/manual](https://esops.cc/manual)
- 客户端安装包：[官网下载](https://esops.cc/downloads) · [GitHub Releases](https://github.com/luguoyuanf/E-SOPS/releases/tag/v0.1.101)
- 镜像仓库：[Gitee](https://gitee.com/barping/e-sops)

## 功能概览

- **工作台**：汇总 SOP、产线、终端和排产状态。
- **产品和 SOP**：维护产品资料、工序及作业指导内容，支持 SOP 审核。
- **生产与发布**：管理生产订单、排产任务和现场广播。
- **基础资料与设备**：管理车间、产线、工位、员工和终端。
- **Web 工位端**：员工登录后查看工位作业内容并反馈报工。
- **系统管理**：维护租户、用户、角色、权限和文件存储。

页面展示的是官网手册截图，界面可能随版本更新。

### 工作台
![工作台](https://esops.cc/manual/dashboard.png)

### SOP 编辑
![SOP 编辑](https://esops.cc/manual/sop-editor.png)

### 产品管理
![产品管理](https://esops.cc/manual/products.png)

### 排产发布
![排产发布](https://esops.cc/manual/plans.png)

### 产线管理
![产线管理](https://esops.cc/manual/lines.png)

### 终端管理
![终端管理](https://esops.cc/manual/devices.png)

### 报工记录
![报工记录](https://esops.cc/manual/report.png)

### Web 工位端
![Web 工位端](https://esops.cc/terminal-demo.png)

## 技术组成

Vue 3 / TypeScript 管理界面、FastAPI 服务端、MySQL 5.7、Redis、Docker Compose。部署脚本构建 ESOP Edition，数据库使用 Alembic 迁移及必要的系统初始化数据；不会导入现有业务数据库。

## 一键部署

### 环境要求

- Linux 或 macOS 主机，已安装 Docker Engine / Docker Desktop 和 Docker Compose v2。
- 主机需要 Bash、Python 3、OpenSSL、Git，以及可访问容器镜像和依赖包的网络。
- 本机默认使用 `127.0.0.1:18096`；MySQL 和 Redis 不向主机开放端口。
- 在 ARM 主机上，MySQL 5.7 镜像使用 amd64 模拟运行；请确保 Docker 支持该架构。
- 首次构建包含文档处理工具和前端依赖，需要足够的磁盘空间和下载时间。

### 首次启动

```bash
git clone https://github.com/luguoyuanf/E-SOPS.git
cd E-SOPS
./install.sh
```

按提示输入管理员邮箱。脚本生成管理员初始密码、数据库密码和应用密钥，写入仅当前用户可读的 `.env`；随后构建镜像、初始化空数据库并启动服务。保管好 `.env`，尤其是 `SECRET_KEY` 和 `ESOP_ACTIVATION_CIPHER_KEY`；丢失密钥可能导致会话失效或加密数据无法恢复。

首次登录使用 `.env` 中的 `FIRST_SUPERUSER` 和 `FIRST_SUPERUSER_PASSWORD`，租户编码为 `default`：

```bash
# 本机查看初始账号信息；不要将输出发送给他人
sed -n '/^FIRST_SUPERUSER=/p; /^FIRST_SUPERUSER_PASSWORD=/p' .env
```

浏览器打开 [http://127.0.0.1:18096](http://127.0.0.1:18096)。首次登录后请修改管理员密码。后台新手引导可打开租户的 Web 工位端。客户端需要在应用中配置自己的服务地址。

脚本默认将文件保存到 Docker `uploads` 数据卷。发布到公网前，请配置 HTTPS 反向代理与防火墙，并按实际访问地址设置 `.env` 中的 `FRONTEND_HOST` 和 `BACKEND_CORS_ORIGINS`；修改后重新运行 `./install.sh`。例如：

```dotenv
FRONTEND_HOST=https://your-domain.example
BACKEND_CORS_ORIGINS=["https://your-domain.example"]
```

默认仅监听回环地址，可由本机反向代理转发到 `127.0.0.1:18096`；远程管理也可使用 SSH 端口转发。请勿直接将数据库、Redis 或配置文件暴露到公网。

### 状态、日志和停止

```bash
docker compose -f compose.release.yml ps
docker compose -f compose.release.yml logs -f --tail=100
docker compose -f compose.release.yml stop
# 重新启动并检查迁移
./install.sh
```

`stop` 保留数据库、Redis 和上传文件数据卷。不要使用 `docker compose down -v`，除非确定要删除这些数据。

### 备份与恢复

升级前请同时备份数据库、上传目录和 `.env`。以下数据库备份写到当前目录，请妥善保管：

```bash
docker compose -f compose.release.yml exec -T db sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers "$MYSQL_DATABASE"' > esops-backup.sql
mkdir -p backup-uploads
docker compose -f compose.release.yml cp backend:/app/backend/uploads/. ./backup-uploads/
cp .env .env.backup
```

恢复前先确认目标数据库；恢复会覆盖或与已有数据冲突。用原 `.env` 恢复相同密钥，停止应用和后台任务并保留数据库运行，将 SQL 导入目标库，再复制上传备份，最后重新运行 `./install.sh`：

```bash
docker compose -f compose.release.yml stop frontend backend schedule-worker outbox-worker
docker compose -f compose.release.yml exec -T db sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' < esops-backup.sql
docker compose -f compose.release.yml cp ./backup-uploads/. backend:/app/backend/uploads/
./install.sh
```

### 更新与排障

1. 备份数据库、上传文件和 `.env`。
2. 拉取所需版本，运行 `./install.sh`。脚本保留现有配置和数据，迁移由初始化容器执行。
3. 用 `docker compose -f compose.release.yml ps` 检查服务；失败时查看 `logs prestart`、`logs backend` 和 `logs frontend`。
4. 首次构建失败时检查镜像源和依赖网络；端口冲突时修改 `.env` 中的 `ESOPS_PORT`。
5. 登录或上传异常时检查 `.env`、数据库与 Redis 状态、磁盘空间以及反向代理设置。

## 客户端安装包

官网和 GitHub Releases 均提供 Android ARM32、Android ARM64 和 Ubuntu ARM64 安装包。GitHub Release 另提供 SHA-256 校验文件。选择与设备架构匹配的安装包；Windows 暂未提供。安装包为独立发布物，客户端源码不在本仓库中。

## 许可证与第三方声明

本仓库的开源版本采用 [GNU AGPL-3.0](LICENSE)。上游 Fast Vben Admin、Vue Vben Admin 及其他第三方代码和资源保留各自的版权与许可声明，详见 [LICENSES](LICENSES)、[frontend/LICENSE](frontend/LICENSE) 和对应资源目录。实体客户端安装包的许可范围以其随附声明为准。
