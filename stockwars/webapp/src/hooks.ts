import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
export function useLoad<T>(path: string) {
  const [data, set] = useState<T | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => { api<T>(path).then(set).catch((e) => setErr(e.message)); }, [path]);
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);
  return { data, err, reload: load };
}
