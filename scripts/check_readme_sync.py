#!/usr/bin/env python3
"""
检查README文件与代码提交的一致性工具
用于检测代码变更是否需要更新对应的README文件
"""

import os
import sys
import subprocess
import re
from typing import List, Dict, Tuple, Set
from dataclasses import dataclass
from pathlib import Path

@dataclass
class FileChange:
    path: str
    change_type: str  # 'A', 'M', 'D', 'R'
    old_path: str = None


def get_git_root() -> Path:
    """获取git仓库根目录"""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(__file__)
    )
    return Path(result.stdout.strip())


def get_changed_files(commit_range: str = None) -> List[FileChange]:
    """
    获取变更的文件列表
    
    Args:
        commit_range: 提交范围，如 "HEAD~1..HEAD" 或 "commit1..commit2"
                      如果为None，则获取暂存区和工作区的变更
    """
    if commit_range:
        cmd = ["git", "diff", "--name-status", commit_range]
    else:
        cmd = ["git", "status", "--porcelain"]
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=get_git_root()
    )
    
    changes = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
            
        parts = line.split(maxsplit=1)
        if len(parts) < 2:
            continue
            
        status = parts[0].strip()
        path = parts[1].strip()
        
        old_path = None
        if "->" in path:
            old_path, path = path.split("->", 1)
            old_path = old_path.strip()
            path = path.strip()
        
        changes.append(FileChange(
            path=path,
            change_type=status[0],
            old_path=old_path
        ))
    
    return changes


def find_associated_readmes(file_path: str, repo_root: Path) -> List[Path]:
    """
    找到与给定文件相关联的README文件
    
    Args:
        file_path: 文件路径（相对仓库根目录）
        repo_root: 仓库根目录路径
    """
    readmes = []
    file_dir = Path(file_path).parent
    
    # 1. 从文件所在目录开始，向上查找README文件
    current_dir = file_dir
    while True:
        for readme_name in ["README.md", "README"]:
            readme_path = repo_root / current_dir / readme_name
            if readme_path.exists():
                readmes.append(readme_path)
        
        if current_dir == Path("."):
            break
        current_dir = current_dir.parent
    
    # 2. 根目录的README
    root_readme = repo_root / "README.md"
    if root_readme.exists() and root_readme not in readmes:
        readmes.append(root_readme)
    
    return readmes


def extract_keywords_from_file(file_path: Path) -> Set[str]:
    """从文件中提取关键词（用于检测README中是否提到这些内容）"""
    keywords = set()
    
    if not file_path.exists():
        return keywords
    
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        
        # 提取文件名（不含扩展名）
        filename = file_path.stem
        keywords.add(filename.lower())
        
        # 对于代码文件，提取函数名、类名、宏定义等
        if file_path.suffix in [".py", ".cpp", ".c", ".h", ".ino"]:
            # 提取函数定义
            func_matches = re.findall(r'(?:def\s+|void\s+|int\s+|float\s+|bool\s+)(\w+)', content)
            keywords.update([m.lower() for m in func_matches])
            
            # 提取类定义
            class_matches = re.findall(r'class\s+(\w+)', content)
            keywords.update([m.lower() for m in class_matches])
            
            # 提取宏定义
            define_matches = re.findall(r'#define\s+(\w+)', content)
            keywords.update([m.lower() for m in define_matches])
            
            # 提取模块/文件名关键词
            keywords.add(file_path.suffix[1:])  # 扩展名
        
        # 对于Arduino文件，提取引脚定义等
        if file_path.suffix == ".ino":
            pin_matches = re.findall(r'(?:#define\s+)?(?:TRIG_PIN|ECHO_PIN|ADC_PIN)\s*[=]?\s*(\d+)', content)
            keywords.update([f"gpio{p}" for p in pin_matches])
            keywords.update([f"pin{p}" for p in pin_matches])
    
    except Exception as e:
        print(f"警告：无法读取文件 {file_path}: {e}", file=sys.stderr)
    
    return keywords


