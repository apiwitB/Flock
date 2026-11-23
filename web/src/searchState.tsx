import { createContext, useContext, useState, type ReactNode } from "react";
import type { BrowseParams, PlateSearchParams } from "./api/types";
import { defaultRange } from "./lib/time";

// เก็บฟอร์มและคำค้นล่าสุดไว้ในหน่วยความจำ เพื่อให้กดกลับจากหน้าเส้นทางแล้วผลยังอยู่
// ไม่ใส่เลขป้ายใน URL/ประวัติเบราว์เซอร์ และหายเมื่อรีเฟรชหรือออกจากระบบ

export interface PlateForm {
  q: string;
  from: string;
  to: string;
  camera_id: string;
  province: string;
  max_distance: number;
  limit: number;
}

export interface BrowseForm {
  from: string;
  to: string;
  camera_id: string;
  color: string;
  vehicle_type: string;
  limit: number;
}

interface State {
  plateForm: PlateForm;
  setPlateForm: (f: PlateForm) => void;
  plateQuery: PlateSearchParams | null;
  setPlateQuery: (q: PlateSearchParams | null) => void;
  browseForm: BrowseForm;
  setBrowseForm: (f: BrowseForm) => void;
  browseQuery: BrowseParams | null;
  setBrowseQuery: (q: BrowseParams | null) => void;
}

const Ctx = createContext<State | null>(null);

export function SearchStateProvider({ children }: { children: ReactNode }) {
  const [plateForm, setPlateForm] = useState<PlateForm>(() => ({
    q: "",
    ...defaultRange(),
    camera_id: "",
    province: "",
    max_distance: 2,
    limit: 100,
  }));
  const [plateQuery, setPlateQuery] = useState<PlateSearchParams | null>(null);
  const [browseForm, setBrowseForm] = useState<BrowseForm>(() => ({
    ...defaultRange(),
    camera_id: "",
    color: "",
    vehicle_type: "",
    limit: 100,
  }));
  const [browseQuery, setBrowseQuery] = useState<BrowseParams | null>(null);
  return (
    <Ctx.Provider value={{ plateForm, setPlateForm, plateQuery, setPlateQuery, browseForm, setBrowseForm, browseQuery, setBrowseQuery }}>
      {children}
    </Ctx.Provider>
  );
}

export function useSearchState(): State {
  const s = useContext(Ctx);
  if (!s) throw new Error("SearchStateProvider missing");
  return s;
}
