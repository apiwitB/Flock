import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { api, UnauthorizedError } from "../api/client";
import { ME_KEY, useMe } from "../auth";
import { errorText } from "../components/ErrorMessage";

function safeFrom(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from;
  // อนุญาตเฉพาะ path ภายในแอป
  return typeof from === "string" && from.startsWith("/") && !from.startsWith("//") && from !== "/login" ? from : "/";
}

export function LoginPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const { data: me } = useMe();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const errorRef = useRef<HTMLDivElement>(null);

  const login = useMutation({
    mutationFn: () => api.login(username.trim(), password),
    onSuccess: (user) => {
      qc.clear();
      qc.setQueryData(ME_KEY, user);
      navigate(safeFrom(location.state), { replace: true });
    },
    onError: () => setPassword(""),
  });

  useEffect(() => {
    if (login.isError) errorRef.current?.focus();
  }, [login.isError]);

  if (me) return <Navigate to={safeFrom(location.state)} replace />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    login.mutate();
  };

  return (
    <main className="login" id="main">
      <form className="card login__card" onSubmit={onSubmit} noValidate={false}>
        <h1>เข้าสู่ระบบ</h1>
        <p className="muted">ระบบค้นหารถในอาคารจอดรถ ทุกการค้นหาและการเปิดภาพถูกบันทึกไว้</p>
        {login.isError ? (
          <div className="alert alert--error" role="alert" tabIndex={-1} ref={errorRef}>
            {login.error instanceof UnauthorizedError ? "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง" : errorText(login.error)}
          </div>
        ) : null}
        <div className="field">
          <label htmlFor="username">ชื่อผู้ใช้</label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            maxLength={64}
            autoFocus
            spellCheck={false}
            autoCapitalize="none"
          />
        </div>
        <div className="field">
          <label htmlFor="password">รหัสผ่าน</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            maxLength={256}
          />
        </div>
        <button type="submit" className="btn btn--primary" disabled={login.isPending}>
          {login.isPending ? "กำลังเข้าสู่ระบบ…" : "เข้าสู่ระบบ"}
        </button>
      </form>
    </main>
  );
}
