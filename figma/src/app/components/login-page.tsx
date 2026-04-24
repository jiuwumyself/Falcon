import { useState, useRef } from "react";
import { motion } from "motion/react";
import { useNavigate } from "react-router";
import { ParticleCanvas } from "./particle-canvas";
import { FalconLogo } from "./falcon-logo";
import { Eye, EyeOff } from "lucide-react";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [focusedField, setFocusedField] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const btnRef = useRef<HTMLButtonElement>(null);

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setTimeout(() => {
      navigate("/home");
    }, 600);
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#0A0A0A]">
      {/* Left - Particle Nebula */}
      <div className="hidden lg:flex flex-1 relative items-center justify-center overflow-hidden">
        <ParticleCanvas />
        {/* Falcon silhouette hint */}
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <motion.div
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 0.45, scale: 1 }}
            transition={{ duration: 2 }}
          >
            <FalconLogo size={400} />
          </motion.div>
        </div>
        {/* Radial gradient overlay */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse at center, transparent 30%, #0A0A0A 75%)",
          }}
        />
        {/* Branding text */}
        <motion.div
          className="absolute bottom-12 left-12 z-10"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, duration: 0.8 }}
        >
          <p className="text-white/30 tracking-[0.3em] text-[11px] uppercase">
            Precision in Speed
          </p>
        </motion.div>
      </div>

      {/* Right - Login Panel */}
      <div className="flex-1 lg:flex-none lg:w-[520px] flex items-center justify-center relative p-8">
        {/* Subtle gradient bg */}
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(135deg, rgba(59,130,246,0.03) 0%, transparent 50%, rgba(124,58,237,0.03) 100%)",
          }}
        />

        <motion.div
          initial={{ opacity: 0, x: 30 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          className="relative w-full max-w-[380px]"
        >
          {/* Glass Card */}
          <div
            className="relative rounded-[28px] p-10 overflow-hidden"
            style={{
              background: "rgba(255, 255, 255, 0.04)",
              backdropFilter: "blur(40px)",
              WebkitBackdropFilter: "blur(40px)",
              boxShadow:
                "inset 0 1px 0 0 rgba(255,255,255,0.08), inset 0 -1px 0 0 rgba(255,255,255,0.02), 0 20px 60px rgba(0,0,0,0.4)",
              border: "1px solid rgba(255,255,255,0.06)",
            }}
          >
            {/* Logo */}
            <div className="flex items-center gap-3 mb-10">
              <FalconLogo size={36} />
              <div>
                <h1 className="text-white text-[20px] tracking-tight">
                  Falcon Eyes
                </h1>
                <p className="text-white/30 text-[11px] tracking-wider">
                  INTELLIGENT TEST PLATFORM
                </p>
              </div>
            </div>

            <form onSubmit={handleLogin} className="space-y-5">
              {/* Email */}
              <div className="relative">
                <label className="text-white/50 text-[12px] mb-1.5 block tracking-wide">
                  EMAIL
                </label>
                <div className="relative">
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    onFocus={() => setFocusedField("email")}
                    onBlur={() => setFocusedField(null)}
                    placeholder="name@company.com"
                    className="w-full px-4 py-3 rounded-2xl text-white placeholder-white/20 outline-none transition-all duration-300 text-[14px]"
                    style={{
                      background: "rgba(255,255,255,0.04)",
                      border: `1px solid ${focusedField === "email" ? "rgba(59,130,246,0.5)" : "rgba(255,255,255,0.06)"}`,
                      boxShadow:
                        focusedField === "email"
                          ? "0 0 20px rgba(59,130,246,0.1), inset 0 0 20px rgba(59,130,246,0.03)"
                          : "none",
                    }}
                  />
                  {focusedField === "email" && (
                    <motion.div
                      className="absolute inset-0 rounded-2xl pointer-events-none"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      style={{
                        background:
                          "conic-gradient(from 0deg, transparent, rgba(59,130,246,0.15), transparent, rgba(124,58,237,0.15), transparent)",
                        mask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
                        maskComposite: "exclude",
                        WebkitMaskComposite: "xor",
                        padding: "1px",
                      }}
                    />
                  )}
                </div>
              </div>

              {/* Password */}
              <div className="relative">
                <label className="text-white/50 text-[12px] mb-1.5 block tracking-wide">
                  PASSWORD
                </label>
                <div className="relative">
                  <input
                    type={showPass ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onFocus={() => setFocusedField("password")}
                    onBlur={() => setFocusedField(null)}
                    placeholder="Enter your password"
                    className="w-full px-4 py-3 pr-12 rounded-2xl text-white placeholder-white/20 outline-none transition-all duration-300 text-[14px]"
                    style={{
                      background: "rgba(255,255,255,0.04)",
                      border: `1px solid ${focusedField === "password" ? "rgba(59,130,246,0.5)" : "rgba(255,255,255,0.06)"}`,
                      boxShadow:
                        focusedField === "password"
                          ? "0 0 20px rgba(59,130,246,0.1), inset 0 0 20px rgba(59,130,246,0.03)"
                          : "none",
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPass(!showPass)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 transition-colors"
                  >
                    {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              {/* Login Button */}
              <motion.button
                ref={btnRef}
                type="submit"
                disabled={isLoading}
                whileTap={{ scale: 0.97 }}
                className="w-full py-3.5 rounded-2xl text-white relative overflow-hidden cursor-pointer transition-shadow duration-300 mt-3"
                style={{
                  background:
                    "linear-gradient(135deg, #3b82f6, #6366f1, #7c3aed)",
                  boxShadow: "0 8px 30px rgba(59,130,246,0.25)",
                }}
              >
                <span className="relative z-10 text-[14px] tracking-wide">
                  {isLoading ? "Authenticating..." : "Sign In"}
                </span>
                {/* Shimmer */}
                <motion.div
                  className="absolute inset-0"
                  animate={{
                    backgroundPosition: ["200% 0", "-200% 0"],
                  }}
                  transition={{ duration: 3, repeat: Infinity }}
                  style={{
                    background:
                      "linear-gradient(90deg, transparent 30%, rgba(255,255,255,0.1) 50%, transparent 70%)",
                    backgroundSize: "200% 100%",
                  }}
                />
              </motion.button>
            </form>

            {/* Footer */}
            <div className="mt-8 text-center">
              <p className="text-white/20 text-[12px]">
                Don't have an account?{" "}
                <span className="text-blue-400/60 cursor-pointer hover:text-blue-400 transition-colors">
                  Request Access
                </span>
              </p>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  );
}