#!/bin/bash
#
# Kimi Agent 守护进程启动脚本
# 支持: 前台运行 / 后台常驻 / 系统服务
#

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 配置环境变量
export GITHUB_TOKEN="${GITHUB_TOKEN:-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}"
export GITHUB_USERNAME="${GITHUB_USERNAME:-zhaohernando-code}"
export MAX_CONCURRENT_TASKS="${MAX_CONCURRENT_TASKS:-3}"
export KIMI_TIMEOUT="${KIMI_TIMEOUT:-3600}"

# 日志配置
LOG_DIR="${HOME}/kimi/logs"
LOG_FILE="${LOG_DIR}/agent.log"
PID_FILE="${LOG_DIR}/agent.pid"

# 创建日志目录
mkdir -p "$LOG_DIR"

# Git 代理配置
export HTTP_PROXY="http://14ad864674363:7559d165cd@168.158.103.246:12323"
export HTTPS_PROXY="$HTTP_PROXY"

# 设置 Git 代理
git config --global http.proxy "$HTTP_PROXY" 2>/dev/null || true
git config --global https.proxy "$HTTPS_PROXY" 2>/dev/null || true

# 默认仓库
DEFAULT_REPOS="claude-dashboard"

# 显示帮助
show_help() {
    echo "Kimi Agent 启动脚本"
    echo ""
    echo "用法:"
    echo "  ./daemon.sh [命令] [选项]"
    echo ""
    echo "命令:"
    echo "  start       前台运行（Ctrl+C 停止）"
    echo "  daemon      后台常驻运行（使用 nohup）"
    echo "  stop        停止后台运行的 Agent"
    echo "  restart     重启 Agent"
    echo "  status      查看运行状态"
    echo "  logs        查看实时日志"
    echo "  install     安装系统服务（开机自启）"
    echo "  uninstall   卸载系统服务"
    echo ""
    echo "示例:"
    echo "  ./daemon.sh start                    # 前台运行"
    echo "  ./daemon.sh start repo1 repo2        # 监听多个仓库"
    echo "  ./daemon.sh daemon                   # 后台常驻"
    echo "  ./daemon.sh logs                     # 查看日志"
    echo ""
}

# 启动 Agent（前台）
cmd_start() {
    local repos="${@:-$DEFAULT_REPOS}"
    
    echo "=========================================="
    echo "  🤖 Kimi Agent - 前台运行"
    echo "=========================================="
    echo ""
    echo "配置:"
    echo "  GitHub 用户: $GITHUB_USERNAME"
    echo "  监听仓库: $repos"
    echo "  日志文件: $LOG_FILE"
    echo ""
    echo "按 Ctrl+C 停止"
    echo ""
    
    # 启动 Agent，输出同时显示在终端和写入日志
    exec python3 agent.py $repos 2>&1 | tee -a "$LOG_FILE"
}

# 后台常驻运行
cmd_daemon() {
    local repos="${@:-$DEFAULT_REPOS}"
    
    # 检查是否已在运行
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "⚠️ Agent 已在运行 (PID: $(cat "$PID_FILE"))"
        echo "   使用 './daemon.sh logs' 查看日志"
        echo "   使用 './daemon.sh stop' 停止"
        return 1
    fi
    
    echo "=========================================="
    echo "  🤖 Kimi Agent - 后台常驻"
    echo "=========================================="
    echo ""
    echo "配置:"
    echo "  GitHub 用户: $GITHUB_USERNAME"
    echo "  监听仓库: $repos"
    echo "  日志文件: $LOG_FILE"
    echo "  PID 文件: $PID_FILE"
    echo ""
    
    # 使用 nohup 后台运行
    nohup python3 agent.py $repos >> "$LOG_FILE" 2>&1 &
    local pid=$!
    
    # 保存 PID
    echo $pid > "$PID_FILE"
    
    echo "✅ Agent 已启动 (PID: $pid)"
    echo ""
    echo "管理命令:"
    echo "  ./daemon.sh logs    - 查看实时日志"
    echo "  ./daemon.sh status  - 查看运行状态"
    echo "  ./daemon.sh stop    - 停止 Agent"
    echo ""
}

