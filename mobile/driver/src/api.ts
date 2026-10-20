import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
export const API = process.env.EXPO_PUBLIC_API_URL ?? '';
export async function token() { return SecureStore.getItemAsync('driver-token'); }
export async function saveToken(value: string) { await SecureStore.setItemAsync('driver-token', value); }
export async function forgetToken() { await SecureStore.deleteItemAsync('driver-token'); }

export async function api(path: string, data?: unknown, id?: string): Promise<any> {
  if (!API.startsWith('https://') || !API.endsWith('/api/driver/')) {
    throw new Error('Configure uma API HTTPS de homologação terminada em /api/driver/.');
  }
  const bearer = await token();
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (bearer) headers.Authorization = 'Bearer ' + bearer;
  if (data !== undefined) {
    headers['Content-Type'] = 'application/json';
    headers['Idempotency-Key'] = id ?? Crypto.randomUUID();
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 25000);
  try {
    const response = await fetch(API + path, {
      method: data === undefined ? 'GET' : 'POST', headers,
      body: data === undefined ? undefined : JSON.stringify(data), signal: controller.signal,
    });
    if (response.status === 204) return null;
    const result = await response.json();
    if (!response.ok) throw new ApiError(typeof result.detail === 'string' ? result.detail : JSON.stringify(result), response.status);
    return result;
  } finally { clearTimeout(timeout); }
}

export async function photo(path: string, uri: string, moment: string) {
  const body = new FormData();
  body.append('moment', moment);
  body.append('image', { uri, type: 'image/jpeg', name: 'vistoria.jpg' } as any);
  const response = await fetch(API + path, {method:'POST', body, headers:{ Authorization:'Bearer '+ await token() }});
  if (!response.ok) throw new Error('Não foi possível enviar a foto. Tente novamente.');
  return response.json();
}
