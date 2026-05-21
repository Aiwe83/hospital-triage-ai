import { create } from "zustand";

type UiState = {
  presentationMode: boolean;
  intakeWidth: number;
  sidebarWidth: number;
  timelineHeight: number;
  togglePresentationMode: () => void;
  setIntakeWidth: (px: number) => void;
  setSidebarWidth: (px: number) => void;
  setTimelineHeight: (px: number) => void;
};

const clamp = (v: number, min: number, max: number) =>
  Math.max(min, Math.min(max, v));

export const useUiStore = create<UiState>((set, get) => ({
  presentationMode: false,
  intakeWidth: 360,
  sidebarWidth: 420,
  timelineHeight: 224,
  togglePresentationMode: () => set({ presentationMode: !get().presentationMode }),
  setIntakeWidth: (px) => set({ intakeWidth: clamp(px, 220, 640) }),
  setSidebarWidth: (px) => set({ sidebarWidth: clamp(px, 280, 720) }),
  setTimelineHeight: (px) => set({ timelineHeight: clamp(px, 120, 720) }),
}));
