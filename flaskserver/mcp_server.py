# -*- coding: utf-8 -*-
"""
flaskserver/mcp_server.py — MCP stdio 代理（独立脚本，随 flask 可选）

把主程序的 REST API 暴露为 MCP 工具，供 AI Agent（DSH / OpenCode 等）
通过 stdio JSON-RPC 调用：

    Agent ──stdio──→ mcp_server.py ──HTTP──→ 主程序 /api

依赖 `mcp` 包（仅本脚本需要，主程序不依赖）：

    pip install mcp
    # 运行（环境变量指向上游地址与密钥）：
    PCD_API_BASE=http://127.0.0.1:8765 PCD_TOKEN=xxx python mcp_server.py
"""

import json
import os

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _e:
    raise SystemExit(
        "缺少依赖：pip install mcp\n（本脚本是独立 MCP 代理，主程序无需安装它）"
    ) from _e

API_BASE = os.environ.get('PCD_API_BASE', 'http://127.0.0.1:8765').rstrip('/')
API_TOKEN = os.environ.get('PCD_TOKEN', '')

mcp = FastMCP('physchem-digitizer')


def _token_headers():
    return {'X-Auth-Token': API_TOKEN} if API_TOKEN else {}


def _request(path, method='GET', body=None):
    """同步 HTTP 请求（标准库，零额外依赖）。"""
    import urllib.request
    import urllib.error
    url = API_BASE + path
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=dict(_token_headers(),
                                              **{'Content-Type': 'application/json'}))
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode('utf-8'))
            return detail
        except Exception:
            return {'ok': False, 'error': 'http_%d' % e.code,
                    'message': 'HTTP %d' % e.code}


@mcp.tool()
def list_modules() -> str:
    """列出所有传感器模块及其状态（是否连接、是否在采集、数据点数）。"""
    d = _request('/api/modules')
    return json.dumps(d, ensure_ascii=False)


@mcp.tool()
def get_snapshot(module: str, points: int = 0) -> str:
    """获取单个模块的最新数据快照（latest / params / actions）。

    Args:
        module: 模块 key（如 force_sensor / ph_sensor）
        points: 附带的降采样序列点数，0 为不附带
    """
    d = _request(f'/api/modules/{module}?points={points}')
    return json.dumps(d, ensure_ascii=False)


@mcp.tool()
def get_series(module: str, limit: int = 2000) -> str:
    """获取模块的降采样时间序列（供自己做拟合/统计分析）。"""
    d = _request(f'/api/modules/{module}/series?limit={limit}')
    return json.dumps(d, ensure_ascii=False)


@mcp.tool()
def control_collect(module: str, action: str) -> str:
    """开始/停止某模块的数据采集。

    Args:
        module: 模块 key
        action: start / stop / toggle
    """
    d = _request(f'/api/modules/{module}/collect', method='POST',
                 body={'action': action})
    return json.dumps(d, ensure_ascii=False)


@mcp.tool()
def send_command(module: str, action: str, params: dict | None = None) -> str:
    """执行模块特有控制动作（去皮 / 校准等）。

    Args:
        module: 模块 key
        action: 动作名（见 get_snapshot 返回的 actions 列表）
        params: 动作参数（可选）
    """
    d = _request(f'/api/modules/{module}/command', method='POST',
                 body={'action': action, 'params': params or {}})
    return json.dumps(d, ensure_ascii=False)


if __name__ == '__main__':
    mcp.run()
