import { create } from 'zustand'

interface UiState {
  shortcutsOpen: boolean
  setShortcutsOpen: (open: boolean) => void
  lastSceneId: string | null
  setLastSceneId: (id: string | null) => void
  lastRunId: string | null
  setLastRunId: (id: string | null) => void
}

export const useUi = create<UiState>((set) => ({
  shortcutsOpen: false,
  setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
  lastSceneId: null,
  setLastSceneId: (lastSceneId) => set({ lastSceneId }),
  lastRunId: null,
  setLastRunId: (lastRunId) => set({ lastRunId }),
}))
