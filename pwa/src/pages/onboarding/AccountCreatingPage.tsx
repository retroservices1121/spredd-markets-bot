import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

const steps = [
  "Creating your account",
  "Setting up wallets",
  "Configuring preferences",
  "Almost there...",
];

export function AccountCreatingPage() {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState(0);

  useEffect(() => {
    const timers = steps.map((_, i) =>
      setTimeout(() => {
        setCurrentStep(i + 1);
      }, (i + 1) * 800)
    );

    const finalTimer = setTimeout(() => {
      navigate("/", { replace: true });
    }, steps.length * 800 + 500);

    return () => {
      timers.forEach(clearTimeout);
      clearTimeout(finalTimer);
    };
  }, [navigate]);

  return (
    <div className="h-[100dvh] flex flex-col items-center justify-center bg-spredd-bg mesh-gradient-welcome px-8">
      {/* Logo */}
      <motion.h1
        className="font-brand text-4xl text-spredd-green mb-12"
        animate={{ scale: [1, 1.05, 1] }}
        transition={{ duration: 2, repeat: Infinity }}
      >
        SPREDD
      </motion.h1>

      {/* Steps */}
      <div className="w-full max-w-xs space-y-4">
        {steps.map((step, i) => (
          <motion.div
            key={step}
            className="flex items-center gap-3"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.2 }}
          >
            <div
              className={cn(
                "w-6 h-6 rounded-full flex items-center justify-center transition-all duration-300",
                currentStep > i
                  ? "bg-spredd-green"
                  : "bg-white/10"
              )}
            >
              {currentStep > i ? (
                <Check size={14} className="text-black" />
              ) : (
                <motion.div
                  className="w-2 h-2 rounded-full bg-white/30"
                  animate={currentStep === i ? { scale: [1, 1.5, 1] } : {}}
                  transition={{ duration: 0.8, repeat: Infinity }}
                />
              )}
            </div>
            <span
              className={cn(
                "text-sm transition-colors",
                currentStep > i ? "text-white" : "text-white/40"
              )}
            >
              {step}
            </span>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
