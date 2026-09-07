# 前端四个 Hooks：结合项目代码的详细讲解

本文依据当前工作区实现，解释会话管理、任务轮询、健康检查和冷却控制的封装。代码块为原代码摘录或注明的简化示例；改进建议不代表已经实现。

## 1. 阅读入口与整体职责

| 文件 | 职责 |
|---|---|
| [useConversation.ts](../web/src/hooks/useConversation.ts) | 保存会话状态，提供消息和客户信息操作 |
| [useJobPolling.ts](../web/src/hooks/useJobPolling.ts) | 根据任务 ID 查询结果，处理重试、超时和清理 |
| [useHealthCheck.ts](../web/src/hooks/useHealthCheck.ts) | 挂载时检查后端连接，提供三态结果 |
| [useCooldown.ts](../web/src/hooks/useCooldown.ts) | 管理可重新计时的冷却窗口 |
| [SupportForm.tsx](../web/src/components/SupportForm.tsx) | 组合 Hooks，协调提交、消息更新、审核和重试 |
| [api.ts](../web/src/lib/api.ts) | 统一封装 HTTP 请求和 HTTP 错误 |
| [types.ts](../web/src/lib/types.ts) | 定义消息、会话和 API 数据类型 |

四个 Hooks 均声明 `"use client"`，供 React 客户端组件使用。它们没有直接访问模型或数据库；轮询和健康检查通过 API 客户端访问后端。

自定义 Hook 复用的是状态逻辑，不会自动创建全局共享状态。不同组件各自调用 `useConversation()` 时，得到各自的会话；当前由同一个 `SupportForm` 实例持有并向子组件传递。

```text
SupportForm
├── useConversation → 消息列表、客户信息、追问模式
├── useJobPolling   → 后台任务查询与结果通知 → api.ts
├── useHealthCheck  → 后端连接状态           → api.ts
└── useCooldown     → 完成后的冷却状态

SupportForm → InitialForm / MessageInput / ChatThread / StatusIndicator
```

## 2. useConversation：把会话状态与操作集中封装

### 2.1 状态结构

核心状态摘录，省略注释：

```ts
const initialConversation: Conversation = {
  messages: [],
  customerName: "",
  customerEmail: "",
  isFollowUpMode: false,
};

const [conversation, setConversation] =
  useState<Conversation>(initialConversation);
```

`messages` 是有序消息列表；姓名和邮箱供后续追问复用；`isFollowUpMode` 控制页面显示首次表单还是追问输入框。

消息的关键字段包括 `id`、`role`、`content`、`timestamp`、`status`，还可保存 `error`、`citations`、`requiresHumanReview` 和 `reviewReason`。前端消息状态为 `sent / processing / completed / failed`，不与后端任务状态完全相同。

### 2.2 对外接口

```ts
return {
  conversation,
  addCustomerMessage,
  updateMessageStatus,
  setCustomerInfo,
};
```

组件读取状态，通过操作方法发起更新，无须在多个事件处理器里重复拼装消息对象。

### 2.3 addCustomerMessage：立即展示用户消息

核心代码：

```ts
const addCustomerMessage = useCallback((content: string): Message => {
  const message: Message = {
    id: crypto.randomUUID(),
    role: "customer",
    content,
    timestamp: new Date(),
    status: "sent",
  };

  setConversation((prev) => ({
    ...prev,
    messages: [...prev.messages, message],
  }));

  return message;
}, []);
```

执行过程：创建消息 → 生成前端唯一 ID 和时间 → 追加列表 → 将消息对象返回给组件。

`SupportForm` 不等待服务器回复就展示客户消息：

```ts
const msg = addCustomerMessage(messageText);
setActiveMessageId(msg.id);
updateMessageStatus(msg.id, "processing");
```

这里先返回对象，是为了让组件立刻拿到 `msg.id`。React 状态更新是调度式的，调用 setter 后不能依赖当前闭包里的 `conversation` 已经同步改变。

初始 `sent` 只是本地消息标记，不证明请求已经被服务器接受；当前调用方随后立即标记为 `processing`，中间状态也可能被 React 批量更新合并。

### 2.4 updateMessageStatus：更新问题并追加回复

参数定义：

