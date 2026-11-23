import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Navigate, NavLink, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api/client";
import { ME_KEY, RequireAuth, UnauthorizedBridge, useMe } from "./auth";
import { hasRole, roleLabel } from "./lib/roles";
import { BrowsePage } from "./pages/BrowsePage";
import { JourneyPage } from "./pages/JourneyPage";
import { LoginPage } from "./pages/LoginPage";
import { PlatesPage } from "./pages/PlatesPage";
import { SearchStateProvider } from "./searchState";

// route ฝั่งเว็บต้องไม่ขึ้นต้นด้วย /auth /search /sightings /journeys /cameras (เป็นของ API)

function Layout() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const logout = useMutation({
    mutationFn: api.logout,
    onSettled: () => {
      qc.clear();
      qc.setQueryData(ME_KEY, null);
      navigate("/login", { replace: true });
    },
  });
  const investigator = hasRole(me?.role, "investigator");

  return (
    <>
      <a href="#main" className="skip-link">
        ข้ามไปเนื้อหาหลัก
      </a>
      <header className="topbar">
        <div className="topbar__inner">
          <span className="brand">ค้นหารถในอาคาร</span>
          <nav aria-label="เมนูหลัก">
            <ul>
              {investigator ? (
                <li>
                  <NavLink to="/plates">ค้นหาป้าย</NavLink>
                </li>
              ) : null}
              <li>
                <NavLink to="/browse">ดูรายการรถ</NavLink>
              </li>
            </ul>
          </nav>
          {me ? (
            <div className="user">
              <span className="user__name">
                {me.username} <span className="muted">({roleLabel(me.role)})</span>
              </span>
              <button type="button" className="btn btn--ghost btn--small" onClick={() => logout.mutate()} disabled={logout.isPending}>
                ออกจากระบบ
              </button>
            </div>
          ) : null}
        </div>
      </header>
      <main id="main" className="container" tabIndex={-1}>
        {/* key ตามผู้ใช้: ออกจากระบบแล้วเข้าใหม่ ฟอร์มและผลค้นเดิมหายไป */}
        <SearchStateProvider key={me?.username ?? ""}>
          <Outlet />
        </SearchStateProvider>
      </main>
      <footer className="footer container">
        <small>เวลาทั้งหมดเป็นเวลาไทย (UTC+7) · ทุกการค้นหาและการเปิดภาพถูกบันทึกไว้ในบันทึกการเข้าถึง</small>
      </footer>
    </>
  );
}

function Home() {
  const { data: me } = useMe();
  return <Navigate to={hasRole(me?.role, "investigator") ? "/plates" : "/browse"} replace />;
}

function NotFound() {
  return (
    <>
      <h1>ไม่พบหน้านี้</h1>
      <p>
        <NavLink to="/">กลับหน้าแรก</NavLink>
      </p>
    </>
  );
}

export function App() {
  return (
    <>
      <UnauthorizedBridge />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Home />} />
          <Route
            path="plates"
            element={
              <RequireAuth min="investigator">
                <PlatesPage />
              </RequireAuth>
            }
          />
          <Route path="browse" element={<BrowsePage />} />
          <Route
            path="journey/:id"
            element={
              <RequireAuth min="investigator">
                <JourneyPage />
              </RequireAuth>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </>
  );
}
