# AI 假发带货视频提示词 RAG 工作台

这是一个面向 Codex 的团队工作仓库。GitHub 保存 PRD、审核后的提示词样例和工具代码；Codex 对话负责生成，本地程序负责检索和确定性校验。

## 同事第一次使用

1. 安装 Git、Python 3.11 或更高版本、Codex 和 [Ollama for Windows](https://docs.ollama.com/windows)。
2. 获得私有仓库权限后克隆并在 Codex 中打开：

   ```powershell
   git clone https://github.com/lzx51998-max/ai-wig-video-prompt-generator.git
   cd ai-wig-video-prompt-generator
   ```

3. 在 Codex 对话中说：`初始化提示词工作台`。
4. 初始化通过后直接描述想要的视频，例如：

   > 生成一个 10 秒的室内视频。黑色中分卷发，明亮客厅，切换到发际线细节和侧面轮廓，最后看向镜头微笑。

更完整的团队流程见 [团队使用指南](docs/TEAM_GUIDE.md)。提示词字段和组装顺序见 [提示词模板](提示词模板.md)。产品硬规则见 [PRD](PRD.md)。

## 本地命令

通常由 Codex 自动调用；排查问题时可以手工运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/rag.ps1 doctor
powershell -ExecutionPolicy Bypass -File scripts/rag.ps1 status
powershell -ExecutionPolicy Bypass -File scripts/rag.ps1 index
powershell -ExecutionPolicy Bypass -File scripts/rag.ps1 prepare --request .rag-workbench/request.json --subject-image <人物图路径> --background-image <背景图路径> --output .rag-workbench/prepared.json
powershell -ExecutionPolicy Bypass -File scripts/rag.ps1 retrieve --creative-type indoor --query "明亮客厅，侧身拨发，发际线细节" --top-k 3
powershell -ExecutionPolicy Bypass -File scripts/rag.ps1 evaluate
```

本项目的 Python 运行时代码无第三方依赖。向量由本机 Ollama 的 `embeddinggemma` 生成，并保存在 Git 忽略的 `.rag-workbench/index.sqlite3`。