```ts
(
  id: string,
  status: Message["status"],
  response?: string,
  error?: string,
  result?: JobStatus,
)
```

`Message["status"]` 是 TypeScript 索引访问类型，复用已有消息类型的状态约束，避免另写一份不一致的联合类型。

方法内部首先创建新数组，更新 ID 匹配的消息：

```ts
const messages = prev.messages.map((msg) =>
  msg.id === id ? { ...msg, status, error } : msg,
);
```

如果 `status === "completed" && response`，再创建 Agent 消息追加到新数组。注意判断要求回答字符串为真值，空字符串不会追加。

Agent 消息会从可选的 `result` 映射字段：

```ts
citations: result?.citations,
requiresHumanReview: result?.requires_human_review,
reviewReason: result?.review_reason,
```

这也是后端下划线字段到前端驼峰字段的一处适配。`messages.push(agentMessage)` 操作的是本次 `map` 产生的新数组，不是原来的 `prev.messages`。

最后更新追问模式：

```ts
isFollowUpMode: prev.isFollowUpMode || status === "completed"
```

一旦进入追问模式，后续处理或失败不会自动将其改回首次表单。即使没有有效 `response`，只要传入 `completed`，该标记也会开启。

### 2.5 setCustomerInfo 与追问

`setCustomerInfo` 通过函数式更新只修改姓名和邮箱，保留消息等其他字段。`SupportForm` 在尚未进入追问模式时保存客户信息，后续提交通过下面的方式复用：

```ts
handleSubmit(
  conversation.customerName,
  conversation.customerEmail,
  message,
);
```

本 Hook 保存的是页面内存状态。没有 localStorage、历史恢复接口、会话重置方法；当前 `submitChat` 也不发送整个 `messages` 数组。后端如何构造历史上下文应另行查看后端实现。

### 2.6 为什么采用函数式更新和 useCallback？

`setConversation(prev => ...)` 用 React 提供的最新待更新状态计算结果。连续添加两条消息时，后一次更新可以接着前一次结果继续追加，减少旧闭包覆盖更新的风险。

三个操作方法通过 `useCallback` 保持引用稳定。它们依赖 setter 和显式参数，读取状态通过 `prev`，所以无需将 `conversation` 加入依赖数组。

稳定函数引用有助于控制其他 Hook 的依赖变化，但并不意味着使用这些方法的组件一定不会重新渲染。

### 2.7 当前边界

- `updateMessageStatus` 没有检查对应消息是否存在、是否是客户消息，再决定是否追加回复。
- 重复传入同一次完成结果，可能重复追加 Agent 消息，没有按 job ID 去重。
- Agent 消息的随机 ID 和时间在状态更新函数内部生成；若加强 updater 的纯函数设计，可以将这些值提前准备。
- 普通完成回调目前只传回答字符串，因此这条调用路径没有把完整结果中的 citations 传入；审核路径则传入了完整 `JobStatus`。

## 3. useJobPolling：封装后台异步任务查询

### 3.1 接口与状态

```ts
export function useJobPolling(
  jobId: string | null,
  onComplete: (status: JobStatus) => void,
  onError: (error: string) => void,
  onReview?: (status: JobStatus) => void,
)
```

返回 `{ isPolling, elapsed }`。`elapsed` 单位为秒，当前 `SupportForm` 只使用 `isPolling`。

| 配置 | 当前值 |
|---|---|
| TIMEOUT_MS | 5 分钟 |
| REQUEST_TIMEOUT_MS | 单次状态请求 15 秒 |
| MAX_NETWORK_RETRIES | 连续 3 次查询异常后结束 |
| DEFAULT_RETRY_AFTER_MS | 5 秒 |
| MAX_RETRY_DELAY_MS | 网络重试最多等待 30 秒 |

常量名包含 retries，但真实行为是第 3 次连续失败就终止，不是首次失败后再额外重试 3 次。

### 3.2 useEffect：以 jobId 为生命周期边界

Effect 依赖为 `[jobId, cleanup]`。`jobId` 为空时重置 elapsed 并返回；有 ID 时清零本次失败计数、记录开始时间并设为轮询中。

任务改变时，React 先执行旧 Effect 的清理，再建立新 Effect。每一轮 Effect 的 `stopped` 和 `networkFailures` 是各自闭包中的变量，不会随普通重新渲染自动清零。清理还会中止旧任务正在执行的状态请求。

