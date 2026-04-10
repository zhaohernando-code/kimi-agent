#!/bin/bash
#
# Kimi Agent 启动脚本 - 生产环境
# 支持后台常驻和日志记录
#

# 强制设置环境变量
export GITHUB_TOKEN="${GITHUB_TOKEN:-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}"
export GITHUB_USERNAME="zhaohernando-code"
export MAX_CONCURRENT_TASKS="3"
export KIMI_TIMEOUT="3600"

# 代理
export HTTP_PROXY="http://14ad864674363:7559d165cd@168.158.103.246:12323"
export HTTPS_PROXY="$HTTP_PROXY"

# Git 代理
git config --global http.proxy "$HTTP_PROXY" 2>/dev/null || true
git config --global https.proxy "$HTTPS_PROXY" 2>/dev/null || true

# 目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${HOME}/kimi/logs"
mkdir -p "$LOG_DIR"

cd "$SCRIPT_DIR"

# 命令
CMD="${1:-start}"

start_agent() {
    echo "=========================================="
    echo "  🤖 Kimi Agent 启动"
    echo "=========================================="
    echo ""
    echo "配置:"
    echo "  用户: $GITHUB_USERNAME"
    echo "  仓库: ${2:-claude-dashboard}"
    echo "  日志: $LOG_DIR/agent.log"
    echo ""
    
    # 清理旧进程
    pkill -f "python.*agent.py" 2>/dev/null || true
    sleep 1
    
    # 启动（无缓冲模式）
    nohup python3 -u agent.py "${2:-claude-dashboard}" >> "$LOG_DIR/agent.log" 2>&1 &
    PID=$!
    
    # 保存 PID
    echo $PID > "$LOG_DIR/agent.pid"
    
    echo "✅ Agent 已启动 (PID: $PID)"
    echo ""
    echo "管理命令:"
    echo "  tail -f $LOG_DIR/agent.log  # 查看日志"
    echo "  kill \$(cat $LOG_DIR/agent.pid)     # 停止"
    echo ""
    
    # 等待几秒显示启动日志
    sleep 3
    tail -15 "$LOG_DIR/agent.log"
}

stop_agent() {
    if [ -f "$LOG_DIR/agent.pid" ]; then
        PID=$(cat "$LOG_DIR/agent.pid")
        if kill -0 "$PID" 2>/dev/null; then
            echo "停止 Agent (PID: $PID)..."
            kill "$PID"
            for i in {1..5}; do
                if ! kill -0 "$PID" 2>/dev/null; then
                    echo "✅ 已停止"
                    rm -f "$LOG_DIR/agent.pid"
                    return 0
                fi
                sleep 1
            done
            kill -9 "$PID" 2>/dev/null
            rm -f "$LOG_DIR/agent.pid"
            echo "✅ 已强制停止"
        else
            echo "Agent 未运行"
            rm -f "$LOG_DIR/agent.pid"
        fi
    else
        pkill -f "python.*agent.py" 2>/dev/null
        echo "✅ 已清理"
    fi
}

status_agent() {
    if [ -f "$LOG_DIR/agent.pid" ]; then
        PID=$(cat "$LOG_DIR/agent.pid")
        if kill -0 "$PID" 2>/dev/null; then
            echo "✅ Agent 运行中 (PID: $PID)"
            echo ""
            tail -10 "$LOG_DIR/agent.log"
        else
            echo "⚠️ Agent 未运行"
        fi
    else
        echo "⚠️ Agent 未运行 (无 PID 文件)"
    fi
}

case "$CMD" in
    start)
        start_agent "$@"
        ;;
    stop)
        stop_agent
        ;;
    restart)
        stop_agent
        sleep 2
        start_agent "$@"
        ;;
    status)
        status_agent
        ;;
    logs)
        tail -f "$LOG_DIR/agent.log"
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs} [仓库名]"
        exit 1
        ;;
esac
