import { useEffect, useState } from "react";

const currentOnlineState = () =>
  typeof navigator === "undefined"
    ? true
    : navigator.onLine;

export function useNetworkStatus() {
  const [isOnline, setIsOnline] = useState(
    currentOnlineState
  );

  useEffect(() => {
    const online = () => setIsOnline(true);
    const offline = () => setIsOnline(false);

    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);

  return isOnline;
}
