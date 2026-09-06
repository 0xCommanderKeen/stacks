import type { components } from './schema';

export type Book = components['schemas']['WorkOut'];
export type Page = components['schemas']['CatalogPage'];
export type ImportResult = components['schemas']['ImportResult'];
export type WorkEdit = components['schemas']['WorkEdit'];
export type Status = components['schemas']['StatusOut'];

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { 'X-Stacks-Request': '1', ...init.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      typeof body?.detail === 'string' ? body.detail : 'The request could not be completed.',
      response.status,
    );
  }
  return response;
}

export async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await request(path, init)).json();
}

export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