def check_readme_mentions_file(readme_path: Path, file_path: Path) -> Tuple[bool, List[str]]:
    """检查README是否提到了该文件的相关内容"""
    if not readme_path.exists():
        return False, []
    
    try:
        readme_content = readme_path.read_text(encoding="utf-8", errors="ignore").lower()
        keywords = extract_keywords_from_file(file_path)
        
        # 也直接检查文件名
        filename = file_path.name.lower()
        filename_no_ext = file_path.stem.lower()
        
        mentions = []
        
        if filename in readme_content:
            mentions.append(f"文件名 '{filename}'")
        if filename_no_ext in readme_content and filename_no_ext != filename:
            mentions.append(f"文件名 '{filename_no_ext}'")
        
        for keyword in keywords:
            if len(keyword) < 3:
                continue
            if keyword in readme_content:
                mentions.append(f"关键词 '{keyword}'")
        
        return len(mentions) > 0, mentions
    
    except Exception as e:
        print(f"警告：无法读取README {readme_path}: {e}", file=sys.stderr)
        return False, []


def analyze_changes(commit_range: str = None) -> Dict:
    """
    分析变更并找出需要更新README的文件
    
    Returns:
        包含分析结果的字典
    """
    repo_root = get_git_root()
    changes = get_changed_files(commit_range)
    
    # 过滤掉README文件本身
    code_changes = [c for c in changes if not c.path.lower().endswith(('readme.md', 'readme'))]
    
    readme_needs_update = []
    
    for change in code_changes:
        file_path = repo_root / change.path
        
        # 找到关联的README
        associated_readmes = find_associated_readmes(change.path, repo_root)
        
        # 检查README是否提到了这个文件
        file_mentioned = False
        mentioned_in = []
        
        for readme in associated_readmes:
            mentioned, mentions = check_readme_mentions_file(readme, file_path)
            if mentioned:
                file_mentioned = True
                mentioned_in.append(str(readme.relative_to(repo_root)))
        
        # 如果文件被README提到，或者是重要文件，可能需要更新README
        if file_mentioned or is_important_file(change.path):
            readme_needs_update.append({
                "file": change.path,
                "change_type": change.change_type,
                "mentioned_in": mentioned_in,
                "associated_readmes": [str(r.relative_to(repo_root)) for r in associated_readmes]
            })
    
    return {
        "total_changes": len(changes),
        "code_changes": len(code_changes),
        "readme_needs_update": readme_needs_update
    }


def is_important_file(file_path: str) -> bool:
    """判断文件是否为重要文件，可能需要README更新"""
    important_patterns = [
        r'\.ino$',  # Arduino代码
        r'\.py$',   # Python代码（特别是main.py等）
        r'main\.',  # 主程序文件
    ]
    
    for pattern in important_patterns:
        if re.search(pattern, file_path, re.IGNORECASE):
            return True
    
    return False


def print_report(analysis: Dict):
    """打印分析报告"""
    print("=" * 80)
    print("README一致性检查报告")
    print("=" * 80)
    print(f"\n总变更文件数: {analysis['total_changes']}")
    print(f"代码文件变更数: {analysis['code_changes']}")
    print(f"可能需要更新README的文件数: {len(analysis['readme_needs_update'])}")
    
    if analysis['readme_needs_update']:
        print("\n" + "=" * 80)
        print("需要检查的文件:")
        print("=" * 80)
        
        for item in analysis['readme_needs_update']:
            print(f"\n📄 文件: {item['file']}")
            print(f"   变更类型: {item['change_type']}")
            
            if item['mentioned_in']:
                print(f"   ✓ 在以下README中被提及:")
                for readme in item['mentioned_in']:
                    print(f"     - {readme}")
            else:
                print(f"   ⚠️  未在README中找到提及")
            
            if item['associated_readmes']:
                print(f"   关联的README文件:")
                for readme in item['associated_readmes']:
                    print(f"     - {readme}")
    
    print("\n" + "=" * 80)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="检查README文件与代码提交的一致性"
    )
    parser.add_argument(
        "commit_range",
        nargs="?",
        help="提交范围，如 HEAD~1..HEAD 或 commit1..commit2（默认为检查工作区变更）"
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="如果发现需要更新README的文件，返回非零退出码"
    )
    
    args = parser.parse_args()
    
    analysis = analyze_changes(args.commit_range)
    print_report(analysis)
    
    if args.fail_on_warning and analysis['readme_needs_update']:
        print("\n❌ 发现需要检查README一致性的文件！")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
