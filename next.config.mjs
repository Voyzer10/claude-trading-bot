/** Next.js config. On your PC (npm run dev / start_dashboard.bat) /api/py/* goes to the FastAPI server on
 *  127.0.0.1:8000. On Vercel, /api/py/* is served by the Python function in api/index.py. */
const nextConfig = {
  rewrites: async () => [
    {
      source: "/api/py/:path*",
      destination: process.env.VERCEL ? "/api/" : "http://127.0.0.1:8000/api/py/:path*",
    },
  ],
};
export default nextConfig;
