import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      // ทุกคำค้นถูกบันทึกใน audit log: ไม่ดึงซ้ำเองเมื่อสลับหน้าต่าง
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");

// ไม่ใช้ StrictMode: ใน dev มันรัน effect ซ้ำ ทำให้โหลดภาพสองครั้งและเกิดรายการ audit log ซ้ำ
createRoot(root).render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>,
);