### 3.3 定时器与请求控制

网络查询使用递归 setTimeout：

```ts
function schedulePoll(delayMs: number) {
  if (stopped) return;
  timerRef.current = setTimeout(poll, delayMs);
}
```

首次固定等待 5 秒。请求完成且仍需等待时，再安排下一次。真实请求间隔约为“上一次请求耗时 + 指定等待时间”，不是固定节拍。

每次请求创建独立的 `AbortController`。单次请求达到 15 秒、任务达到 5 分钟、任务切换或组件卸载时，都会中止当前请求。独立的 5 分钟定时器保证即使 fetch 一直没有返回，轮询也会按时结束。

另一个 setInterval 每秒刷新显示用 elapsed：

```ts
const seconds = Math.floor((Date.now() - startTimeRef.current) / 1000);
setElapsed(Math.min(seconds, TIMEOUT_MS / 1000));
```

用实际时间差而非每次简单加一，有助于避免定时器延迟导致累计计时偏差；后台标签页的定时器仍可能被浏览器节流。

### 3.4 为什么将回调放入 useRef？

```ts
const onCompleteRef = useRef(onComplete);
onCompleteRef.current = onComplete;
```

普通渲染可能产生新的 `handlePollComplete`，它捕获最新 `activeMessageId`。如果定时器始终调用首次渲染的回调，可能操作旧消息；如果把变化的回调直接作为 Effect 依赖，又可能反复重启轮询和计时。

当前代码在一个独立 Effect 中更新 ref，定时器通过 `onCompleteRef.current(...)` 调用最新版本，使回调更新与轮询生命周期分离。onError、onReview 使用相同方式。

`useRef` 也保存定时器句柄和起始时间，因为这些值需要跨渲染保留，但修改它们本身无需触发界面渲染。

### 3.5 一次 poll 的执行分支

| 分支 | 行为 |
|---|---|
| stopped | 直接返回 |
| 整体达到 5 分钟 | 中止在途请求并调用超时错误回调 |
| completed 且 response 非空 | cleanup，调用 onComplete(status) |
| completed 但 response 为空 | cleanup，调用空回答错误回调 |
| waiting_review | cleanup，调用可选 onReview(status) |
| failed | cleanup，调用 onError，优先使用后端 error |
| rejected | cleanup，调用审核拒绝错误回调 |
| 其他状态 | 按 retry_after 或默认 5 秒继续查询 |
| 408、429、5xx、网络错误或单次超时 | 累计失败并按 5 秒、10 秒指数退避，连续第 3 次失败后停止 |
| 其他 4xx | 立即停止并显示 API 返回的错误 |

查询成功时，无论仍在 processing 还是已经结束，都会将连续失败次数清零。

`retry_after` 的处理代码：

```ts
const delay = status.retry_after !== null && status.retry_after !== undefined
  ? Math.max(0, status.retry_after * 1000)
  : DEFAULT_RETRY_AFTER_MS;
```

秒转换为毫秒，并显式区分空值，所以 `retry_after: 0` 会立即安排下一轮。提交接口返回的首次 `retry_after` 没有传入该 Hook；首次仍固定 5 秒。

### 3.6 清理和取消

`cleanup()` 清除轮询、整体截止、单次请求和 elapsed 定时器，中止在途请求，将对应 ref 置空，并设 `isPolling = false`。终态、超时、不可重试错误和连续失败都会调用它。

Effect 返回的清理函数先设置停止标记，再统一清理：

```ts
return () => {
  stopped = true;
  cleanup();
};
```

即使底层 mock 或异常环境没有响应 abort，异步请求返回后也会检查 `stopped`，旧结果不会继续调用业务回调。

### 3.7 超时和异常的实际边界

- `getJobStatus` 通过 `ApiError.status` 保留 HTTP 状态；408、429 和 5xx 可重试，其他 4xx 立即失败。
- 单次请求超时和总任务超时分别是 15 秒与 5 分钟；前者进入网络重试，后者直接结束任务。
- 指数退避只用于请求异常；服务端正常返回 processing 时仍遵守 `retry_after`。
- waiting_review 即使未提供 onReview，也会停止轮询；调用方应传入处理器。
- Hook 一次只管理一个 job。`SupportForm` 用同步 ref 锁阻止任务结束前的重复提交，避免新任务覆盖当前任务；如产品需要并行任务，应把状态提升为按 job ID 管理的集合。

