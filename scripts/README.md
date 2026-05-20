# README同步工具集

本目录包含用于检查和维护README文档与代码同步的自动化工具。

## 工具列表

### 1. `check_readme_sync.py` - README同步检查器

用于分析git提交历史，检测代码变更是否需要同步更新对应的README文档。

**功能特点：**
- 自动识别与代码文件关联的README文件（向上目录搜索）
- 提取代码文件中的关键词（函数名、宏定义、引脚配置等）
- 检查README是否提到这些关键词
- 识别重要文件类型（Arduino代码、Python主程序等）
- 生成详细的检查报告

**使用方法：**
```bash
# 检查最近一次提交
python check_readme_sync.py HEAD~1..HEAD

# 检查当前工作区变更
python check_readme_sync.py

# 检查指定提交范围
python check_readme_sync.py commit_hash1..commit_hash2

# 如果发现问题则返回非零退出码（用于CI/CD）
python check_readme_sync.py --fail-on-warning
```

**输出示例：**
```
================================================================================
README一致性检查报告
================================================================================

总变更文件数: 5
代码文件变更数: 3
可能需要更新README的文件数: 2

================================================================================
需要检查的文件:
================================================================================

📄 文件: 传感器arduino代码/ph传感器/ph esp32.ino
   变更类型: M
   ✓ 在以下README中被提及:
     - 传感器arduino代码/ph传感器/README.md
   关联的README文件:
     - 传感器arduino代码/ph传感器/README.md
     - 传感器arduino代码/README.md
     - README.md
```

### 2. `create_readme_update_pr.py` - 自动创建PR工具

帮助快速创建README更新的PR，自动处理分支创建、提交、推送和PR创建。

**功能特点：**
- 自动生成有意义的分支名（包含时间戳）
- 支持自定义提交信息和PR标题
- 自动推送分支到远程仓库
- 使用GitHub CLI自动创建PR
- 支持干运行模式（预览操作）

**使用方法：**
```bash
# 基本用法（先修改README文件，然后运行）
python create_readme_update_pr.py

# 自定义参数
python create_readme_update_pr.py \
    --branch "update-readme-2024" \
    --title "docs: 更新README文档" \
    --message "更新主README和传感器文档" \
    --base "main" \
    --files README.md "传感器arduino代码/README.md"

# 干运行（只显示将要执行的操作）
python create_readme_update_pr.py --dry-run
```

**前置要求：**
- 安装GitHub CLI (`gh`) 并登录
- 配置git remote为GitHub仓库
- 工作区干净或已stage要提交的文件

## GitHub Actions工作流

项目配置了自动检查工作流，位于 `.github/workflows/check-readme-sync.yml`

**触发条件：**
- Push到main/master分支
- PR到main/master分支
- 手动触发（workflow_dispatch）

**功能：**
- 自动运行README同步检查
- 上传检查报告为artifact
- 在PR中评论提醒（如果发现问题）

## 工作流程建议

1. **开发阶段**
   ```bash
   # 编写代码...
   git add .
   git commit -m "feat: 添加新功能"
   
   # 检查是否需要更新README
   python scripts/check_readme_sync.py HEAD~1..HEAD
   ```

2. **如果需要更新README**
   ```bash
   # 编辑相关README文件
   vim README.md
   
   # 创建PR
   python scripts/create_readme_update_pr.py
   ```

3. **CI自动检查**
   - 推送后GitHub Actions会自动运行检查
   - 打开PR后会收到检查结果评论

## 注意事项

- 工具会搜索所有相关的README文件（当前目录、父目录、根目录）
- Arduino文件(.ino)和Python主程序会被特别关注
- 检查是启发式的，可能会有误报或漏报，最终需要人工判断
- 创建PR前确保已配置好GitHub CLI或准备好手动创建

## 扩展阅读

- 主README文档：[../README.md](../README.md)
- GitHub Actions文档：https://docs.github.com/en/actions
- GitHub CLI文档：https://cli.github.com/
