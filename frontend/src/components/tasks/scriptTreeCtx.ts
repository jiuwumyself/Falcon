import type { InjectionKey, Ref } from 'vue'
import type { Task } from '@/types/task'

export interface ScriptTreeCtx {
  searchQuery: Ref<string>
  expandTrigger: Ref<number>
  collapseTrigger: Ref<number>
  // Path of the last row whose save failed — ComponentNode uses this to flash
  // that row red briefly (800 ms). null when no failure pending.
  errorFlashPath: Ref<string | null>
  // Paths that should be auto-expanded the first time their ComponentNode
  // mounts (e.g. the ancestors of any <CSVDataSet> node so the inline "upload
  // CSV" button is always visible regardless of default 3-level limit).
  forceExpandPaths: Ref<Set<string>>
  // Current task — needed by CSVDataSet inline upload button (binding lookup).
  task: Ref<Task>
  // Intra-row action: upload a CSV for the CSVDataSet at `componentPath`.
  // Returns the updated Task so the tree can refresh csv_bindings.
  uploadCsv: (componentPath: string, file: File) => Promise<Task>
}

export const SCRIPT_TREE_CTX: InjectionKey<ScriptTreeCtx> = Symbol('SCRIPT_TREE_CTX')
