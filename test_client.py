"""
测试客户端 - 用于验证 API
"""
import json
import time
import requests
from auth import create_signed_headers


class KimiAgentClient:
    """Kimi Agent API 客户端"""
    
    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url.rstrip('/')
    
    def _make_request(self, method: str, path: str, data: dict = None) -> dict:
        """发送带签名的请求"""
        url = f"{self.base_url}{path}"
        body = json.dumps(data) if data else ""
        
        headers = create_signed_headers(method, path, body)
        
        if method == 'GET':
            response = requests.get(url, headers=headers)
        elif method == 'POST':
            response = requests.post(url, headers=headers, data=body)
        elif method == 'DELETE':
            response = requests.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        if response.status_code >= 400:
            print(f"Error {response.status_code}: {response.text}")
        
        return response.json()
    
    # 健康检查
    def health(self) -> dict:
        """健康检查"""
        url = f"{self.base_url}/health"
        response = requests.get(url)
        return response.json()
    
    # 项目 API
    def create_project(self, name: str, repo_url: str) -> dict:
        """创建项目"""
        return self._make_request('POST', '/api/v1/projects', {
            'name': name,
            'repo_url': repo_url
        })
    
    def list_projects(self) -> dict:
        """列出项目"""
        return self._make_request('GET', '/api/v1/projects')
    
    def get_project(self, project_id: str) -> dict:
        """获取项目详情"""
        return self._make_request('GET', f'/api/v1/projects/{project_id}')
    
    def delete_project(self, project_id: str) -> dict:
        """删除项目"""
        return self._make_request('DELETE', f'/api/v1/projects/{project_id}')
    
    # 任务 API
    def create_task(self, project_id: str, title: str, task_type: str = 'feature', 
                    description: str = None, parent_task_id: str = None) -> dict:
        """创建任务"""
        data = {
            'title': title,
            'type': task_type
        }
        if description:
            data['description'] = description
        if parent_task_id:
            data['parent_task_id'] = parent_task_id
        
        return self._make_request('POST', f'/api/v1/projects/{project_id}/tasks', data)
    
    def list_tasks(self, project_id: str, status: str = None) -> dict:
        """列出任务"""
        path = f'/api/v1/projects/{project_id}/tasks'
        if status:
            path += f'?status={status}'
        return self._make_request('GET', path)
    
    def get_task(self, task_id: str) -> dict:
        """获取任务详情"""
        return self._make_request('GET', f'/api/v1/tasks/{task_id}')
    
    def cancel_task(self, task_id: str) -> dict:
        """取消任务"""
        return self._make_request('POST', f'/api/v1/tasks/{task_id}/cancel')
    
    def get_logs(self, task_id: str) -> dict:
        """获取任务日志"""
        return self._make_request('GET', f'/api/v1/tasks/{task_id}/logs')
    
    def stream_logs(self, task_id: str):
        """流式获取日志 (SSE)"""
        url = f"{self.base_url}/api/v1/tasks/{task_id}/logs?stream=true"
        headers = create_signed_headers('GET', f'/api/v1/tasks/{task_id}/logs?stream=true')
        
        response = requests.get(url, headers=headers, stream=True)
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = json.loads(line[6:])
                    if data.get('type') == 'EOF':
                        break
                    yield data
    
    # 统计
    def get_stats(self) -> dict:
        """获取统计"""
        return self._make_request('GET', '/api/v1/stats')


def run_tests():
    """运行测试"""
    client = KimiAgentClient()
    
    print("=" * 50)
    print("Kimi Agent API 测试")
    print("=" * 50)
    
    # 1. 健康检查
    print("\n1. 健康检查")
    result = client.health()
    print(f"   Status: {result.get('status')}")
    print(f"   Stats: {result.get('stats')}")
    
    # 2. 创建项目
    print("\n2. 创建测试项目")
    result = client.create_project(
        name="test-project",
        repo_url="https://github.com/zhaohernando-code/claude-dashboard.git"
    )
    print(f"   Result: {json.dumps(result, indent=2, ensure_ascii=False)}")
    
    if not result.get('success'):
        print("   创建项目失败，停止测试")
        return
    
    project_id = result['data']['id']
    
    # 3. 列出项目
    print("\n3. 列出所有项目")
    result = client.list_projects()
    print(f"   Count: {result.get('pagination', {}).get('count')}")
    
    # 4. 获取项目详情
    print("\n4. 获取项目详情")
    result = client.get_project(project_id)
    print(f"   Project: {result.get('data', {}).get('name')}")
    
    # 5. 创建任务
    print("\n5. 创建测试任务")
    result = client.create_task(
        project_id=project_id,
        title="Test Task - Add README",
        task_type="docs",
        description="Add a simple README.md file to the project"
    )
    print(f"   Result: {json.dumps(result, indent=2, ensure_ascii=False)}")
    
    if not result.get('success'):
        print("   创建任务失败")
    else:
        task_id = result['data']['id']
        
        # 6. 获取任务详情
        print("\n6. 获取任务详情")
        time.sleep(1)
        result = client.get_task(task_id)
        print(f"   Status: {result.get('data', {}).get('status')}")
    
    # 7. 获取统计
    print("\n7. 获取系统统计")
    result = client.get_stats()
    print(f"   Stats: {json.dumps(result.get('data', {}).get('tasks'), indent=2)}")
    
    print("\n" + "=" * 50)
    print("测试完成")
    print("=" * 50)


if __name__ == "__main__":
    run_tests()
