#!/bin/bash
#
# Kimi Agent 启动脚本 (GitHub Issues 驱动)
#

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 配置环境变量
export GITHUB_TOKEN="${GITHUB_TOKEN:-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}"
export GITHUB_USERNAME="${GITHUB_USERNAME:-zhaohernando-code}"

# 可选配置
export MAX_CONCURRENT_TASKS="${MAX_CONCURRENT_TASKS:-3}"
export KIMI_TIMEOUT="${KIMI_TIMEOUT:-3600}"

# Git 代理配置
export HTTP_PROXY="http://14ad864674363:7559d165cd@168.158.103.246:12323"
export HTTPS_PROXY="$HTTP_PROXY"

# 设置 Git 代理
git config --global http.proxy "$HTTP_PROXY" 2>/dev/null || true
git config --global https.proxy "$HTTPS_PROXY" 2>/dev/null || true

echo "=========================================="
echo "  🤖 Kimi Agent - GitHub Issues 驱动"
echo "=========================================="
echo ""
echo "环境配置:"
echo "  GitHub 用户: $GITHUB_USERNAME"
echo "  最大并发: $MAX_CONCURRENT_TASKS"
echo "  任务超时: ${KIMI_TIMEOUT}秒"
echo ""

# 检查参数
if [ $# -eq 0 ]; then
    echo "监听仓库: claude-dashboard (默认)"
    echo ""
    echo "使用方式:"
    echo "  ./start.sh                    # 使用默认仓库"
    echo "  ./start.sh repo1 repo2        # 监听多个仓库"
    echo ""
    REPOS="claude-dashboard"
else
    echo "监听仓库: $@"
    REPOS="$@"
fi

echo ""
echo "启动 Agent..."
echo "按 Ctrl+C 停止"
echo ""

# 启动 Agent
exec python3 agent.py $REPOS
