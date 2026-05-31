export const mockLlm =
  process.env.NEXT_PUBLIC_MOCK_LLM !== "false" &&
  process.env.NEXT_PUBLIC_MOCK_LLM !== "0";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  process.env.BACKEND_URL ??
  "http://127.0.0.1:8000";
