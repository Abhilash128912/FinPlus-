import { useEffect, useRef, useState } from "react";
import { AppState } from "react-native";
import * as Updates from "expo-updates";

// Over-the-air updates (EAS Update, free plan). A new JavaScript bundle published for this build's
// runtime version is downloaded when the app opens (and when it returns to the foreground after a
// while) and applied immediately -- no APK to copy or install. Native changes (new permissions,
// new native modules) still need a new APK and a bumped runtime version.
const RECHECK_AFTER_MS = 10 * 60 * 1000;

export type UpdateState = "idle" | "checking" | "installing";

export const updateInfo = (): string => {
  if (!Updates.isEnabled) return "Updates: off (development build)";
  const id = Updates.updateId ? Updates.updateId.slice(0, 8) : "embedded";
  return `Updates: on \u00b7 channel ${Updates.channel ?? "n/a"} \u00b7 build ${id}`;
};

export function useAutoUpdate(): UpdateState {
  const [state, setState] = useState<UpdateState>("idle");
  const lastCheck = useRef(0);
  const busy = useRef(false);

  const run = async () => {
    if (__DEV__ || !Updates.isEnabled || busy.current) return;
    busy.current = true;
    lastCheck.current = Date.now();
    try {
      setState("checking");
      const res = await Updates.checkForUpdateAsync();
      if (res.isAvailable) {
        setState("installing");
        const fetched = await Updates.fetchUpdateAsync();
        if (fetched.isNew) {
          await Updates.reloadAsync();
          return;
        }
      }
    } catch (_) {
      // offline / server asleep: keep running the bundle we already have
    } finally {
      busy.current = false;
      setState("idle");
    }
  };

  useEffect(() => {
    run();
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active" && Date.now() - lastCheck.current > RECHECK_AFTER_MS) run();
    });
    return () => sub.remove();
  }, []);

  return state;
}