# 停止 Agent
cmd_stop() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "正在停止 Agent (PID: $pid)..."
            kill "$pid"
            # 等待进程结束
            for i in {1..10}; do
                if ! kill -0 "$pid" 2>/dev/null; then
                    echo "✅ Agent 已停止"
                    rm -f "$PID_FILE"
                    return 0
                fi
                sleep 1
            done
            # 强制终止
            echo "强制终止..."
            kill -9 "$pid" 2>/dev/null || true
            rm -f "$PID_FILE"
            echo "✅ Agent 已强制停止"
        else
            echo "⚠️ Agent 未运行"
            rm -f "$PID_FILE"
        fi
    else
        echo "⚠️ 找不到 PID 文件，尝试查找进程..."
        local pids=$(pgrep -f "python.*agent.py" || true)
        if [ -n "$pids" ]; then
            echo "找到进程: $pids，正在停止..."
            kill $pids 2>/dev/null || true
            sleep 2
            echo "✅ 已停止"
        else
            echo "⚠️ Agent 未运行"
        fi
    fi
}

# 查看状态
cmd_status() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "✅ Agent 正在运行 (PID: $pid)"
            echo ""
            echo "最近日志:"
            tail -10 "$LOG_FILE" 2>/dev/null || echo "(无日志)"
        else
            echo "⚠️ Agent 未运行 (PID 文件存在但进程不存在)"
            rm -f "$PID_FILE"
        fi
    else
        local pids=$(pgrep -f "python.*agent.py" || true)
        if [ -n "$pids" ]; then
            echo "✅ Agent 正在运行 (PID: $pids)"
            echo "   (注意: 不是通过 daemon.sh 启动的)"
        else
            echo "⚠️ Agent 未运行"
        fi
    fi
}

# 查看日志
cmd_logs() {
    if [ -f "$LOG_FILE" ]; then
        echo "显示实时日志 (按 Ctrl+C 退出)..."
        tail -f "$LOG_FILE"
    else
        echo "⚠️ 日志文件不存在: $LOG_FILE"
    fi
}

# 安装系统服务（开机自启）
cmd_install() {
    local plist_path="${HOME}/Library/LaunchAgents/com.kimi.agent.plist"
    
    echo "安装系统服务..."
    
    # 停止现有服务
    launchctl unload "$plist_path" 2>/dev/null || true
    
    # 复制 plist 文件
    cp com.kimi.agent.plist "$plist_path"
    
    # 加载服务
    launchctl load "$plist_path"
    
    echo "✅ 系统服务已安装"
    echo ""
    echo "管理命令:"
    echo "  launchctl start com.kimi.agent   # 启动"
    echo "  launchctl stop com.kimi.agent    # 停止"
    echo "  launchctl list | grep kimi       # 查看状态"
    echo ""
    echo "日志位置:"
    echo "  ${HOME}/kimi/logs/agent.log"
    echo "  ${HOME}/kimi/logs/agent.error.log"
}

# 卸载系统服务
cmd_uninstall() {
    local plist_path="${HOME}/Library/LaunchAgents/com.kimi.agent.plist"
    
    echo "卸载系统服务..."
    
    if [ -f "$plist_path" ]; then
        launchctl unload "$plist_path" 2>/dev/null || true
        rm -f "$plist_path"
        echo "✅ 系统服务已卸载"
    else
        echo "⚠️ 系统服务未安装"
    fi
}

# 主逻辑
main() {
    case "${1:-start}" in
        start)
            shift
            cmd_start "$@"
            ;;
        daemon)
            shift
            cmd_daemon "$@"
            ;;
        stop)
            cmd_stop
            ;;
        restart)
            shift
            cmd_stop
            sleep 1
            cmd_daemon "$@"
            ;;
        status)
            cmd_status
            ;;
        logs)
            cmd_logs
            ;;
        install)
            cmd_install
            ;;
        uninstall)
            cmd_uninstall
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            echo "未知命令: $1"
            echo "使用 './daemon.sh help' 查看帮助"
            exit 1
            ;;
    esac
}

main "$@"
