import { useCallback, useEffect, useRef, useState } from "react";

import {
  clearThreadGoal,
  fetchThreadGoal,
  setThreadGoal,
  stopThreadGoal,
  type GoalClearer,
  type GoalLoader,
  type GoalSetter,
  type GoalStopper,
  type ThreadGoal,
} from "@/features/goals/api/thread-goal";

export interface UseThreadGoalOptions {
  readonly loader?: GoalLoader;
  readonly setter?: GoalSetter;
  readonly stopper?: GoalStopper;
  readonly clearer?: GoalClearer;
}

export interface UseThreadGoalResult {
  readonly goal: ThreadGoal | null;
  readonly isLoading: boolean;
  readonly isMutating: boolean;
  readonly error: string | null;
  readonly retry: () => void;
  readonly setGoal: (
    objective: string,
    maxContinuations: number,
  ) => Promise<boolean>;
  readonly stopGoal: () => Promise<boolean>;
  readonly clearGoal: () => Promise<boolean>;
}

interface GoalViewState {
  readonly threadId: string;
  readonly goal: ThreadGoal | null;
  readonly isLoading: boolean;
  readonly isMutating: boolean;
  readonly error: string | null;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Goal 操作失败";
}

export function useThreadGoal(
  threadId: string,
  options: UseThreadGoalOptions = {},
): UseThreadGoalResult {
  const loader = options.loader ?? fetchThreadGoal;
  const setter = options.setter ?? setThreadGoal;
  const stopper = options.stopper ?? stopThreadGoal;
  const clearer = options.clearer ?? clearThreadGoal;
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<GoalViewState>(() => ({
    threadId,
    goal: null,
    isLoading: true,
    isMutating: false,
    error: null,
  }));
  const generationRef = useRef(0);
  const loaderAbortRef = useRef<AbortController | null>(null);
  const mutationInFlightRef = useRef(false);
  const refreshAfterMutationRef = useRef(false);

  useEffect(() => {
    generationRef.current += 1;
    const generation = generationRef.current;
    const controller = new AbortController();
    loaderAbortRef.current?.abort();
    loaderAbortRef.current = controller;
    setState((current) =>
      current.threadId === threadId
        ? {
            ...current,
            isLoading: true,
            isMutating: false,
            error: null,
          }
        : {
            threadId,
            goal: null,
            isLoading: true,
            isMutating: false,
            error: null,
          },
    );
    void loader({ threadId, signal: controller.signal }).then(
      (goal) => {
        if (controller.signal.aborted || generation !== generationRef.current)
          return;
        setState({
          threadId,
          goal,
          isLoading: false,
          isMutating: false,
          error: null,
        });
      },
      (error: unknown) => {
        if (controller.signal.aborted || generation !== generationRef.current)
          return;
        setState((current) =>
          current.threadId === threadId
            ? {
                ...current,
                isLoading: false,
                isMutating: false,
                error: errorMessage(error),
              }
            : {
                threadId,
                goal: null,
                isLoading: false,
                isMutating: false,
                error: errorMessage(error),
              },
        );
      },
    );
    return () => {
      controller.abort();
      if (loaderAbortRef.current === controller) loaderAbortRef.current = null;
    };
  }, [loader, revision, threadId]);

  const retry = useCallback(() => {
    if (mutationInFlightRef.current) {
      refreshAfterMutationRef.current = true;
      return;
    }
    setRevision((current) => current + 1);
  }, []);

  const mutate = useCallback(
    async (operation: () => Promise<ThreadGoal | null>): Promise<boolean> => {
      if (mutationInFlightRef.current) return false;
      mutationInFlightRef.current = true;
      generationRef.current += 1;
      const generation = generationRef.current;
      loaderAbortRef.current?.abort();
      setState((current) =>
        current.threadId === threadId
          ? { ...current, isMutating: true, error: null }
          : current,
      );
      try {
        const goal = await operation();
        if (generation !== generationRef.current) return false;
        setState({
          threadId,
          goal,
          isLoading: false,
          isMutating: false,
          error: null,
        });
        return true;
      } catch (error) {
        if (generation !== generationRef.current) return false;
        setState((current) => ({
          ...(current.threadId === threadId
            ? current
            : { threadId, goal: null, isLoading: false }),
          isMutating: false,
          error: errorMessage(error),
        }));
        return false;
      } finally {
        mutationInFlightRef.current = false;
        if (refreshAfterMutationRef.current) {
          refreshAfterMutationRef.current = false;
          setRevision((current) => current + 1);
        }
      }
    },
    [threadId],
  );

  const setGoal = useCallback(
    (objective: string, maxContinuations: number) => {
      const current =
        state.threadId === threadId ? state.goal?.revision : undefined;
      return mutate(() =>
        setter({
          threadId,
          objective,
          maxContinuations,
          ...(current === undefined ? {} : { expectedRevision: current }),
        }),
      );
    },
    [mutate, setter, state.goal?.revision, state.threadId, threadId],
  );
  const stopGoal = useCallback(() => {
    const revision = state.threadId === threadId ? state.goal?.revision : null;
    if (revision === null || revision === undefined)
      return Promise.resolve(false);
    return mutate(() => stopper({ threadId, revision }));
  }, [mutate, state.goal?.revision, state.threadId, stopper, threadId]);
  const clearGoal = useCallback(() => {
    const revision = state.threadId === threadId ? state.goal?.revision : null;
    if (revision === null || revision === undefined)
      return Promise.resolve(false);
    return mutate(async () => {
      await clearer({ threadId, revision });
      return null;
    });
  }, [clearer, mutate, state.goal?.revision, state.threadId, threadId]);

  return state.threadId === threadId
    ? { ...state, retry, setGoal, stopGoal, clearGoal }
    : {
        goal: null,
        isLoading: true,
        isMutating: false,
        error: null,
        retry,
        setGoal,
        stopGoal,
        clearGoal,
      };
}
