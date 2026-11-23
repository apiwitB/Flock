const RANK: Record<string, number> = { viewer: 1, investigator: 2, admin: 3 };

export const ROLE_LABELS: Record<string, string> = {
  viewer: "ผู้ดู",
  investigator: "ผู้สอบสวน",
  admin: "ผู้ดูแลระบบ",
};

/** บทบาทที่ไม่รู้จักถือว่าไม่มีสิทธิ์ */
export function hasRole(role: string | null | undefined, minimum: "viewer" | "investigator" | "admin"): boolean {
  if (!role) return false;
  return (RANK[role] ?? 0) >= RANK[minimum]!;
}

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}