## 4. useHealthCheck：挂载时的一次连接检查

实现完整核心逻辑：

```ts
const [isHealthy, setIsHealthy] = useState<boolean | null>(null);

useEffect(() => {
  let cancelled = false;

  checkHealth().then((healthy) => {
    if (!cancelled) setIsHealthy(healthy);
  });

  return () => {
    cancelled = true;
  };
}, []);

return { isHealthy };
```

三态比初始值直接使用 false 更准确：null 表示结果未返回，true 表示健康，false 表示不可用。

`api.ts` 的 checkHealth 请求 `/health`，只有 HTTP 成功且 JSON 中 `status === "ok"` 才返回 true。非成功 HTTP、网络失败、JSON 解析异常均转换为 false，因此 Hook 的 then 无须重复实现这些错误判断。

`StatusIndicator` 根据 null / true / false 分别显示 Checking connection / Connected / Service unavailable，并用灰、绿、红色提示。

空依赖表示每次正常挂载检查，不是定时心跳。React 开发环境 Strict Mode 可能额外执行 Effect 建立和清理，不能承诺所有环境只发生一个 HTTP 请求。

该 Hook 没有手动重查、自动恢复探测、请求超时或 AbortController。健康状态只用于展示，没有参与当前提交禁用条件；状态也不保证后续每次请求一定成功。

## 5. useCooldown：可配置的重新计时窗口

核心代码：

```ts
export function useCooldown(durationMs: number = 10000) {
  const [isCoolingDown, setIsCoolingDown] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const startCooldown = useCallback(() => {
    setIsCoolingDown(true);
    if (timerRef.current) clearTimeout(timerRef.current);

    timerRef.current = setTimeout(() => {
      setIsCoolingDown(false);
      timerRef.current = null;
    }, durationMs);
  }, [durationMs]);

  return { isCoolingDown, startCooldown };
}
```

状态控制界面，ref 管理定时器句柄；句柄变化无需渲染。`ReturnType<typeof setTimeout>` 从函数推导句柄类型，减少不同类型环境下手写 timer 类型的不一致。

默认冷却 10 秒。再次调用先清掉旧计时器，再从当前时间重新计算。例如 5 秒冷却在第 3 秒重启，将在第 8 秒结束，而不是第 5 秒结束。

`useCallback` 依赖 durationMs，使下一次调用采用新的时长；仅改变参数不会重排已经建立的旧定时器。

当前组件在普通任务完成时调用 startCooldown；提交进行中用 isSubmitting / isPolling 禁止操作，成功后再用冷却标记继续限制提交。

这是前端冷却窗口，不提供服务器限流，也不延迟某个函数直到输入停止，不应直接称为输入防抖。刷新页面或直接调用 API 可以绕过它。

当前缺少卸载清理 Effect、主动取消接口、剩余时间和 durationMs 参数校验。这些是可改进点，不能描述为已有能力。

## 6. SupportForm：将四个 Hooks 串成业务流程

### 6.1 两个 ID 与三个状态

| 字段 | 含义 |
|---|---|
| activeMessageId | 前端客户消息 ID，用于更新聊天气泡 |
| activeJobId | 后端异步任务 ID，用于查询任务 |
| isSubmitting | 从提交开始到任务完成/失败/待审核期间的组件状态 |
| isPolling | Hook 是否处于任务查询流程 |
| isCoolingDown | 普通完成后是否处于冷却窗口 |

两个 ID 的来源与用途不同。当前关联保存在组件的 active 字段中，虽然 Message 类型有可选 jobId，但添加消息时没有自动填入它。

### 6.2 正常提交与完成

```text
输入校验通过
→ isSubmitting = true，保存 lastSubmission
→ 保存客户信息，追加客户消息，标记 processing
→ POST /api/chat，拿到 job_id
→ activeJobId 更新，开始轮询
→ GET /api/jobs/{job_id} 返回 completed 且有回答
→ 停止轮询，handlePollComplete 更新消息并追加回复
→ 清空 active ID、错误和重试数据，isSubmitting = false
→ 进入追问模式，开启 10 秒冷却
→ 冷却结束后允许继续提交
```

