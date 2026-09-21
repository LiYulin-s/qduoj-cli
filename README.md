# qduoj-cli

QingdaoU OnlineJudge (QDU OJ) 命令行客户端：登录、看题、提交代码、终端查看逐测试点评测结果。

## 安装

```bash
uv tool install .   # 或 uv tool install git+https://github.com/<you>/qduoj-cli
```

## 使用

```bash
qduoj-cli config https://your-oj.example.com   # 首次使用：保存服务器地址
qduoj-cli login                                 # 交互式登录（支持两步验证）
qduoj-cli whoami                                # 查看当前用户

qduoj-cli problem 1000                          # 查看题目（描述/样例/限制）
qduoj-cli submit 1000 main.cpp                  # 提交并等待评测结果
qduoj-cli status <提交号> --wait                 # 查看提交结果
qduoj-cli submissions                           # 我的提交记录

qduoj-cli contests                              # 比赛列表
qduoj-cli contest 5 --password <密码>           # 解锁密码比赛
qduoj-cli problem A1 --contest 5                # 比赛题（需要时会提示输入密码）
qduoj-cli submit A1 sol.cpp --contest 5
```

## 配置

- 服务器地址存于 `~/.config/qduoj-cli/config.toml`，环境变量 `QDUOJ_BASE_URL` 或全局 `--base-url` 可覆盖
- 登录会话存于 `~/.config/qduoj-cli/session.json`；`qduoj-cli logout` 清除

## 开发

```bash
uv sync
uv run qduoj-cli --help
```
