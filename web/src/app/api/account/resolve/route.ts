import { NextResponse } from "next/server";
import { API_BASE_URL } from "@/lib/env";

export const dynamic = "force-dynamic";

export async function POST(req: Request): Promise<NextResponse> {
  const body = (await req.json()) as { api_key?: string };
  if (!body?.api_key) {
    return NextResponse.json({ detail: "api_key required" }, { status: 400 });
  }
  const upstream = await fetch(`${API_BASE_URL}/api/v1/account`, {
    method: "GET",
    headers: { Authorization: `Bearer ${body.api_key}` },
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