提交函数属于 SupportForm，useConversation 自身不发送 HTTP。

### 6.3 失败与两种重试

轮询内部重试：仍使用同一个 job_id，只重新查询状态，不创建新任务。

用户点击 Try Again：组件使用 lastSubmission 重新执行 handleSubmit，会追加一条新的客户消息并再次 POST，创建新任务；它不是恢复旧任务。

失败路径清空 active ID、结束提交状态并显示错误，保留 lastSubmission 供用户重试。普通失败不会启动冷却。

### 6.4 人工审核路径

waiting_review 触发 handleReview。组件将前端客户消息标记为 completed，追加带审核信息的草稿或等待提示，保存 pendingReview 和 editedAnswer，并结束轮询和提交状态。

因此，前端 completed 在这条路径上表示消息进入展示阶段，不代表后台任务已经批准或最终回答完成。后端 waiting_review 与前端消息状态要分别理解。

审核按钮通过 submitReview 提交 approve / edit / reject。当前成功后只清空 pendingReview，没有继续轮询，也没有使用接口返回值更新已有聊天消息；审核流程同样不会调用 startCooldown。

### 6.5 界面状态组合

```ts
const isProcessing = isSubmitting || isPolling;
```

追问输入框接收：

```tsx
<MessageInput disabled={isProcessing || isCoolingDown} />
```

首次表单接收 isSubmitting 和 isCoolingDown，提交按钮使用两者的或运算；其文本字段主要根据 isSubmitting 禁用。

MessageInput 还检查非空和最大长度，Enter 提交、Shift+Enter 换行。字段校验属于输入组件，不属于这四个 Hooks。

当前没有把 `isHealthy` 或 `pendingReview` 加入提交禁用条件，也没有在 SupportForm.handleSubmit 开头建立统一的同步防重入锁。按钮禁用是交互控制，不能替代后端幂等和限流。

## 7. 已有测试如何验证这些封装

测试位于 [web/src/__tests__/hooks](../web/src/__tests__/hooks)。以下描述源于测试代码阅读，不表示本次文档任务重新执行了测试。

| Hook | 已有测试场景 | 主要方法 |
|---|---|---|
| useConversation | 初始状态、消息字段、追加顺序、状态更新、Agent 回复、追问模式、错误和客户信息 | renderHook、act、检查 result.current |
| useJobPolling | 空 ID、完成、多轮查询、失败、等待审核、HTTP 分类、指数退避、retry_after 为 0、单次和整体超时、卸载取消 | mock getJobStatus、fake timers、AbortSignal、异步推进时间 |
| useHealthCheck | 初始 null、健康、异常、挂载调用次数 | mock checkHealth、等待 Promise 更新 |
| useCooldown | 初始状态、启动、到期、默认 10 秒、重复调用重新计时 | fake timers、act 内推进时间 |

例如等待 5 秒的测试不必真实休眠：

```ts
await act(async () => {
  await vi.advanceTimersByTimeAsync(5000);
});
```

fake timers 控制定时器，异步推进同时处理 Promise；act 让测试在断言前处理 React 更新。`result.current` 读取最近一次渲染结果。

可补充的测试包括旧任务迟到响应、回调更新不重启轮询、rejected 终态、HTTP 请求挂起、重复完成去重、正常回答引用保留，以及冷却卸载清理。

## 8. 面试讲述：先讲业务，再解释代码

使用顺序：先练熟本节的一分钟回答；再用第 9 节练习追问；遇到不理解的细节，回看第 2～7 节代码说明。不需要在开场一次讲完所有实现边界。

### 8.1 一分钟开场回答

“这个项目的客服处理是异步的，前端提交问题以后，后端先返回任务 ID，前端再轮询结果。我把相关逻辑拆成四个 Hook：会话 Hook 管消息列表、客户信息和追问模式；轮询 Hook 管任务查询、重试、超时和定时器清理；健康检查 Hook 在页面挂载时检查后端连接；冷却 Hook 在正常回答完成后限制十秒内再次提交。最后由 SupportForm 把它们组合起来，负责提交请求和处理完成、失败、人工审核这些业务分支。这样组件主要描述页面和流程，各个 Hook 的状态逻辑也能单独测试。”

