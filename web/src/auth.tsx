import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api, setUnauthorizedHandler } from "./api/client";
import type { User } from "./api/types";
import { Forbidden } from "./components/ErrorMessage";
import { hasRole, roleLabel } from "./lib/roles";

export const ME_KEY = ["me"] as const;

export function useMe() {
  return useQuery({ queryKey: ME_KEY, queryFn: api.me, staleTime: 60_000, retry: false });
}

/** รับสัญญาณ 401 จาก API client: ล้างผู้ใช้ปัจจุบัน แล้ว RequireAuth จะพาไปหน้าเข้าสู่ระบบ */
export function UnauthorizedBridge() {
  const qc = useQueryClient();
  useEffect(
    () =>
      setUnauthorizedHandler(() => {
        qc.setQueryData<User | null>(ME_KEY, null);
      }),
    [qc],
  );
  return null;
}

export function RequireAuth({ children, min }: { children: ReactNode; min?: "viewer" | "investigator" | "admin" }) {
  const { data: user, isPending, isError } = useMe();
  const location = useLocation();
  if (isPending) return <p className="loading">กำลังตรวจสอบการเข้าสู่ระบบ…</p>;
  if (isError) {
    return (
      <div className="alert alert--error" role="alert">
        ติดต่อเซิร์ฟเวอร์ไม่ได้ กรุณาลองใหม่อีกครั้ง
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (min && !hasRole(user.role, min)) return <Forbidden need={roleLabel(min)} />;
  return <>{children}</>;
}
