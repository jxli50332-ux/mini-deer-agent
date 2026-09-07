export type ThreadStatus = "idle" | "busy" | "error";

/** 表示服务端最近会话列表公开的稳定 Thread 元数据。 */
export interface ThreadSummary {
  readonly threadId: string;
  readonly title: string | null;
  readonly status: ThreadStatus;
  readonly projectId: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}