### 8.2 被要求展开时，按一次请求说明

“用户提交时，我先在前端插入客户消息并标记为处理中，同时保存它的消息 ID。提交接口返回的是后台任务 ID，这两个 ID 分别用于更新气泡和查询任务。拿到任务 ID 后，轮询 Hook 开始工作；任务完成时，通过回调让组件更新原消息并追加 Agent 回复，清空当前任务状态，再启动十秒冷却。后续追问复用已经保存的姓名和邮箱。如果查询失败，Hook 负责有限重试；如果最终失败，组件显示错误并保留上一次提交，方便用户重新发送。”

### 8.3 回答设计题的结构

使用“具体问题 → 代码做法 → 行为结果 → 当前边界”的顺序。例如讨论取消：每次查询都带独立的 AbortSignal，清理 Effect 时设置 stopped 并调用 abort；即使异常环境不响应 abort，旧响应回来后也会因 stopped 而被忽略。

别只列出 useState、useEffect、useRef、useCallback。每提到一个 API，都能接着说明它保存什么、何时变化、解决哪一种具体问题。

## 9. 常见追问与口语式回答

### 9.1 为什么拆成四个 Hook，而不是都放在组件里？

“这四类逻辑的状态和变化原因不同。消息更新不应该关心轮询间隔，连接检查也不需要知道当前客户是谁。我把独立的状态机制拆开，把它们之间的业务协调留在 SupportForm。这样查看某种行为时有明确入口，也能单独测试。不过自定义 Hook 复用的是逻辑，不会自动共享状态；如果要让多个页面共享会话，还要额外设计状态提升或共享容器。”

### 9.2 为什么用函数式状态更新？

“添加消息依赖已有消息列表。如果回调拿着旧 conversation 直接拼新数组，连续更新时可能把另一条消息覆盖掉。函数式更新让 React 把最新的待更新状态传进来，每次在 prev.messages 后面追加，所以不需要依赖闭包里那份旧列表。”

简化示例，假设当前列表为空：

```ts
// 两次都从同一个旧 messages 计算，可能只留下 B。
setMessages([...messages, A]);
setMessages([...messages, B]);

// 两次更新依次基于待更新状态计算，结果为 [A, B]。
setMessages((prev) => [...prev, A]);
setMessages((prev) => [...prev, B]);
```

这不是说 React 单线程更新存在传统线程锁问题，而是闭包状态快照与批量更新的组合需要正确处理。

### 9.3 为什么递归 setTimeout，而不是 setInterval？请求花十秒怎么办？

“我的下一次查询是在上一次请求返回以后才安排的，所以同一个轮询周期内不会因为接口变慢而叠加查询。假设默认等待五秒，第一次请求从第五秒开始，花十秒到第十五秒返回，如果还在处理中，再等五秒，到第二十秒开始下一次查询。setInterval 如果没有额外的在途保护，就可能在前一个请求还没结束时继续发起请求。”

```text
0s       5s                    15s       20s
建立轮询 → 发起第一次查询 ──────→ 返回 → 等待5秒 → 第二次查询
```

因此不要说“每五秒一定发一次请求”；准确说法是“默认在上次请求结束后等待五秒再查询”。setInterval 配合在途标记也能避免重叠，只是当前没有采用该方案。

### 9.4 为什么回调放 useRef，不直接放 Effect 依赖里？

“完成回调会捕获组件里的 activeMessageId，组件更新后它可能变成新的函数。我希望轮询调用最新回调，但不希望回调变化就把整个轮询停掉重建。所以将回调保存到 ref，每次渲染更新 current，定时器触发时从 current 取最新函数。轮询是否重新开始主要由 jobId 决定。”

如果继续追问旧闭包：定时器中的函数保留创建时的作用域；没有 ref 或其他同步机制，就可能一直使用创建定时器时的回调版本。ref 提供跨渲染保留的可变容器，读 current 时获取更新后的引用。

### 9.5 useState 和 useRef 怎么分工？

