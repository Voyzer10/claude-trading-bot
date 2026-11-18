import { NextRequest, NextResponse } from "next/server";

/** Optional password: set DASHBOARD_PASSWORD on Vercel and the whole dashboard (pages and the read API)
 *  asks for it (any username). The bot's push to /api/py/ingest uses its own token and is let through. */
export function middleware(req: NextRequest) {
  const pass = process.env.DASHBOARD_PASSWORD;
  if (!pass || req.nextUrl.pathname.startsWith("/api/py/ingest")) return NextResponse.next();
  const auth = req.headers.get("authorization") || "";
  if (auth.startsWith("Basic ")) {
    try {
      const [, given] = atob(auth.slice(6)).split(":");
      if (given === pass) return NextResponse.next();
    } catch {
      /* fall through */
    }
  }
  return new NextResponse("Password required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Trader dashboard"' },
  });
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
