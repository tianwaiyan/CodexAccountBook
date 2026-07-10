# 个人记账系统

基于 Streamlit 的本地 Web 应用，支持支付宝/微信账单导入、自动去重合并、分类统计分析和数据导出。

## 技术栈

- **前端**: Streamlit (Python)
- **数据库**: SQLite (WAL 模式)
- **数据处理**: Pandas, Plotly
- **打包**: PyInstaller (onedir)
- **启动器**: 批处理 + pythonw 后台运行

## 功能模块

### 📊 仪表盘
- 月度收支概览卡片（收入 / 支出 / 结余）
- 月度收支趋势折线图
- 当月分类占比饼图（支出）
- 平台来源分布饼图（微信 vs 支付宝）

### 📋 流水列表
- 按月份分页浏览所有交易记录
- 关键字搜索（商品说明 / 分类 / 交易对方）
- **行选择 + 批量删除**：勾选多行后一键删除，复选框自动复位
- 金额格式化显示（¥ 符号，千分位）

### 📥 导入账单
- 上传支付宝 CSV / XLSX 账单
- 上传微信 CSV / XLSX 账单
- 自动解析不同平台的导出格式（编码、跳过元数据行、列名映射）
- import_hash 去重机制，重复导入自动跳过
- 导入预览（展开查看新增记录）
- 导出全部流水为 Excel 备份

### ✏️ 手动记账
- 手动添加单笔收支记录
- 支持选择日期、收支类型、金额、来源、分类
- 可选填写商品说明、交易对方、支付渠道

## 项目结构

| 文件 | 说明 |
|------|------|
| pp.py | Streamlit 前端，页面路由与 UI |
| db.py | SQLite 数据库层（建表、CRUD、聚合查询） |
| parser.py | 支付宝/微信账单解析器 |
| launcher.py | 应用启动器（自动分配端口，打开浏览器） |
| 启动.bat | 一键启动脚本（自动杀旧进程，pythonw 后台运行） |
| uild_exe.ps1 | PyInstaller 打包脚本 |
| 
equirements.txt | Python 依赖 |

## 数据库特性

- SQLite WAL 模式（高并发读写）
- usy_timeout=5000ms（避免锁冲突）
- 
ow_factory=sqlite3.Row（字典式访问）
- import_hash 唯一约束（自动去重）
- 索引：trade_time、platform、category
- 连接错误中文提示

## 快速启动

`ash
# 方式 1：双击 启动.bat

# 方式 2：命令行
python -m streamlit run app.py --server.port 8501 --server.headless true

# 方式 3：使用启动器（自动分配端口）
python launcher.py
`

## 打包发布

`powershell
.uild_exe.ps1
`

输出目录：dist\账单合并分析器
## 版本历史

| 版本 | 说明 |
|------|------|
| v1.1 | WAL 模式、冻结路径修复、连接错误处理、自动杀旧进程 |
| v1.2 | 修复 row_factory 回归问题，恢复仪表盘和流水列表功能 |
| v1.3 | 流水列表批量删除 + 复选框自动复位 |
