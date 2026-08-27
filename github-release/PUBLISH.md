# GitHub 发布指南

按以下步骤将本工具发布到 GitHub。**发布过程不影响本地开发/打包流程**（`github-release/` 目录与 PyInstaller、build.bat 完全独立）。

## 1. 创建仓库

1. GitHub 网页新建仓库，如 `bilibili-downloader`（Public / 不要勾选 README 初始化）
2. 复制仓库地址，如 `https://github.com/<用户名>/bilibili-downloader.git`

## 2. 初始化本地仓库

```powershell
# 在项目根目录执行（首次）
git init
Copy-Item github-release\.gitignore .gitignore   # 复制忽略规则
git add .
git commit -m "init: B站视频下载器 v1.0"
git branch -M main
git remote add origin <仓库地址>
git push -u origin main
```

> 注意：`dist/`、`build/`、`ffmpeg/`（139MB，超 GitHub 单文件 100MB 限制）均被 .gitignore 排除，
> 不会上传。exe 通过下方 Release 附件分发。

## 3. 推送后续更新

```powershell
git add .
git commit -m "描述本次改动"
git push
```

## 4. 发布 Release（含 exe）

```powershell
# 运行发布脚本：复制 exe + 生成 SHA256
powershell -ExecutionPolicy Bypass -File github-release\make_release.ps1
```

然后：

1. GitHub 仓库页面 → Releases → Create a new release
2. Tag 写版本号（如 `v1.0.0`）
3. 上传附件：`github-release\release\BiliDownloader.exe`（80MB，< 100MB 单文件限制）
4. 附上发布说明（更新内容、已知问题）
5. 发布后把 Release 的 exe 下载链接贴到 README（见下方"完善 README"）

## 5. 完善仓库

- **截图**：给 `github-release/README.md` 的"界面截图"处放 1-2 张主界面图，展示搜索框与解析结果
- **示例视频**：如需在 README 演示，建议只用免费/自制视频链接
- **Star 引导**：把仓库地址发给朋友或加"如果对你有帮助请 Star"
- **License**：`github-release/LICENSE` 已备好 MIT，上传到仓库根目录

## 注意事项

- exe 80MB 已接近 GitHub 建议的单文件上限（100MB），不要用 Git 提交 exe，只用 Release 附件
- 源码运行需要 ffmpeg：在仓库 README 中注明（Releases 附件或 ffmpeg.org 下载），因为 ffmpeg 无法入库
- 每次发新版 exe：重新运行 `make_release.ps1` 覆盖旧副本，再新建 Release
- 若仓库体积过大（历史提交膨胀），可重新 init 仓库或使用 Git LFS（一般不需要）