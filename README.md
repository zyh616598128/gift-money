# 🧧 礼金管理系统

一个简洁的礼金（人情往来）管理工具，用于记录和管理婚丧嫁娶、生日、乔迁等场合的礼金收支。

## 功能特性

- ✅ **礼金记录**：记录人名、金额、事由、日期、备注
- ✅ **分类管理**：支持婚嫁、丧葬、生日、乔迁、开业、生育、探病等分类
- ✅ **查询统计**：按人名、按月份、按类别查询
- ✅ **余额计算**：自动计算应收/应付净额
- ✅ **数据可视化**：分类统计柱状图、月度趋势、人名余额排名
- ✅ **SQLite 存储**：零配置，数据本地持久化

## 项目结构

```
gift-money/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI 后端
│   └── database.py        # 数据库初始化
├── static/
│   ├── index.html         # 前端页面
│   ├── css/style.css      # 样式
│   └── js/app.js          # 前端逻辑
├── requirements.txt       # Python 依赖
├── README.md
└── gift_money.db          # SQLite 数据库（启动后自动生成）
```

## 快速开始

### 1. 安装依赖

```bash
cd D:\gift-money
pip install -r requirements.txt
```

### 2. 启动服务

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 打开浏览器

访问：http://localhost:8000

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python + FastAPI |
| 数据库 | SQLite |
| 前端 | 原生 HTML/CSS/JS |

## API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/transactions` | 查询记录（支持 name/category/month/direction 筛选） |
| POST | `/api/transactions` | 新增记录 |
| PUT | `/api/transactions/{id}` | 更新记录 |
| DELETE | `/api/transactions/{id}` | 删除记录 |
| GET | `/api/transactions/{id}` | 查询单条记录 |
| GET | `/api/categories` | 获取分类列表 |
| POST | `/api/categories` | 新增分类 |
| GET | `/api/stats/summary` | 获取汇总统计 |
| GET | `/api/stats/person/{name}` | 按人名查询统计 |

## 数据说明

- 数据库文件：`gift_money.db`（首次启动时自动创建）
- 默认分类已预置 8 个常用分类，可在分类管理页面新增自定义分类

## License

MIT
