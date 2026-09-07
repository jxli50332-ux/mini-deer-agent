/** 项目是独立持久身份；文件工具可在项目根内读写。 */
export interface ProjectSummary {
  readonly projectId: string;
  readonly name: string;
  readonly rootPath: string;
  readonly accessMode: "read_write";
  readonly status: "available" | "missing" | "unavailable" | "changed";
  readonly statusReason: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

/** 一页项目记录；null 表示当前查询没有下一页。 */
export interface ProjectPage {
  readonly items: readonly ProjectSummary[];
  readonly nextOffset: number | null;
}

/** 表示传输数据无法成为可信产品状态，不回显未知正文。 */
export class ProjectPayloadError extends Error {}

/** 校验未知对象，避免直接断言服务端 JSON 的类型。 */
function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ProjectPayloadError();
  }
  return value as Record<string, unknown>;
}

/** 只接受长度受限的字符串，防止异常元数据进入页面。 */
function text(
  record: Record<string, unknown>,
  key: string,
  max: number,
): string {
  const value = record[key];
  if (typeof value !== "string" || value.length < 1 || value.length > max) {
    throw new ProjectPayloadError();
  }
  return value;
}

/** 时间必须来自有效 ISO 日期，不能将 Swagger 占位字符串作为实际结果。 */
function timestamp(record: Record<string, unknown>, key: string): string {
  const value = text(record, key, 64);
  if (!/^\d{4}-\d{2}-\d{2}T/.test(value) || Number.isNaN(Date.parse(value))) {
    throw new ProjectPayloadError();
  }
  return value;
}

/** 在 HTTP 边界验证身份、权限与状态，UI 不根据缺失字段猜测成功。 */
export function parseProject(value: unknown): ProjectSummary {
  const record = asRecord(value);
  const projectId = text(record, "project_id", 36).toLowerCase();
  if (
    !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(projectId) ||
    record.access_mode !== "read_write" ||
    (record.status !== "available" &&
      record.status !== "missing" &&
      record.status !== "unavailable" &&
      record.status !== "changed") ||
    (record.status_reason !== null &&
      (typeof record.status_reason !== "string" ||
        record.status_reason.length > 100))
  ) {
    throw new ProjectPayloadError();
  }
  return {
    projectId,
    name: text(record, "name", 80),
    rootPath: text(record, "root_path", 4096),
    accessMode: record.access_mode,
    status: record.status,
    statusReason: record.status_reason,
    createdAt: timestamp(record, "created_at"),
    updatedAt: timestamp(record, "updated_at"),
  };
}

/** 续页必须前进且页面内部不能重复身份，避免无限翻页或错误合并。 */
export function parseProjectPage(value: unknown, offset: number): ProjectPage {
  const record = asRecord(value);
  if (!Array.isArray(record.items) || record.items.length > 20)
    throw new ProjectPayloadError();
  const items = record.items.map(parseProject);
  const nextOffset = record.next_offset;
  if (
    new Set(items.map((item) => item.projectId)).size !== items.length ||
    (nextOffset !== null &&
      (typeof nextOffset !== "number" ||
        !Number.isSafeInteger(nextOffset) ||
        nextOffset <= offset ||
        nextOffset > 10000 ||
        items.length === 0))
  ) {
    throw new ProjectPayloadError();
  }
  return { items, nextOffset };
}
