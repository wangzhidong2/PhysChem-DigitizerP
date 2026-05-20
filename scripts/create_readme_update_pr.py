#!/usr/bin/env python3
"""
自动创建README更新PR的工具
用于在发现README需要更新时，自动创建分支并提交PR
"""

import os
import sys
import subprocess
import argparse
from datetime import datetime
from pathlib import Path


def get_git_root() -> Path:
    """获取git仓库根目录"""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(__file__)
    )
    return Path(result.stdout.strip())


def check_git_clean() -> bool:
    """检查git工作区是否干净"""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=get_git_root()
    )
    return len(result.stdout.strip()) == 0


def create_branch(branch_name: str) -> bool:
    """创建新分支"""
    try:
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            check=True,
            cwd=get_git_root()
        )
        return True
    except subprocess.CalledProcessError:
        return False


def get_current_branch() -> str:
    """获取当前分支名"""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        cwd=get_git_root()
    )
    return result.stdout.strip()


def commit_changes(message: str, files: list = None) -> bool:
    """提交更改"""
    try:
        if files:
            for file in files:
                subprocess.run(
                    ["git", "add", file],
                    check=True,
                    cwd=get_git_root()
                )
        else:
            subprocess.run(
                ["git", "add", "-u"],
                check=True,
                cwd=get_git_root()
            )
        
        subprocess.run(
            ["git", "commit", "-m", message],
            check=True,
            cwd=get_git_root()
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"提交失败: {e}", file=sys.stderr)
        return False


def push_branch(branch_name: str, remote: str = "origin") -> bool:
    """推送分支到远程"""
    try:
        subprocess.run(
            ["git", "push", "-u", remote, branch_name],
            check=True,
            cwd=get_git_root()
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"推送失败: {e}", file=sys.stderr)
        return False


def get_repo_info() -> tuple:
    """获取仓库信息"""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        cwd=get_git_root()
    )
    url = result.stdout.strip()
    
    # 解析owner和repo名
    if url.endswith(".git"):
        url = url[:-4]
    
    if "github.com" in url:
        parts = url.split("/")
        owner = parts[-2]
        repo = parts[-1]
        return owner, repo
    
    return None, None


def create_github_pr(title: str, body: str, base_branch: str = "main") -> bool:
    """使用GitHub CLI创建PR"""
    try:
        # 检查gh是否可用
        subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            check=True
        )
        
        cmd = [
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--base", base_branch
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=get_git_root()
        )
        
        print(f"PR创建成功: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"使用gh创建PR失败: {e}", file=sys.stderr)
        print(f"错误输出: {e.stderr}", file=sys.stderr)
        return False
    except FileNotFoundError:
        print("GitHub CLI (gh) 未安装，请手动创建PR", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="自动创建README更新PR"
    )
    parser.add_argument(
        "--branch",
        help="分支名称（默认自动生成）"
    )
    parser.add_argument(
        "--title",
        help="PR标题（默认自动生成）"
    )
    parser.add_argument(
        "--base",
        default="main",
        help="目标分支（默认main）"
    )
    parser.add_argument(
        "--files",
        nargs="+",
        help="要提交的文件（默认所有已修改的README文件）"
    )
    parser.add_argument(
        "--message",
        help="提交信息（默认自动生成）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅显示将要执行的操作，不实际执行"
    )
    
    args = parser.parse_args()
    
    repo_root = get_git_root()
    print(f"仓库根目录: {repo_root}")
    
    # 检查工作区状态
    if not check_git_clean():
        print("⚠️  工作区有未提交的更改，请先提交或 stash", file=sys.stderr)
        if not args.dry_run:
            return 1
    
    # 生成分支名
    if not args.branch:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        args.branch = f"update-readme-{timestamp}"
    
    # 生成标题
    if not args.title:
        args.title = "docs: 更新README文件以同步代码变更"
    
    # 生成提交信息
    if not args.message:
        args.message = args.title
    
    print("\n📋 将要执行的操作:")
    print(f"   1. 创建分支: {args.branch}")
    print(f"   2. 提交文件: {args.files or '所有已修改的README文件'}")
    print(f"   3. 提交信息: {args.message}")
    print(f"   4. 推送分支并创建PR到: {args.base}")
    
    if args.dry_run:
        print("\n✅ 干运行模式，不执行实际操作")
        return 0
    
    # 确认
    response = input("\n继续执行？(y/N): ")
    if response.lower() != "y":
        print("操作取消")
        return 0
    
    # 执行操作
    print("\n🚀 开始执行...")
    
    # 1. 创建分支
    print(f"创建分支 {args.branch}...")
    if not create_branch(args.branch):
        print("创建分支失败", file=sys.stderr)
        return 1
    
    # 2. 提交更改
    print("提交更改...")
    if not commit_changes(args.message, args.files):
        print("提交失败", file=sys.stderr)
        return 1
    
    # 3. 推送分支
    print(f"推送分支 {args.branch}...")
    if not push_branch(args.branch):
        print("推送失败，但本地更改已提交", file=sys.stderr)
        print("请手动推送并创建PR")
        return 1
    
    # 4. 创建PR
    print("创建PR...")
    pr_body = f"""\
## README更新

此PR用于同步代码变更与README文档。

**变更内容:**
- 更新相关README文件以反映最新代码变更

---
*此PR由自动化工具生成*
"""
    
    if create_github_pr(args.title, pr_body, args.base):
        print("\n✅ PR创建成功！")
    else:
        print("\n⚠️  PR创建失败，但分支已推送。请手动创建PR。")
        owner, repo = get_repo_info()
        if owner and repo:
            print(f"   访问: https://github.com/{owner}/{repo}/pull/new/{args.branch}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
