"""
Flask HTTP API 服务
提供 RESTful API 和 SSE 日志流
"""
import json
import time
from datetime import datetime

from flask import Flask, request, jsonify, Response, stream_with_context
from werkzeug.exceptions import BadRequest

from config import config
from auth import require_auth, create_signed_headers
from database import db
from models import (
    init_database, TaskStatus, TaskType, LogType,
    Project, Task, TaskLog
)
from task_manager import task_manager, TaskManagerError
from git_manager import git_manager, GitManagerError

app = Flask(__name__)


# ========== 错误处理 ==========

@app.errorhandler(BadRequest)
def handle_bad_request(e):
    return jsonify({"error": "Bad request", "message": str(e)}), 400


@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled exception: {e}", exc_info=True)
    return jsonify({"error": "Internal server error", "message": str(e)}), 500


# ========== 健康检查 ==========

@app.route('/health', methods=['GET'])
def health():
    """健康检查端点"""
    stats = task_manager.get_stats()
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "stats": {
            "pending": stats.pending,
            "running": stats.running,
            "completed": stats.completed,
            "failed": stats.failed,
            "cancelled": stats.cancelled,
            "total": stats.total
        }
    })


# ========== 项目 API ==========

@app.route('/api/v1/projects', methods=['POST'])
@require_auth
def create_project():
    """创建项目"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400
    
    name = data.get('name')
    repo_url = data.get('repo_url')
    
    if not name or not repo_url:
        return jsonify({"error": "Missing required fields: name, repo_url"}), 400
    
    try:
        # 计算本地路径
        local_path = git_manager._get_repo_path(name)
        
        # 创建项目记录
        project = db.create_project(name=name, repo_url=repo_url, local_path=local_path)
        
        return jsonify({
            "success": True,
            "data": project.to_dict()
        }), 201
    
    except Exception as e:
        return jsonify({"error": f"Failed to create project: {str(e)}"}), 500


@app.route('/api/v1/projects', methods=['GET'])
@require_auth
def list_projects():
    """列出所有项目"""
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    projects = db.list_projects(limit=limit, offset=offset)
    
    return jsonify({
        "success": True,
        "data": [p.to_dict() for p in projects],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "count": len(projects)
        }
    })


@app.route('/api/v1/projects/<project_id>', methods=['GET'])
@require_auth
def get_project(project_id: str):
    """获取项目详情"""
    project = db.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    # 获取项目统计
    tasks = db.list_tasks(project_id=project_id, limit=10000)
    status_count = {}
    for task in tasks:
        status_count[task.status.value] = status_count.get(task.status.value, 0) + 1
    
    result = project.to_dict()
    result['task_stats'] = status_count
    
    return jsonify({
        "success": True,
        "data": result
    })


@app.route('/api/v1/projects/<project_id>', methods=['DELETE'])
@require_auth
def delete_project(project_id: str):
    """删除项目"""
    project = db.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    # 检查是否有运行中的任务
    running_tasks = db.list_tasks(project_id=project_id, status=TaskStatus.RUNNING)
    if running_tasks:
        return jsonify({"error": "Cannot delete project with running tasks"}), 409
    
    success = db.delete_project(project_id)
    
    return jsonify({
        "success": success,
        "message": "Project deleted" if success else "Failed to delete project"
    })


# ========== 任务 API ==========

@app.route('/api/v1/projects/<project_id>/tasks', methods=['POST'])
@require_auth
def create_task(project_id: str):
    """创建任务"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400
    
    # 验证项目存在
    project = db.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    title = data.get('title')
    if not title:
        return jsonify({"error": "Missing required field: title"}), 400
    
    # 解析任务类型
    task_type_str = data.get('type', 'feature')
    try:
        task_type = TaskType(task_type_str.lower())
    except ValueError:
        return jsonify({"error": f"Invalid task type: {task_type_str}"}), 400
    
    description = data.get('description')
    parent_task_id = data.get('parent_task_id')
    
    try:
        task = task_manager.submit_task(
            project_id=project_id,
            title=title,
            task_type=task_type,
            description=description,
            parent_task_id=parent_task_id
        )
        
        return jsonify({
            "success": True,
            "data": task.to_dict()
        }), 201
    
    except TaskManagerError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to create task: {str(e)}"}), 500


