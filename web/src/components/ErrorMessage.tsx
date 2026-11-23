import { ApiError, ForbiddenError, NotFoundError, UnauthorizedError } from "../api/client";

/** ข้อความผิดพลาดภาษาไทยจาก error ใดๆ */
export function errorText(error: unknown): string {
  if (error instanceof ForbiddenError) {
    return "บัญชีของคุณไม่มีสิทธิ์ใช้งานส่วนนี้ หากจำเป็นต้องใช้ โปรดติดต่อผู้ดูแลระบบเพื่อขอสิทธิ์";
  }
  if (error instanceof UnauthorizedError) return "หมดเวลาการเข้าสู่ระบบ กรุณาเข้าสู่ระบบใหม่";
  if (error instanceof NotFoundError) return "ไม่พบข้อมูลที่ต้องการ";
  if (error instanceof ApiError) return error.message;
  return "เกิดข้อผิดพลาดที่ไม่คาดคิด";
}

export function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className={`alert ${error instanceof ForbiddenError ? "alert--forbidden" : "alert--error"}`} role="alert">
      {errorText(error)}
    </div>
  );
}

export function Forbidden({ need }: { need: string }) {
  return (
    <div className="alert alert--forbidden" role="alert">
      <strong>ไม่มีสิทธิ์เข้าถึง</strong> หน้านี้ต้องใช้บทบาท{need}ขึ้นไป โปรดติดต่อผู้ดูแลระบบหากจำเป็นต้องใช้
    </div>
  );
}
