import { useEffect, useId, useRef, useState } from "react";

import type { TodoList, TodoStatus } from "@/entities/todo/model/todo-list";
import {
  TODO_NAVIGATION_EVENT,
  navigateToCotStep,
  todoItemDomId,
  type TodoNavigationDetail,
} from "@/features/chat/model/cot-navigation";

interface TodoPanelProps {
  readonly todoList: TodoList;
  readonly sourceStepId?: string;
}

const STATUS_LABEL: Record<TodoStatus, string> = {
  pending: "未开始",
  in_progress: "进行中",
  completed: "已完成",
};

function itemKey(content: string, index: number): string {
  return `${index}:${content}`;
}

export function TodoPanel({ todoList, sourceStepId }: TodoPanelProps) {
  const [collapsed, setCollapsed] = useState(true);
  const [highlightedIndex, setHighlightedIndex] = useState<number | null>(null);
  const contentId = useId();
  const listRef = useRef<HTMLOListElement | null>(null);
  const previousStatusesRef = useRef(
    new Map(
      todoList.items.map((todo, index) => [
        itemKey(todo.content, index),
        todo.status,
      ]),
    ),
  );
  const updateTimerRef = useRef<number | null>(null);
  const highlightTimerRef = useRef<number | null>(null);
  const completedCount = todoList.items.filter(
    (item) => item.status === "completed",
  ).length;

  useEffect(() => {
    const nextStatuses = new Map(
      todoList.items.map((todo, index) => [
        itemKey(todo.content, index),
        todo.status,
      ]),
    );
    const changedIndexes: number[] = [];
    todoList.items.forEach((todo, index) => {
      const key = itemKey(todo.content, index);
      const status = nextStatuses.get(key);
      if (previousStatusesRef.current.get(key) !== status) {
        changedIndexes.push(index);
      }
    });
    previousStatusesRef.current = nextStatuses;
    if (changedIndexes.length === 0) {
      return;
    }
    for (const index of changedIndexes) {
      const element = listRef.current?.querySelector<HTMLElement>(
        `[data-todo-index="${index}"]`,
      );
      if (element !== undefined && element !== null) {
        element.dataset.updated = "false";
        void element.offsetWidth;
        element.dataset.updated = "true";
      }
    }
    if (updateTimerRef.current !== null) {
      window.clearTimeout(updateTimerRef.current);
    }
    updateTimerRef.current = window.setTimeout(() => {
      listRef.current
        ?.querySelectorAll<HTMLElement>('[data-updated="true"]')
        .forEach((element) => {
          element.dataset.updated = "false";
        });
    }, 700);
  }, [todoList.items]);

  useEffect(() => {
    if (sourceStepId === undefined) {
      return;
    }
    const handleNavigation = (event: Event) => {
      const detail = (event as CustomEvent<TodoNavigationDetail>).detail;
      if (detail.sourceStepId !== sourceStepId) {
        return;
      }
      const fallbackIndex = todoList.items.findIndex(
        (todo) => todo.status === "in_progress",
      );
      const targetIndex =
        detail.todoIndex ?? (fallbackIndex >= 0 ? fallbackIndex : 0);
      setCollapsed(false);
      setHighlightedIndex(targetIndex);
      if (highlightTimerRef.current !== null) {
        window.clearTimeout(highlightTimerRef.current);
      }
      window.setTimeout(() => {
        document
          .getElementById(todoItemDomId(sourceStepId, targetIndex))
          ?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
      }, 0);
      highlightTimerRef.current = window.setTimeout(
        () => setHighlightedIndex(null),
        1400,
      );
    };
    window.addEventListener(TODO_NAVIGATION_EVENT, handleNavigation);
    return () =>
      window.removeEventListener(TODO_NAVIGATION_EVENT, handleNavigation);
  }, [sourceStepId, todoList.items]);

  useEffect(
    () => () => {
      if (updateTimerRef.current !== null) {
        window.clearTimeout(updateTimerRef.current);
      }
      if (highlightTimerRef.current !== null) {
        window.clearTimeout(highlightTimerRef.current);
      }
    },
    [],
  );

  return (
    <section className="todo-panel" aria-label="任务清单">
      <button
        type="button"
        className="todo-panel__header"
        aria-expanded={!collapsed}
        aria-controls={contentId}
        onClick={() => setCollapsed((current) => !current)}
      >
        <span className="todo-panel__title">
          <span aria-hidden="true">☷</span>
          Todos
        </span>
        <span className="todo-panel__progress">
          {completedCount}/{todoList.items.length}
        </span>
        <span
          className="todo-panel__chevron"
          data-collapsed={collapsed}
          aria-hidden="true"
        >
          ⌃
        </span>
      </button>
      <div id={contentId} className="todo-panel__body" hidden={collapsed}>
        <ol ref={listRef} className="todo-panel__list">
          {todoList.items.map((todo, index) => {
            const key = itemKey(todo.content, index);
            const content = (
              <>
                <span className="todo-panel__indicator" aria-hidden="true" />
                <span className="todo-panel__content">{todo.content}</span>
                <span className="visually-hidden">
                  {STATUS_LABEL[todo.status]}
                </span>
              </>
            );
            return (
              <li
                key={key}
                id={
                  sourceStepId === undefined
                    ? undefined
                    : todoItemDomId(sourceStepId, index)
                }
                data-status={todo.status}
                data-todo-index={index}
                data-updated="false"
                data-highlighted={highlightedIndex === index}
              >
                {sourceStepId === undefined ? (
                  content
                ) : (
                  <button
                    type="button"
                    className="todo-panel__item-link"
                    title="定位到对应 COT 步骤"
                    onClick={() => navigateToCotStep(sourceStepId)}
                  >
                    {content}
                    <span className="todo-panel__locate" aria-hidden="true">
                      ↖
                    </span>
                  </button>
                )}
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