@app.route('/api/v1/projects/<project_id>/tasks', methods=['GET'])
@require_auth
def list_project_tasks(project_id: str):
    """列出项目下的任务"""
    # 验证项目存在
    project = db.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    status = request.args.get('status')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    # 解析状态过滤
    status_filter = None
    if status:
        try:
            status_filter = TaskStatus(status.lower())
        except ValueError:
            return jsonify({"error": f"Invalid status: {status}"}), 400
    
    tasks = db.list_tasks(project_id=project_id, status=status_filter, limit=limit, offset=offset)
    
    return jsonify({
        "success": True,
        "data": [t.to_dict() for t in tasks],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "count": len(tasks)
        }
    })


@app.route('/api/v1/tasks/<task_id>', methods=['GET'])
@require_auth
def get_task(task_id: str):
    """获取任务详情"""
    task = db.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    result = task.to_dict()
    
    # 获取项目信息
    project = db.get_project(task.project_id)
    if project:
        result['project_name'] = project.name
    
    return jsonify({
        "success": True,
        "data": result
    })


@app.route('/api/v1/tasks/<task_id>/cancel', methods=['POST'])
@require_auth
def cancel_task(task_id: str):
    """取消任务"""
    task = db.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    if task.status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
        return jsonify({"error": f"Cannot cancel task with status: {task.status.value}"}), 409
    
    success = task_manager.cancel_task(task_id)
    
    return jsonify({
        "success": success,
        "message": "Task cancelled" if success else "Failed to cancel task"
    })


@app.route('/api/v1/tasks/<task_id>/logs', methods=['GET'])
@require_auth
def get_task_logs(task_id: str):
    """获取任务日志"""
    task = db.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    # 检查是否是流式请求
    stream = request.args.get('stream', 'false').lower() == 'true'
    
    if stream:
        # SSE 流式响应
        def generate():
            last_id = 0
            while True:
                logs = db.get_task_logs(task_id, limit=100)
                new_logs = [log for log in logs if log.id > last_id]
                
                for log in new_logs:
                    data = json.dumps(log.to_dict())
                    yield f"data: {data}\n\n"
                    last_id = log.id
                
                # 检查任务是否结束
                current_task = db.get_task(task_id)
                if current_task and current_task.status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                    # 发送结束标记
                    yield f"data: {json.dumps({'type': 'EOF'})}\n\n"
                    break
                
                time.sleep(0.5)
        
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )
    
    else:
        # 普通响应
        limit = request.args.get('limit', 1000, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        logs = db.get_task_logs(task_id, limit=limit, offset=offset)
        
        return jsonify({
            "success": True,
            "data": [log.to_dict() for log in logs],
            "pagination": {
                "limit": limit,
                "offset": offset,
                "count": len(logs)
            }
        })


@app.route('/api/v1/tasks/<task_id>/tree', methods=['GET'])
@require_auth
def get_task_tree(task_id: str):
    """获取任务树"""
    task = db.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    # 获取项目
    project = db.get_project(task.project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    try:
        tree = git_manager.get_task_tree(project.name)
        return jsonify({
            "success": True,
            "data": tree
        })
    except GitManagerError as e:
        return jsonify({"error": str(e)}), 500


# ========== 统计 API ==========

@app.route('/api/v1/stats', methods=['GET'])
@require_auth
def get_stats():
    """获取系统统计"""
    stats = task_manager.get_stats()
    running_tasks = task_manager.get_running_tasks()
    
    return jsonify({
        "success": True,
        "data": {
            "tasks": {
                "pending": stats.pending,
                "running": stats.running,
                "completed": stats.completed,
                "failed": stats.failed,
                "cancelled": stats.cancelled,
                "total": stats.total
            },
            "running_task_ids": running_tasks,
            "max_concurrent": task_manager.max_concurrent
        }
    })


# ========== CORS 支持 ==========

@app.after_request
def after_request(response):
    """添加 CORS 头"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,X-Timestamp,X-Signature')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


# ========== 启动函数 ==========

def init_app():
    """初始化应用"""
    # 初始化数据库
    init_database()
    print(f"Database initialized at: {config.DATABASE_PATH}")
    
    return app


if __name__ == '__main__':
    app = init_app()
    
    print(f"Starting Kimi Agent Server on {config.HOST}:{config.PORT}")
    print(f"Debug mode: {config.DEBUG}")
    
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        threaded=True
    )