“影响界面展示的值放 state，比如消息、是否轮询、是否冷却。需要跨渲染保存，但修改后不需要触发渲染的值放 ref，比如定时器句柄、开始时间和最新回调。ref 本身不会自动让 UI 更新，所以 elapsed 仍然用 state。”

### 9.6 useCallback 是为了让组件完全不重渲染吗？

“不是。它是在依赖不变时复用函数引用，便于控制 Effect 依赖和传递给子组件的函数 props。组件是否重新渲染还受 state、其他 props 和是否采用 memo 等因素影响。我这里更直接的收益是保持操作函数和 cleanup 引用稳定。”

### 9.7 为什么既有 isSubmitting，又有 isPolling？

“提交请求发出但任务 ID 还没返回时，轮询还没有开始，单用 isPolling 覆盖不了这段等待，所以组件保留了 isSubmitting。当前实现里 isSubmitting 一直持续到任务完成、失败或等待审核，和轮询阶段有重叠，界面用二者的或运算表示处理中。以后状态更复杂，可以考虑统一成显式阶段状态，减少多个布尔值的组合。”

### 9.8 连续失败三次和用户点击重试有什么区别？

“轮询失败重试还是查原来的 jobId，任何一次查询成功就清零连续失败次数，第三次连续失败会结束轮询。用户点击 Try Again 则是用保留的提交内容重新调用 POST 接口，会创建新消息和新任务。这个区别也意味着重新提交要考虑后端幂等，不能把它理解成继续等待原任务。”

### 9.9 组件卸载或任务切换时，如何处理旧请求？

“清理函数会将这轮 Effect 的 stopped 设为 true，清除轮询、截止时间、单次请求和 elapsed 定时器，并通过 AbortController 中止在途请求。即使底层环境没有响应 abort，旧结果回来后也不会调用业务回调。”

### 9.10 五分钟超时是严格截止吗？

“是。任务启动时会同时建立独立的五分钟截止计时器；到期后直接标记停止、中止在途请求并调用超时回调。每次 fetch 另有十五秒超时，单次超时会按可恢复的网络错误进入重试。”

### 9.11 健康检查为什么用 null、true、false？会自动恢复吗？

“null 表示检查还没完成，不能在一开始就把服务显示成故障；true 和 false 表示检查结果。当前挂载时检查一次，没有周期重试或自动恢复探测，显示健康也不保证后续请求一定成功。实际请求仍由各自的错误处理负责。”

### 9.12 冷却控制是不是防抖或者限流？

“它是正常完成后的前端冷却窗口。调用 startCooldown 就进入冷却，默认十秒，重复调用会重新计时。它没有延迟执行提交函数，所以我不会把它说成输入防抖；用户也能绕过页面直接调用 API，因此不能替代后端限流。”

### 9.13 怎么测轮询和冷却，不会每次都等五分钟吧？

“用 Vitest 假定时器控制时间，用 mock API 按顺序返回 processing、completed 或错误，再通过 renderHook 观察状态和回调。测试轮询时用异步方式推进定时器并配合 act，让 Promise 和 React 更新处理完再断言。五分钟超时只是推进模拟时间，不需要真实等五分钟。”

### 9.14 为什么 waiting_review 也调用 completed？

“这里有两套状态：后端任务是 waiting_review，前端消息却只有 sent、processing、completed、failed。当前用 completed 把这次问题处理切换到可展示阶段，再用 requiresHumanReview 和 pendingReview 表达审核状态。它不代表答案已经批准。后续可以给前端补充明确的审核状态，避免混用。”

## 10. 场景推演：离开代码也能说明行为

| 场景 | 当前实现的预期行为 | 回答时必须提到 |
|---|---|---|
| jobId 为 null | 不发查询，elapsed 为 0 | 任务 ID 是启动条件 |
| 首次查询花十秒，仍处理中 | 请求结束后再按间隔安排下一次 | 递归 timeout，不是固定节拍 |
| 查询失败、成功、失败 | 两次失败不累计成连续两次 | 成功清零失败计数 |
| 查询连续失败三次 | 停止并调用错误回调 | 总共三次失败，不是额外三次重试 |
| 改变完成回调但 jobId 不变 | 轮询保持，后续取 ref 中的新回调 | 回调更新与生命周期分离 |
| 切到新 job，旧请求仍在途 | 旧 Effect 中止请求并忽略任何迟到结果 | abort 与 stopped 双重保护 |
| 五分钟内有一次请求一直挂起 | 单次十五秒时中止并重试；总计五分钟时强制结束 | 两层独立截止时间 |
| waiting_review | 停止查询，交给审核处理器 | 不自动继续等审核完成 |
| 5 秒冷却在第 3 秒重启 | 约第 8 秒结束 | 清除旧 timer 后重新计时 |
| 冷却中修改 durationMs | 已存在 timer 不自动改期 | 新时长用于下一次 startCooldown |
| 页面刷新 | 本地会话和冷却重新初始化 | 无持久化 |
| 后端启动时健康，之后断线 | 状态灯不一定立即变化 | 当前仅挂载检查 |

