// 封装健康检查接口及其返回类型。
export type HealthStatus = {
  status: "ok";
  version: string;
  docker_available: boolean;
};

export async function fetchHealth(signal?: AbortSignal): Promise<HealthStatus> {
  const response = await fetch("/api/health", { signal });
  if (!response.ok) {
    throw new Error(`健康检查请求失败，状态码：${response.status}`);
  }
  return response.json() as Promise<HealthStatus>;
}
