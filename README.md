# Auto Update Alfred Workflows

这是一个 Alfred Workflow。运行后会自动：

1. 扫描你已安装的 workflows。
2. 找出带有 GitHub 仓库信息的 workflow。
3. 检查是否存在更新版本。
4. 自动下载并触发安装更新（如果 release 中有 `.alfredworkflow` 文件）。

## 用法

1. 导入 `Auto-Update-Alfred-Workflows.alfredworkflow`。
2. 在 Alfred 输入 `wfup` 并回车。
3. 等待通知结果。

## 注意

- 只会处理能识别到 GitHub 仓库的 workflow。
- 只有当发布页里包含 `.alfredworkflow` 安装包时，才能自动更新。
- 检查依赖网络。

## 项目文件

- `info.plist`：Workflow 配置
- `run.sh`：Alfred 执行入口
- `update_workflows.py`：检查与更新逻辑
- `Auto-Update-Alfred-Workflows.alfredworkflow`：导入安装包
