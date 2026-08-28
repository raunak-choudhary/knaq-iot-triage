"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useSyncExternalStore,
} from "react";
import { ThemeProvider } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";
import { Provider as ReduxProvider } from "react-redux";
import { store } from "@/lib/store";
import { getTheme } from "@/lib/theme";
import { AppToastProvider } from "@/components/ui/AppToast";

const STORAGE_KEY = "knaq-theme-mode";

type ColorMode = "light" | "dark";

// localStorage is an external store, so the theme is read through
// useSyncExternalStore rather than mirrored into component state. The server
// snapshot keeps SSR and the first client render in agreement.
const themeListeners = new Set<() => void>();

function subscribeToStoredMode(onStoreChange: () => void): () => void {
  themeListeners.add(onStoreChange);
  window.addEventListener("storage", onStoreChange);
  return () => {
    themeListeners.delete(onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

function getStoredMode(): ColorMode {
  return localStorage.getItem(STORAGE_KEY) === "dark" ? "dark" : "light";
}

function getServerMode(): ColorMode {
  return "light";
}

function writeStoredMode(next: ColorMode): void {
  localStorage.setItem(STORAGE_KEY, next);
  themeListeners.forEach((listener) => listener());
}

interface ColorModeContextValue {
  mode: ColorMode;
  toggleColorMode: () => void;
}

export const ColorModeContext = createContext<ColorModeContextValue>({
  mode: "light",
  toggleColorMode: () => undefined,
});

export function useColorMode(): ColorModeContextValue {
  return useContext(ColorModeContext);
}

export function Providers({ children }: { children: React.ReactNode }) {
  const mode = useSyncExternalStore(
    subscribeToStoredMode,
    getStoredMode,
    getServerMode
  );

  const toggleColorMode = useCallback(() => {
    writeStoredMode(getStoredMode() === "light" ? "dark" : "light");
  }, []);

  const colorModeValue = useMemo(
    () => ({ mode, toggleColorMode }),
    [mode, toggleColorMode]
  );

  const theme = useMemo(() => getTheme(mode), [mode]);

  return (
    <ColorModeContext.Provider value={colorModeValue}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <ReduxProvider store={store}>
          <AppToastProvider>{children}</AppToastProvider>
        </ReduxProvider>
      </ThemeProvider>
    </ColorModeContext.Provider>
  );
}
