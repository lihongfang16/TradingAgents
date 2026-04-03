# 历史界面进度显示修复计划

## 问题诊断

### 问题 1: 进度计数器 Bug
**位置**: `web/components/history_manager.py` 第 476-477 行

`progress_fetch_count` 在获取进度后没有递增，导致所有运行中任务都会获取进度。

### 问题 2: 已完成任务缺少耗时显示
只显示状态图标和文本，如 `✅ BUY`，不显示总耗时。

### 问题 3: 进度条文字格式不清晰
从 `2分22秒 / 剩余: 0秒` 优化为 `⏱️ 2分22秒 | ⏳ 剩余: 0秒`

---

## 修复内容

### 修改 1: 修复计数器 Bug + 优化格式
```python
# Line 477: 添加计数器递增
progress_info = get_task_progress(task_id)
progress_fetch_count += 1  # FIX

# Line 485: 优化文字格式
st.progress(prog / 100, text=f"⏱️ {elapsed_str} | ⏳ 剩余: {remaining_str}")
```

### 修改 2: 为已完成任务添加耗时显示
```python
# Line 492-493: 替换 else 分支
else:
    updated_at = record.get("updated_at", "")
    duration_text = ""
    if created_at and updated_at:
        try:
            created_dt = datetime.fromisoformat(created_at)
            updated_dt = datetime.fromisoformat(updated_at)
            duration = (updated_dt - created_dt).total_seconds()
            duration_text = f" (⏱️ {format_duration(int(duration))})"
        except Exception:
            pass
    st.write(f"{status_emoji} {status_text}{duration_text}")
```

---

## 实施流程

### Phase 1: 本地开发与验证

#### Step 1.1: 代码修改
- [ ] 修改 `web/components/history_manager.py`
- [ ] 添加 `progress_fetch_count += 1`
- [ ] 优化进度条文字格式
- [ ] 添加已完成任务耗时显示

#### Step 1.2: 本地静态检查
```bash
# 检查语法
python -m py_compile web/components/history_manager.py

# 检查导入
python -c "from web.components.history_manager import *"
```

#### Step 1.3: 本地启动验证（如有本地环境）
```bash
# 启动本地服务
cd web && streamlit run app.py

# 或使用 docker-compose
docker-compose up web
```

#### Step 1.4: 本地功能验证清单
- [ ] 代码语法检查通过
- [ ] 模块导入无错误
- [ ] 运行中任务显示进度条
- [ ] 进度条文字格式正确
- [ ] 已完成任务显示总耗时

### Phase 2: 远程部署与验证

#### Step 2.1: 上传代码
```bash
scp web/components/history_manager.py \
  ops@49.235.131.200:/home/ops/tradingagents-a-share/web/components/
```

#### Step 2.2: 部署到容器
```bash
ssh ops@49.235.131.200 "
  docker cp /home/ops/tradingagents-a-share/web/components/history_manager.py \
    tradingagents-a-share-web-1:/app/web/components/
  docker restart tradingagents-a-share-web-1
"
```

#### Step 2.3: 等待服务就绪
```bash
# 检查容器状态
ssh ops@49.235.131.200 "docker ps | grep web"

# 检查服务健康
until curl -s http://10.8.0.1:8501/health > /dev/null; do
  echo "Waiting for service..."
  sleep 2
done
```

### Phase 3: 远程功能验证

#### Step 3.1: 浏览器验证（使用 chrome-devtools）
1. 访问 `http://10.8.0.1:8501`
2. 点击进入历史记录页面
3. 验证以下功能：

| 检查项 | 预期结果 |
|--------|----------|
| 运行中任务进度条 | 显示进度条 + `⏱️ X分X秒 \| ⏳ 剩余: X分X秒` |
| 已完成任务耗时 | 显示 `✅ BUY (⏱️ X分X秒)` |
| 计数器限制 | 超过3个运行任务时，第4个只显示"分析中..." |
| 日期显示 | 格式为 `2026-03-25 23:30` |

#### Step 3.2: 截图验证
- [ ] 运行中任务进度显示截图
- [ ] 已完成任务耗时显示截图
- [ ] 整体历史页面截图

#### Step 3.3: 回归测试
- [ ] 删除功能正常工作
- [ ] 查看详情功能正常工作
- [ ] 搜索过滤功能正常工作
- [ ] 页面无 JavaScript 错误

### Phase 4: 回滚准备（如需要）

#### 回滚命令
```bash
# 从 git 恢复原始版本
git checkout web/components/history_manager.py

# 重新部署
scp web/components/history_manager.py ops@49.235.131.200:/home/ops/tradingagents-a-share/web/components/
docker cp ... && docker restart ...
```

---

## 预期效果

| 状态 | 修改前 | 修改后 |
|------|--------|--------|
| RUNNING | 🔄 分析中... | 🔄 进度条 `⏱️ 1分30秒 \| ⏳ 剩余: 2分30秒` |
| COMPLETED | ✅ BUY | ✅ BUY `(⏱️ 5分20秒)` |
| FAILED | ❌ 失败 | ❌ 失败 `(⏱️ 1分10秒)` |

---

## 风险控制

1. **本地验证先行**: 必须在本地验证代码语法和逻辑正确性
2. **分阶段部署**: 先上传代码，确认无误后再重启容器
3. **快速回滚**: 保留原始代码备份，可随时回滚
4. **验证清单**: 严格按照清单验证，不跳过任何步骤
