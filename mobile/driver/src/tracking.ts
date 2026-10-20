import * as TaskManager from 'expo-task-manager';
import * as Location from 'expo-location';
import * as SQLite from 'expo-sqlite';
import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import { api, ApiError } from './api';

const TASK = 'transfrota-active-leg';
type Context = { trip: string; leg: string; since: number };
let opening: Promise<SQLite.SQLiteDatabase> | undefined;
async function db() {
  if (!opening) opening = (async () => {
    const conn = await SQLite.openDatabaseAsync('driver-gps.db');
    await conn.execAsync('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS positions (id TEXT PRIMARY KEY, trip TEXT NOT NULL, leg TEXT NOT NULL, payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS rejected_positions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, reason TEXT NOT NULL); CREATE TABLE IF NOT EXISTS pending_command (slot INTEGER PRIMARY KEY CHECK(slot=1), id TEXT NOT NULL, path TEXT NOT NULL, body TEXT NOT NULL);');
    return conn;
  })();
  return opening;
}
async function context(): Promise<Context | null> {
  const raw = await SecureStore.getItemAsync('driver-tracking');
  return raw ? JSON.parse(raw) : null;
}

// Defined outside React: native background tasks must register at module scope.
TaskManager.defineTask(TASK, async ({ data, error }) => {
  if (error) {
    await SecureStore.setItemAsync('driver-gps-error', error.message);
    return;
  }
  const current = await context();
  if (!current) return;
  const locations = (data as { locations?: Location.LocationObject[] })?.locations ?? [];
  const conn = await db();
  for (const loc of locations) {
    if (loc.timestamp < current.since || loc.coords.accuracy == null || loc.coords.accuracy < 0) continue;
    const id = Crypto.randomUUID();
    await conn.runAsync('INSERT OR IGNORE INTO positions VALUES (?, ?, ?, ?)', id, current.trip, current.leg,
      JSON.stringify({ id, measured_at: new Date(loc.timestamp).toISOString(),
        latitude: loc.coords.latitude, longitude: loc.coords.longitude, accuracy: loc.coords.accuracy }));
  }
  try { await flush(); } catch { /* retained on disk, visible pending counter */ }
});

export async function prepareGPS() {
  const foreground = await Location.requestForegroundPermissionsAsync();
  if (foreground.status !== 'granted') throw new Error('Permita a localização para registrar o percurso.');
  const background = await Location.requestBackgroundPermissionsAsync();
  if (background.status !== 'granted') throw new Error('Autorize a localização em segundo plano nas configurações do celular.');
  if (!await Location.hasServicesEnabledAsync()) throw new Error('Ative o GPS do celular.');
}

export async function startGPS(trip: string, leg: string, startedAt: string) {
  const old = await context();
  if (old && old.leg !== leg) await stopGPS();
  await SecureStore.setItemAsync('driver-tracking', JSON.stringify({trip, leg, since: Date.parse(startedAt)}));
  try {
    if (!await Location.hasStartedLocationUpdatesAsync(TASK)) {
      await Location.startLocationUpdatesAsync(TASK, {
      accuracy: Location.Accuracy.High, distanceInterval: 30, timeInterval: 15000,
      pausesUpdatesAutomatically: false, showsBackgroundLocationIndicator: true,
      foregroundService: { notificationTitle: 'BDT em deslocamento', notificationBody: 'Registrando o percurso do trecho ativo.' },
      });
    }
    await SecureStore.deleteItemAsync('driver-gps-error');
  } catch (error) {
    await SecureStore.setItemAsync('driver-gps-error', 'Trecho ativo sem coleta: use Retomar GPS e confira as permissões.');
    throw error;
  }
}

export async function stopGPS() {
  // Disable collection before stopping native task to reject late callbacks.
  await SecureStore.deleteItemAsync('driver-tracking');
  await SecureStore.deleteItemAsync('driver-gps-error');
  if (await Location.hasStartedLocationUpdatesAsync(TASK)) await Location.stopLocationUpdatesAsync(TASK);
}

let flushing = false;
export async function flush(maxBatches = 1) {
  if (flushing) return;
  flushing = true;
  try {
    const conn = await db();
    for (let batch = 0; batch < maxBatches; batch++) {
    const rows = await conn.getAllAsync<{id:string;trip:string;leg:string;payload:string}>('SELECT * FROM positions ORDER BY rowid LIMIT 200');
    if (!rows.length) return;
    const group = rows.filter(r => r.trip === rows[0].trip && r.leg === rows[0].leg);
    const result = await api('trips/'+rows[0].trip+'/legs/'+rows[0].leg+'/locations/', {points:group.map(r=>JSON.parse(r.payload))});
    for (const id of result.accepted) await conn.runAsync('DELETE FROM positions WHERE id=?', id);
    for (const rejected of result.rejected ?? []) {
      const row = group.find(r=>r.id===rejected.id);
      if (!row) continue;
      await conn.withTransactionAsync(async()=>{
        await conn.runAsync('INSERT OR IGNORE INTO rejected_positions VALUES (?, ?, ?)', row.id, row.payload, rejected.reason);
        await conn.runAsync('DELETE FROM positions WHERE id=?', row.id);
      });
    }
    }
  } finally { flushing = false; }
}

export async function gpsStatus() {
  const conn = await db();
  const count = await conn.getFirstAsync<{n:number}>('SELECT count(*) AS n FROM positions');
  const rejected = await conn.getFirstAsync<{n:number}>('SELECT count(*) AS n FROM rejected_positions');
  return {pending:count?.n ?? 0, rejected:rejected?.n ?? 0, error:await SecureStore.getItemAsync('driver-gps-error'),
    active:await Location.hasStartedLocationUpdatesAsync(TASK)};
}

// Persist a command BEFORE sending it. Retrying after a lost response uses exactly
// the same UUID and body; never allow another transition until it is resolved.
export async function command(path: string, body: unknown) {
  const conn = await db();
  const existing = await pendingCommand();
  if (existing) throw new Error('Existe uma operação pendente. Use Sincronizar antes de continuar.');
  await conn.runAsync('INSERT INTO pending_command VALUES (1, ?, ?, ?)', Crypto.randomUUID(), path, JSON.stringify(body));
  return retryCommand();
}
export async function pendingCommand() {
  return (await db()).getFirstAsync<{id:string;path:string;body:string}>('SELECT * FROM pending_command WHERE slot=1');
}
export async function retryCommand() {
  const conn = await db();
  const row = await pendingCommand();
  if (!row) return null;
  try {
    const result = await api(row.path, JSON.parse(row.body), row.id);
    await conn.runAsync('DELETE FROM pending_command WHERE slot=1 AND id=?', row.id);
    return result;
  } catch (error) {
    // Validation/authorization failure is definitive: no transition was committed.
    if (error instanceof ApiError && [400,403,404,409].includes(error.status)) {
      await conn.runAsync('DELETE FROM pending_command WHERE slot=1 AND id=?', row.id);
    }
    throw error;
  }
}