## 11. 讲述边界与改进顺序

下面是被追问时应准确表达的边界，不需要开场主动背完整张表。

| 不准确的说法 | 基于当前代码的准确说法 |
|---|---|
| “每五秒准时查一次” | 首次等五秒，后续在请求结束后按 retry_after 或默认间隔查询 |
| “所有错误都按五秒固定重试” | 可恢复请求错误按 5 秒、10 秒指数退避；普通 4xx 立即失败；processing 遵守 retry_after |
| “一个 Hook 可以同时追踪多个任务” | Hook 一次管理一个 job；SupportForm 在任务终止或审核完成前锁住新提交 |
| “健康检查会持续监控” | 正常挂载时检查，没有周期探测 |
| “会话 Hook 自动恢复历史” | 保存当前组件内存状态，没有刷新恢复 |
| “十秒冷却保证用户无法频繁调用 API” | 只控制前端交互，不能代替后端限制 |
| “轮询会采用提交接口的首次 retry_after” | Hook 只接收 jobId，因此首次查询仍固定等待五秒 |

如果被问“你会先改什么”，可以这样回答：

“我会先根据产品需求判断是否要支持并行任务；如果仍是单任务交互，就保持提交锁并补强提示。随后再评估是否把提交接口的首次 retry_after 传入 Hook，以及是否增加健康检查重试和会话持久化。每个改动都补对应场景测试；涉及 API 字段变化时，也要同步后端模型、前端类型、客户端和契约测试。”

这是改进计划，不代表这些功能已经完成。

## 12. 自测与练习方式

### 12.1 三轮练习

1. 一分钟：合上文档，说清异步客服场景、四个 Hook 的职责和 SupportForm 的作用。
2. 三分钟：选一次正常提交，讲出消息 ID、任务 ID、轮询、完成回调、追问和冷却的顺序。
3. 五分钟：随机选第 9 节三个问题和第 10 节两个异常场景，先独立回答，再对照代码核验。

练习时可以录音。重点听是否只是报 API 名字、是否混淆了前端消息与后台任务状态，以及是否把“当前已有”与“以后可以改”混在一起。

### 12.2 判断是否讲清楚

| 检查项 | 达标表现 |
|---|---|
| 业务动机 | 能解释为什么先拿任务 ID 再查结果 |
| 分层职责 | 能指出 Hook、SupportForm、API 客户端各做什么 |
| 状态更新 | 能举例解释函数式更新如何避免旧数组覆盖 |
| 异步机制 | 能画出慢请求下下一次轮询发生的时间 |
| 闭包问题 | 能解释回调为何可能过期、ref 如何读取最新版本 |
| 生命周期 | 能区分清 timer、忽略响应和 abort 请求 |
| 错误路径 | 能区分原任务查询重试与重新提交 |
| 验证能力 | 能说明 mock API、fake timers、act 各解决什么 |
| 实现边界 | 不把建议中的功能说成已经实现 |

这些是准备程度的自测标准，不是面试通过率保证。答不清楚的条目回到对应代码节学习，再用自己的话复述。

### 12.3 第一题模拟练习

题目：“为什么你使用递归 setTimeout，而不是 setInterval？如果单次接口请求耗时十秒，会发生什么？”

回答应包含三点：下一次请求是在上一条返回后安排的；默认五秒等待加十秒请求，首次从第 5 秒请求到第 15 秒返回，第二次约第 20 秒开始；保证的是同一有效轮询周期不因固定定时器叠加查询，不是保证接口五秒完成。
