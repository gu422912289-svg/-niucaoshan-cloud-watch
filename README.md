# 牛草山云海预测器 V0.2 — GitHub Pages 发布包

## 当前状态
这是一个静态 HTML 网页，使用 Open-Meteo 的公开天气接口。页面中的指数是启发式条件指数，不是经过历史观测校准的云海概率。

## 发布步骤
1. 登录 GitHub，打开 https://github.com/new
2. Repository name 填 `niucaoshan-cloud-watch`。
3. 选择 Public（GitHub Free 的 Pages 通常要求公开仓库），点击 Create repository。
4. 在新仓库页面点 **Add file → Upload files**，上传本包中的 `index.html` 和 `README.md`，然后 Commit changes。
5. 进入仓库 **Settings → Pages**。
6. 在 Build and deployment 里选择 **Deploy from a branch**；Branch 选 `main`，文件夹选 `/(root)`，点击 Save。
7. 等待 GitHub Pages 部署完成，页面会显示站点网址，通常形如 `https://<你的用户名>.github.io/niucaoshan-cloud-watch/`。

## 发布后测试
- 用手机浏览器打开 Pages 网址，确认页面能加载。
- 点“刷新”，检查综合预报、ECMWF、GFS 三栏是否都返回数据；若某模型报错，不要把空值当成无云海。
- 分别在 Wi-Fi 和移动网络测试一次。
- 由于预测器用近似坐标和启发式指数，出发前仍应对照更近时次的天气预报、低云量、风、降水与现场路况。

## 注意
当前连接的 GitHub 工具没有提供创建仓库或开启 Pages 的管理操作，因此这些设置需要在 GitHub 网页端手动完成。此包并不代表站点已经上线。
