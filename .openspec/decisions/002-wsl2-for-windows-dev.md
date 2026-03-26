# ADR-002: 使用 WSL2 作为 Windows 开发环境

## 标题

Windows 开发环境使用 WSL2 + PostgreSQL

## 状态

- [x] Proposed
- [x] Accepted
- [ ] Implemented
- [ ] Rejected
- [ ] Deprecated

## 背景

TradingAgents A-share 需要在以下环境运行：
- **开发环境**: Windows 开发者本地环境
- **测试/生产环境**: Linux 服务器

当前问题：
1. PostgreSQL 在 Windows 原生环境配置复杂
2. Windows 和 Linux 的 PostgreSQL 配置差异大
3. 开发环境与生产环境不一致，容易引入环境问题
4. 部分 Python 库在 Windows 上兼容性差

## 决策

我们决定 **在 Windows 开发中使用 WSL2（Windows Subsystem for Linux）运行 PostgreSQL**，确保开发环境与生产环境一致。

## 备选方案

### 备选方案 A: Windows 原生 PostgreSQL

- **描述**: 在 Windows 上直接安装 PostgreSQL
- **优点**:
  - 无需 WSL2，配置简单
  - Windows 开发者熟悉
  - 可直接在 Windows 上运行所有组件
- **缺点**:
  - 与 Linux 生产环境差异大
  - 文件路径、权限模型不同
  - 某些 PostgreSQL 扩展在 Windows 上不支持
  - 需要维护两套配置文档
- **结论**: 拒绝。环境差异会导致部署问题和难以排查的 Bug。

### 备选方案 B: Docker Desktop

- **描述**: 使用 Docker Desktop 运行 PostgreSQL 容器
- **优点**:
  - 环境一致性最好
  - 易于配置和清理
  - 与 Linux 容器行为一致
- **缺点**:
  - Docker Desktop 在 Windows 上性能开销大
  - 需要额外学习 Docker
  - 文件挂载性能差（特别是 WSL2 后端）
  - 许可问题（Docker Desktop 企业使用限制）
- **结论**: 拒绝。性能和许可问题不适合长期使用。

### 备选方案 C: 远程数据库

- **描述**: 使用远程 PostgreSQL 服务器（如 AWS RDS、本地服务器）
- **优点**:
  - 无需本地配置
  - 开发环境完全统一
- **缺点**:
  - 依赖网络连接
  - 开发时延迟较高
  - 多人开发时数据冲突
  - 成本问题（云服务）
- **结论**: 拒绝。网络依赖和多人协作问题是主要障碍。

### 备选方案 D: WSL2 + PostgreSQL（选定）

- **描述**: 在 WSL2 Ubuntu 中安装和运行 PostgreSQL
- **优点**:
  - 与生产环境（Linux）完全一致
  - 性能好（接近原生 Linux）
  - 免费，无许可限制
  - 可使用 Linux 生态的所有工具
  - Windows 和 WSL2 文件互通
- **缺点**:
  - 需要安装和配置 WSL2
  - Windows 需要访问 WSL2 中的数据库
  - 需要额外配置防火墙和端口转发
- **结论**: 接受。WSL2 是当前 Windows 上最接近 Linux 体验的方案。

## 影响

### 正面影响
- 开发环境与生产环境完全一致
- 消除 "在我机器上能跑" 问题
- 可以使用 Linux 原生工具和脚本
- 性能好，接近原生 Linux 体验

### 负面影响
- Windows 开发者需要学习 WSL2 基本操作
- 初始配置需要额外步骤
- 需要维护 WSL2 安装脚本

### 需要采取的行动
- [x] 编写 WSL2 PostgreSQL 安装脚本
- [x] 配置 Windows 访问 WSL2 PostgreSQL
- [ ] 更新开发环境搭建文档
- [ ] 编写 WSL2 常见问题排查指南

## 技术架构

### 环境拓扑

```
┌─────────────────────────────────────────────────────────┐
│                      Windows 10/11                       │
│  ┌─────────────────┐        ┌──────────────────────┐   │
│  │  Python Backend │───────▶│  PostgreSQL (WSL2)   │   │
│  │  Streamlit UI   │        │  Port: 5432          │   │
│  └─────────────────┘        └──────────────────────┘   │
│           │                            ▲                │
│           │                            │                │
│           └────────────────────────────┘                │
│                    localhost:5432                        │
└─────────────────────────────────────────────────────────┘
```

### 网络配置

- WSL2 自动配置端口转发
- Windows 可以通过 `localhost:5432` 访问 PostgreSQL
- 无需手动配置端口转发（WSL2 自动处理）

### 文件访问

- Windows 路径: `C:\Users\<name>\project`
- WSL2 路径: `/mnt/c/Users/<name>/project`
- 建议在 WSL2 中运行项目代码，通过 `/mnt/c` 访问 Windows 文件

## 安装步骤

### 1. 安装 WSL2

```powershell
# 以管理员身份运行 PowerShell
wsl --install
```

### 2. 安装 PostgreSQL（使用脚本）

```bash
# 在 WSL2 中运行
sudo bash scripts/setup_wsl_postgres.sh
```

### 3. 验证连接

```bash
# Windows 或 WSL2 中
psql -h localhost -U trading -d trading_db -c "SELECT 1"
```

## 相关文档

- [PostgreSQL 选型决策](./001-use-postgresql.md)
- [Microsoft WSL2 官方文档](https://docs.microsoft.com/en-us/windows/wsl/)
- [PostgreSQL 官方文档](https://www.postgresql.org/docs/)

## 决策记录

| 日期 | 事件 | 负责人 |
|------|------|--------|
| 2026-03-26 | 决策提出 | 开发团队 |
| 2026-03-26 | 决策接受 | 开发团队 |
| 2026-03-26 | WSL2 安装脚本完成 | 开发团队 |
