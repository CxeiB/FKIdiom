# FKIdiom · 习语

一个给自己用的中文成语学习 Web App：按拼音首字母分组的词书、间隔重复复习、默写 / 选词两种练习模式，支持 OIDC 登录与多用户数据隔离。

> **说明：本项目的全部代码、词条数据整理与文档均由 AI 生成**，经人工审阅后使用。

## 功能

- **分组词书**：A–G 按拼音首字母分组，共 1388 条常用成语，含拼音、字义、词义、出处、例句、近反义、用法
- **间隔重复**：SM-2 风格调度，复习间隔以天为单位，答错次日再练
- **三种练习模式**：默写（手打成语）/ 选词（四选一，答错展示双方释义对比）/ 关闭（只看卡片）
- **学习统计**：今日新学与复习、连续天数、正确率、薄弱词
- **多用户**：OIDC 授权码 + PKCE 登录，每个用户独立进度
- **PWA**：可添加到手机主屏，离线壳加载

## 结构

```
server.py            # 单文件后端：HTTP 服务 + SQLite + OIDC
index.html           # 单页前端，无框架
words.json           # 词书数据
manifest.webmanifest # PWA 清单
icons/ splash/       # 图标与启动图
```

## 运行

```bash
python3 server.py          # 默认 8080
PORT=9000 python3 server.py
```

首次启动会自动创建 `state.db`。

## 登录配置（可选）

不配置 `oidc.json` 时以单用户模式运行；配置后强制登录并按用户隔离数据。

```json
{
  "issuer": "https://example.com",
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "redirect_uri": "https://idiom.example.com/oidc/callback"
}
```

## 数据来源

成语释义整理自公开语料，仅供个人学习使用。

## License

MIT
