/** Next.js config: /api/py/* goes to the FastAPI server on 127.0.0.1:8000 (api/index.py). */
const nextConfig = {
  rewrites: async () => [{ source: "/api/py/:path*", destination: "http://127.0.0.1:8000/api/py/:path*" }],
};
export default nextConfig;
