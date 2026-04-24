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
  // Current task — needed by CSVDataSet inline upload button (calls
  // /tasks/:id/upload-csv/) and potentially other intra-row actions.
  task: Ref<Task>
  // Intra-row action: upload a CSV for this task. Returns the updated Task
  // (so the header bar refreshes csv_filename).
  uploadCsv: (file: File) => Promise<Task>
}

export const SCRIPT_TREE_CTX: InjectionKey<ScriptTreeCtx> = Symbol('SCRIPT_TREE_CTX')
