/** Next.js config. On the VPS / your PC (npm start / npm run dev) /api/py/* goes to the FastAPI server on
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
