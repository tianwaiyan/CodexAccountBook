# Project Profile: 个人记账系统

## 项目概述
基于 Streamlit + SQLite 的本地 Web 个人记账应用。支持支付宝/微信账单 CSV/XLSX 导入、自动去重合并、仪表盘可视化分析、流水列表管理、手动记账、Excel 备份导出。通过 pythonw 后台一键启动，浏览器访问。

## 技术栈
- 前端：Streamlit (Python)
- 数据库：SQLite (WAL 模式, row_factory=sqlite3.Row)
- 图表：Plotly (折线图、饼图)
- 数据处理：Pandas, openpyxl
- 打包：PyInstaller (onedir)
- 启动：BAT 脚本 + pythonw 后台无窗口

## 项目文件结构

app.py          — Streamlit 前端（页面路由、UI、图表）
db.py           — SQLite 数据库层（建表、CRUD、聚合查询、WAL 模式、连接管理）
parser.py       — 支付宝/微信账单解析器（编码处理、列名映射、import_hash 去重）
launcher.py     — 启动器（自动分配端口、打开浏览器、PyInstaller 资源路径）
启动.bat         — 一键启动（自动杀旧进程 → pythonw 后台启动 → 打开浏览器 → 自动关闭）
build_exe.ps1   — PyInstaller 打包脚本
requirements.txt
.gitignore      — 排除 data/、*.xlsx、*.csv、dist/、build/

## 数据库 (db.py)

表: transactions
  id               TEXT PK
  trade_time       DATETIME NOT NULL
  platform         TEXT NOT NULL        (支付宝/微信/手动录入)
  trade_type       TEXT NOT NULL        (支出/收入)
  amount           REAL NOT NULL
  category         TEXT DEFAULT ''
  description      TEXT DEFAULT ''
  counterparty     TEXT DEFAULT ''
  payment_channel  TEXT DEFAULT ''
  import_hash      TEXT UNIQUE NOT NULL (去重用)

索引: idx_trade_time(DESC), idx_platform, idx_category

连接特性:
- _get_connection(): conn.row_factory = sqlite3.Row, check_same_thread=False
- get_connection(): @contextmanager 装饰器, 自动 commit/rollback/close
- init_db() 启用 PRAGMA journal_mode=WAL, foreign_keys=ON, busy_timeout=5000
- _db_dir() 兼容 frozen 模式 (sys.executable 父目录)

API:
- init_db()
- insert_transactions(rows: list[dict]) → (inserted, skipped)
- delete_transaction(id: str) → bool
- update_transaction(id, **kwargs) → bool
- query_transactions(year_month, page, page_size, keyword) → (rows, total)
- get_available_months() → list[str]
- get_monthly_stats() → list[dict]        (月度收支汇总)
- get_monthly_category_stats(ym) → list[dict]  (分类支出)
- get_platform_stats(ym) → list[dict]     (平台分布)
- get_month_summary(ym) → dict            (收入/支出/结余)
- get_all_transactions_count() → int

## 账单解析器 (parser.py)

支付宝: 编码 GBK/gb18030, skiprows=24, 列映射 (交易时间→trade_time, 交易分类→category, 收/支→trade_type...)
微信: 编码 UTF-8, skiprows=16, 列映射 (交易时间→trade_time, 交易类型→category, 收/支→trade_type...)
去重: import_hash = MD5(时间 + 金额 + 对方 + 商品说明)

## 页面路由 (app.py)

侧边栏导航: 仪表盘 / 流水列表 / 导入账单 / 手动记账
current_page 状态: session_state["current_page"]

### 1. 仪表盘 (page_dashboard)
- 月份选择下拉框
- 收支概览卡片 (st.metric 风格, 自定义 CSS 样式)
- Plotly 月度趋势折线图 (双线: 收入/支出)
- Plotly 当月各分类支出饼图
- Plotly 当月各平台支出饼图
- 无记录时显示 st.info 提示

### 2. 流水列表 (page_transactions)
- 月份/页码/关键字搜索 三栏筛选
- st.dataframe(selection_mode="multi-row", on_select="rerun")
- 动态 key: tx_table_{counter} — 删除后 counter+1 使复选框自动复位
- 删除按钮: type="primary", disabled=len(selected_rows)==0
- 删除逻辑: sorted(selected_rows, reverse=True) 倒序安全删除
- 无记录时显示 st.info

### 3. 导入账单 (page_import)
- 两个 file_uploader (支付宝/微信)
- 调用 parser.py 的 import_csv_to_db()
- 显示插入/跳过统计
- 预览展开面板
- Excel 备份导出按钮

### 4. 手动记账 (page_manual)
- st.form 表单
- 日期/收支类型/金额/来源/分类/说明/对方/支付渠道
- 提交后插入 DB

## 启动器 (launcher.py)

- find_free_port() 自动分配端口
- resource_path() 兼容 PyInstaller frozen 模式
- 线程异步打开浏览器
- 调用 streamlit.web.cli.main()

## 启动方式

双击 启动.bat:
  1. 查找端口 8501 的 LISTENING 进程并强制关闭
  2. pythonw -m streamlit run app.py --server.port 8501 --server.headless true (后台无窗口)
  3. 等待 4 秒
  4. 打开浏览器 http://localhost:8501
  5. bat 自动关闭

命令行: python launcher.py

## 注意事项

- 数据库文件位置: {项目根目录}/data/account_book.db
- frozen 模式下使用 sys.executable 父目录
- Chinese 路径可能在某些终端显示乱码（内部处理正确）
- 多个 Streamlit 实例不能同时绑定同一端口 — 启动.bat 已处理
- st.dataframe 的 selection_mode 需要 Streamlit >= 1.35