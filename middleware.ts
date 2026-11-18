import { NextRequest, NextResponse } from "next/server";

/** Optional password: set DASHBOARD_PASSWORD on Vercel and the whole dashboard (pages and the read API)
 *  asks for it (any username). The bot's push to /api/py/ingest uses its own token and is let through. */
export function middleware(req: NextRequest) {
  // The browser re-sends the saved password to this site even from another site's page, so a write
  // (close positions, change settings) must come from the dashboard's own pages. The bot's push sends no Origin.
  if (req.method !== "GET" && req.method !== "HEAD" && !sameOrigin(req)) {
    return new NextResponse("Cross-site request blocked", { status: 403 });
  }
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

function sameOrigin(req: NextRequest) {
  const origin = req.headers.get("origin");
  if (!origin) return true; // not a browser cross-site request (browsers always send Origin on those)
  try {
    return new URL(origin).host === req.headers.get("host");
  } catch {
    return false; // "null" (sandboxed page) or garbage
  }
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
