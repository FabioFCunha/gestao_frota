export type Check = { status: ''|'ok'|'problem'|'na'; note: string };
export type Checklist = Record<string, Check>;
export type Leg = { id:string; position:number; destination:string; started_at:string|null; ended_at:string|null;
  started_km:number|null; ended_km:number|null; distance_km:number|null; duration_seconds:number|null };
export type Trip = { id:string; vehicle:string; opened_at:string; closed_at:string|null; legs:Leg[] };
export type Bootstrap = { name:string; company:string; role:string; checklist_items:string[];
  vehicles:{id:number;label:string;suggested_km:number|null}[]; active_trip:Trip|null };
