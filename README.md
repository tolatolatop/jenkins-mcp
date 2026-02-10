# Jenkins MCP Server

一个基于 [FastMCP](https://gofastmcp.com/) 构建的 MCP 服务，用于通过 MCP 协议管理 Jenkins 任务。

## 功能

| 工具 | 说明 |
|------|------|
| `trigger_job` | 触发 Jenkins 任务构建，支持传入参数，自动等待获取构建号 |
| `get_job_parameters` | 获取任务的参数定义列表（名称、类型、默认值、描述） |
| `get_job_status` | 查看任务构建状态（支持指定构建号或查看最新构建） |
| `get_build_log` | 分页获取构建控制台日志（支持从头部或末尾读取） |
| `cancel_build` | 取消正在运行的构建 |
| `list_triggered_jobs` | 查看通过本 MCP 触发的所有任务记录，自动同步最新状态 |
| `list_build_artifacts` | 列出构建产出的归档文件 |
| `fetch_build_artifact` | 下载指定归档文件内容（文本直接返回，二进制 base64 编码） |

## 安装

```bash
git clone https://github.com/tolatolatop/jenkins-mcp.git
cd jenkins-mcp
uv sync
```

## 环境变量配置

| 变量 | 说明 | 必填 |
|------|------|------|
| `JENKINS_URL` | Jenkins 服务地址，例如 `http://jenkins.example.com:8080` | 是 |
| `JENKINS_USERNAME` | Jenkins 用户名 | 否 |
| `JENKINS_API_TOKEN` | Jenkins API Token | 否 |
| `JENKINS_MCP_STORE_PATH` | 触发记录持久化文件路径（默认 `~/.jenkins_mcp/triggered_jobs.json`） | 否 |

## MCP 客户端配置

### Cursor

在 Cursor Settings > MCP 中点击 "Add new MCP server"，或编辑 `~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "jenkins": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/tolatolatop/jenkins-mcp.git", "jenkins-mcp"],
      "env": {
        "JENKINS_URL": "http://jenkins.example.com:8080",
        "JENKINS_USERNAME": "your-username",
        "JENKINS_API_TOKEN": "your-api-token"
      }
    }
  }
}
```

如果是本地克隆的仓库，也可以用本地路径：

```json
{
  "mcpServers": {
    "jenkins": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/jenkins-mcp", "python", "-m", "jenkins_mcp.server"],
      "env": {
        "JENKINS_URL": "http://jenkins.example.com:8080",
        "JENKINS_USERNAME": "your-username",
        "JENKINS_API_TOKEN": "your-api-token"
      }
    }
  }
}
```

### Claude Desktop

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）或 `%APPDATA%\Claude\claude_desktop_config.json`（Windows）：

```json
{
  "mcpServers": {
    "jenkins": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/tolatolatop/jenkins-mcp.git", "jenkins-mcp"],
      "env": {
        "JENKINS_URL": "http://jenkins.example.com:8080",
        "JENKINS_USERNAME": "your-username",
        "JENKINS_API_TOKEN": "your-api-token"
      }
    }
  }
}
```

## 手动运行

```bash
# 设置环境变量
export JENKINS_URL="http://jenkins.example.com:8080"
export JENKINS_USERNAME="your-username"
export JENKINS_API_TOKEN="your-api-token"

# 运行 MCP 服务（stdio 模式）
uv run python -m jenkins_mcp.server

# 或使用 fastmcp CLI
uv run fastmcp run src/jenkins_mcp/server.py
```

## 工具使用示例

### 触发任务

```
trigger_job(job_name="my-project/main", parameters={"BRANCH": "develop", "DEPLOY": "true"})
```

### 获取任务参数

```
get_job_parameters(job_name="my-project/main")
```

### 查看构建状态

```
# 查看最新构建
get_job_status(job_name="my-project/main")

# 查看指定构建
get_job_status(job_name="my-project/main", build_number=42)
```

### 获取构建日志

```
# 从头部获取前 100 行
get_build_log(job_name="my-project/main", build_number=42)

# 获取最后 50 行
get_build_log(job_name="my-project/main", build_number=42, max_lines=50, from_end=True)

# 从末尾跳过 50 行后再取 100 行（向上翻页）
get_build_log(job_name="my-project/main", build_number=42, start_line=50, max_lines=100, from_end=True)
```

### 取消构建

```
cancel_build(job_name="my-project/main", build_number=42)
```

### 查看触发记录

```
list_triggered_jobs()
```

### 列出构建归档

```
list_build_artifacts(job_name="my-project/main", build_number=42)
```

### 下载归档文件

```
fetch_build_artifact(job_name="my-project/main", build_number=42, artifact_path="target/app.jar")
```
