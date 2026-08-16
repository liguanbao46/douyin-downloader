# 抖音主页作品批量下载工具 v3.8+

> 基于 Python + PyQt6 的抖音主页作品批量下载工具，支持视频、图集、实况图下载及 Excel 导出。
> 本项目在 [yanruying/douyin-downloader](https://github.com/yanruying/douyin-downloader)（MIT License, Copyright (c) 2025 颜如嘤）基础上重构与增强，仅用于学习与研究，禁止任何商业或违法用途。
>
> a_bogus 算法来源于开源项目 [Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API)

---

## ✨ 本分支的主要增强

| 增强项 | 说明 |
| ------ | ---- |
| 🎯 **作品级视图** | 列表按作品分组展示，10 列信息（选择 / 序号 / 作者 / 提取方式 / 作品类型 / 作品标题 / 时长·数量 / 分辨率 / 下载状态 / 发布时间） |
| 🗂️ **主页列表批量提取** | 主页列表勾选多个作者，一键批量提取作品（列表累加展示，不覆盖已获取内容） |
| 👤 **按作者分文件夹下载** | 批量提取多个主页后，每个作者的作品自动进入各自文件夹 `作品下载/{昵称-unique_id}/视频|图集/` |
| 📁 **路径结构优化** | 视频进 `视频/`，图集进 `图集/{日期}_{标题}/`，文件名简化为 `1.jpeg`/`live1.mp4`；避免超长文件名 |
| 🛠️ **长标题下载修复** | 修复 Windows 目录名以点/空格结尾导致 `os.makedirs` 静默失败、进而 `[Errno 2]` 的问题 |
| ⏰ **文件时间=发布时间** | 可选：下载完成后将文件修改时间设为作品发布时间（`os.utime`） |
| 🔍 **搜索过滤** | 作品列表上方搜索框，按标题/作者实时过滤 |
| 📊 **导出增强** | 导出 URLs / 导出 Excel；状态栏显示已获取作品数 |
| 📂 **打开文件夹** | 一键打开下载目录按钮 |
| 📦 **单文件 exe** | 支持 PyInstaller 打包成带图标的单文件可执行程序（开箱即用） |

---

## 🚀 快速开始

### 方式一：直接运行 exe（无需 Python 环境）

前往 [Releases](../../releases) 下载 `抖音下载器.exe`，双击运行即可。

### 方式二：从源码运行

```bash
git clone https://github.com/liguanbao46/douyin-downloader.git
cd douyin-downloader
pip install requests PyQt6 openpyxl gmssl
python main.py
```

### 配置 Cookie

1. 点击「设置」→「查看教程」按说明获取你的抖音 Cookie
2. 填写后保存（Cookie 具有时效性，失效后重新获取）

### 下载作品

1. 输入抖音主页链接（支持短链）
2. 点击「获取作品」开始解析
3. 列表中勾选要下载的作品
4. 点击「开始下载」

> 💡 批量提取：在「主页列表」对话框里添加多个主页并勾选，点「提取作品」可一次性把多个作者的作品全部列出。

---

## 📁 下载目录结构

```
作品下载/
└─ 昵称-unique_id/
   ├─ 视频/
   │  └─ 2024-02-18_作品标题.mp4
   └─ 图集/
      └─ 20240218_作品标题/
         ├─ 1.jpeg
         ├─ 2.jpeg
         └─ live1.mp4
```

- 视频：`视频/{日期}_{标题}.mp4`
- 图集：`图集/{日期}_{标题}/` 独立子文件夹，图片按序号命名
- 若勾选「修改文件时间为发布时间」，文件 mtime 将设为作品 `create_time`

---

## 📊 Excel 导出

可将抓取到的作品信息导出为 `.xlsx`，包含字段：类型 / 发布时间 / 文案 / 合集 / 点赞数 / 评论数 / 收藏数 / 分享数 / 推荐次数 / 视频时长 / 作品链接。

导出默认保存于：`作品数据Excel/用户名.xlsx`

---

## ⚙️ 配置文件

程序自动生成 `config.ini`（**含 Cookie，请勿提交到公开仓库**）：

```ini
[main]
path = D:\Downloads\Douyin
use_mix_folder = True
include_date_in_filename = True
threads = 8
set_file_time_to_publish_time = False
cookie = your_cookie_here

[users]
user1 = 张三,https://www.douyin.com/user/MS4wLjABAAAAxxxx
```

---

## 🧩 项目结构

```
douyin_downloader/
├─ core/        # 解析、下载、API、导出
│  ├─ parser.py        # 作品级解析（parse_awemes_to_works）
│  ├─ downloader.py     # 单文件下载（含 mtime 修改）
│  ├─ api.py           # 抖音 API 请求
│  └─ abogus.py        # a_bogus 算法（vendored）
├─ gui/         # PyQt6 界面
│  ├─ main_window.py   # 主窗口（作品级 10 列视图、批量提取、按作者分文件夹）
│  ├─ worker.py        # 后台线程（获取/下载，含按任务 base_folder 路由）
│  ├─ dialog_userlist.py  # 主页列表对话框
│  └─ dialog_settings.py  # 设置对话框
├─ utils/       # 文件名/目录计算、配置读写
└─ tests/       # 解析器单元测试
```

---

## 💡 常见问题（FAQ）

**Q1：程序打不开或界面闪退？**
A：确认已安装 PyQt6：`pip install PyQt6`

**Q2：提示 Cookie 错误？**
A：Cookie 具有时效性，请重新获取并更新。

**Q3：如何加快下载速度？**
A：在设置中调高线程数（建议 ≤8），过高可能被风控。

**Q4：图集下载报 `[Errno 2] No such file or directory`？**
A：通常是作品标题过长或含特殊字符导致目录创建失败，本版本已修复尾部点号问题；若仍出现请检查下载路径所在磁盘是否可写。

**Q5：批量提取多个主页后作品都下到一个文件夹了？**
A：本版本已修复——每个作品按其自身作者分文件夹，确保各作者作品独立存放。

---

## 🖼️ 运行截图

> 以下为实际运行界面示意：

![主界面截图](https://raw.githubusercontent.com/liguanbao46/douyin-downloader/refs/heads/main/251023013355554.png)
![设置界面](https://raw.githubusercontent.com/liguanbao46/douyin-downloader/refs/heads/main/251023013445461.png)
![Excel导出](https://raw.githubusercontent.com/liguanbao46/douyin-downloader/refs/heads/main/251023013738453.png)

---

## 📜 LICENSE

MIT License，Copyright (c) 2025 颜如嘤（原作者）。

⚠️ 禁止将本程序用于任何商业、违法或侵犯隐私的用途，仅供学习与研究，请在合法范围内使用。

---

## 🙏 致谢

- 原项目：[yanruying/douyin-downloader](https://github.com/yanruying/douyin-downloader)
- a_bogus 算法：[Evil0ctal/Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API)
