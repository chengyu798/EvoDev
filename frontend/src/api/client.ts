export type HealthStatus = {
  status: "ok";
  version: string;
  docker_available: boolean;
};

export async function fetchHealth(signal?: AbortSignal): Promise<HealthStatus> {
  const response = await fetch("/api/health", { signal });
  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`);
  }
  return response.json() as Promise<HealthStatus>;
}
