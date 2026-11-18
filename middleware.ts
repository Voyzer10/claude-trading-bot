import { NextRequest, NextResponse } from "next/server";

/** Password: with DASHBOARD_PASSWORD set (start_dashboard.bat, or /etc/trader/trader.env on the VPS) the whole
 *  dashboard, pages and API, asks for it (any username). */
export function middleware(req: NextRequest) {
  // The browser re-sends the saved password to this site even from another site's page, so a write
  // (close positions, change settings) must come from the dashboard's own pages.
  if (req.method !== "GET" && req.method !== "HEAD" && !sameOrigin(req)) {
    return new NextResponse("Cross-site request blocked", { status: 403 });
  }
  const pass = process.env.DASHBOARD_PASSWORD;
  if (!pass) return NextResponse.next();
  const auth = req.headers.get("authorization") || "";
  if (auth.startsWith("Basic ")) {
    try {
      const userPass = atob(auth.slice(6));
      if (userPass.slice(userPass.indexOf(":") + 1) === pass) return NextResponse.next(); // the password may contain ":"
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
