export const COT_NAVIGATION_EVENT = "mini-deer:navigate-to-cot";
export const TODO_NAVIGATION_EVENT = "mini-deer:navigate-to-todo";

export interface CotNavigationDetail {
  readonly stepId: string;
}

export interface TodoNavigationDetail {
  readonly sourceStepId: string;
  readonly todoIndex?: number;
}

export function cotStepDomId(stepId: string): string {
  return `cot-step:${stepId}`;
}

export function todoItemDomId(sourceStepId: string, index: number): string {
  return `todo-item:${sourceStepId}:${index}`;
}

export function navigateToCotStep(stepId: string): void {
  window.dispatchEvent(
    new CustomEvent<CotNavigationDetail>(COT_NAVIGATION_EVENT, {
      detail: { stepId },
    }),
  );
}

export function navigateToTodo(sourceStepId: string, todoIndex?: number): void {
  window.dispatchEvent(
    new CustomEvent<TodoNavigationDetail>(TODO_NAVIGATION_EVENT, {
      detail: {
        sourceStepId,
        ...(todoIndex === undefined ? {} : { todoIndex }),
      },
    }),
  );
}
