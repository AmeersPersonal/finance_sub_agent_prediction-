// Shared UI state: which toggletip is open, learning mode, and theme.
import { createContext, useContext } from 'react';

export const UIContext = createContext(null);

export function useUI() {
  return useContext(UIContext);
}
