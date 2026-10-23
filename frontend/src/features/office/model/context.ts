import { createContext, useContext } from "react";
import type { OfficeDocument } from "@/features/office/api/documents";

export interface OfficeDocumentsContextValue {
  readonly documents: readonly OfficeDocument[];
  readonly openDocument: (filename: string) => void;
  readonly openTextFile: (path: string, projectId?: string) => void;
  readonly projectId: string | null;
  readonly openLibrary: () => void;
}

export const OfficeDocumentsContext =
  createContext<OfficeDocumentsContextValue | null>(null);
export function useOfficeDocuments(): OfficeDocumentsContextValue | null {
  return useContext(OfficeDocumentsContext);
}
