import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Shield, Key, CheckCircle2, Loader2, AlertCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTelegram } from "@/contexts/TelegramContext";
import { createWallet } from "@/lib/api";
import { toast } from "sonner";

interface WalletSetupPageProps {
  onComplete: () => void;
}

export default function WalletSetupPage({ onComplete }: WalletSetupPageProps) {
  const { initData, hapticFeedback } = useTelegram();
  const [pin, setPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [step, setStep] = useState<"intro" | "pin" | "confirm" | "creating">("intro");

  const createWalletMutation = useMutation({
    mutationFn: () => createWallet(initData, pin),
    onSuccess: () => {
      hapticFeedback("success");
      toast.success("Wallets created successfully!");
      setStep("creating");
      // Brief delay to show success state
      setTimeout(() => {
        onComplete();
      }, 1500);
    },
    onError: (error: Error) => {
      hapticFeedback("error");
      toast.error(error.message);
      setStep("pin");
    },
  });

  const handlePinChange = (value: string) => {
    // Only allow digits
    const digits = value.replace(/\D/g, "").slice(0, 6);
    setPin(digits);
  };

  const handleConfirmPinChange = (value: string) => {
    const digits = value.replace(/\D/g, "").slice(0, 6);
    setConfirmPin(digits);
  };

  const handleNext = () => {
    hapticFeedback("light");
    if (step === "intro") {
      setStep("pin");
    } else if (step === "pin") {
      if (pin.length < 4) {
        toast.error("PIN must be at least 4 digits");
        return;
      }
      setStep("confirm");
    } else if (step === "confirm") {
      if (pin !== confirmPin) {
        toast.error("PINs do not match");
        hapticFeedback("error");
        return;
      }
      setStep("creating");
      createWalletMutation.mutate();
    }
  };

  const handleBack = () => {
    hapticFeedback("light");
    if (step === "confirm") {
      setConfirmPin("");
      setStep("pin");
    } else if (step === "pin") {
      setPin("");
      setStep("intro");
    }
  };

  return (
    <div className="min-h-screen p-4 flex flex-col">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center mb-6"
      >
        <h1 className="text-2xl font-bold mb-2">Welcome to Spredd</h1>
        <p className="text-white/60">Let's set up your wallets</p>
      </motion.div>

      {/* Progress Indicator */}
      <div className="flex justify-center gap-2 mb-6">
        {["intro", "pin", "confirm"].map((s, i) => (
          <div
            key={s}
            className={`w-2 h-2 rounded-full transition-colors ${
              step === s || (step === "creating" && i === 2)
                ? "bg-spredd-orange"
                : i < ["intro", "pin", "confirm"].indexOf(step)
                ? "bg-spredd-orange/50"
                : "bg-white/20"
            }`}
          />
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 flex flex-col justify-center">
        {step === "intro" && (
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
          >
            <Card className="bg-gradient-to-br from-spredd-dark to-spredd-black">
              <CardContent className="p-6 space-y-6">
                <div className="w-16 h-16 rounded-full bg-spredd-orange/20 flex items-center justify-center mx-auto">
                  <Shield className="w-8 h-8 text-spredd-orange" />
                </div>

                <div className="text-center">
                  <h2 className="text-xl font-bold mb-2">Secure & Non-Custodial</h2>
                  <p className="text-white/60 text-sm">
                    Your wallets are encrypted and only you can access your private keys.
                  </p>
                </div>

                <div className="space-y-3">
                  <div className="flex items-start gap-3 text-sm">
                    <CheckCircle2 className="w-5 h-5 text-spredd-green shrink-0 mt-0.5" />
                    <div>
                      <p className="font-medium">Two Wallets Created</p>
                      <p className="text-white/60">One for Solana (Kalshi) and one for EVM chains (Polymarket, Opinion)</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3 text-sm">
                    <CheckCircle2 className="w-5 h-5 text-spredd-green shrink-0 mt-0.5" />
                    <div>
                      <p className="font-medium">PIN Protection</p>
                      <p className="text-white/60">Your PIN protects private key exports (not needed for trading)</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3 text-sm">
                    <CheckCircle2 className="w-5 h-5 text-spredd-green shrink-0 mt-0.5" />
                    <div>
                      <p className="font-medium">Trade Instantly</p>
                      <p className="text-white/60">No PIN required for trading - fast and seamless</p>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {step === "pin" && (
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
          >
            <Card>
              <CardContent className="p-6 space-y-6">
                <div className="w-16 h-16 rounded-full bg-spredd-orange/20 flex items-center justify-center mx-auto">
                  <Key className="w-8 h-8 text-spredd-orange" />
                </div>

                <div className="text-center">
                  <h2 className="text-xl font-bold mb-2">Create Your PIN</h2>
                  <p className="text-white/60 text-sm">
                    Enter a 4-6 digit PIN to protect your private key exports
                  </p>
                </div>

                <div className="space-y-4">
                  <Input
                    type="password"
                    inputMode="numeric"
                    placeholder="Enter PIN (4-6 digits)"
                    value={pin}
                    onChange={(e) => handlePinChange(e.target.value)}
                    className="text-center text-2xl tracking-widest"
                    maxLength={6}
                  />

                  <div className="flex justify-center gap-1">
                    {[0, 1, 2, 3, 4, 5].map((i) => (
                      <div
                        key={i}
                        className={`w-3 h-3 rounded-full ${
                          i < pin.length ? "bg-spredd-orange" : "bg-white/20"
                        }`}
                      />
                    ))}
                  </div>

                  <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="w-4 h-4 text-yellow-500 shrink-0 mt-0.5" />
                      <p className="text-xs text-yellow-500/80">
                        Remember this PIN! You'll need it to export your private keys.
                        If you forget it, you cannot export your keys (but can still trade).
                      </p>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {step === "confirm" && (
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
          >
            <Card>
              <CardContent className="p-6 space-y-6">
                <div className="w-16 h-16 rounded-full bg-spredd-orange/20 flex items-center justify-center mx-auto">
                  <Key className="w-8 h-8 text-spredd-orange" />
                </div>

                <div className="text-center">
                  <h2 className="text-xl font-bold mb-2">Confirm Your PIN</h2>
                  <p className="text-white/60 text-sm">
                    Enter your PIN again to confirm
                  </p>
                </div>

                <div className="space-y-4">
                  <Input
                    type="password"
                    inputMode="numeric"
                    placeholder="Confirm PIN"
                    value={confirmPin}
                    onChange={(e) => handleConfirmPinChange(e.target.value)}
                    className="text-center text-2xl tracking-widest"
                    maxLength={6}
                  />

                  <div className="flex justify-center gap-1">
                    {[0, 1, 2, 3, 4, 5].map((i) => (
                      <div
                        key={i}
                        className={`w-3 h-3 rounded-full ${
                          i < confirmPin.length
                            ? confirmPin[i] === pin[i]
                              ? "bg-spredd-green"
                              : "bg-spredd-red"
                            : "bg-white/20"
                        }`}
                      />
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {step === "creating" && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
          >
            <Card>
              <CardContent className="p-6 text-center space-y-4">
                {createWalletMutation.isPending ? (
                  <>
                    <Loader2 className="w-12 h-12 text-spredd-orange mx-auto animate-spin" />
                    <div>
                      <h2 className="text-xl font-bold">Creating Wallets...</h2>
                      <p className="text-white/60 text-sm mt-1">
                        Generating your secure wallets
                      </p>
                    </div>
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="w-12 h-12 text-spredd-green mx-auto" />
                    <div>
                      <h2 className="text-xl font-bold">Wallets Created!</h2>
                      <p className="text-white/60 text-sm mt-1">
                        You're all set to start trading
                      </p>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </motion.div>
        )}
      </div>

      {/* Action Buttons */}
      {step !== "creating" && (
        <div className="space-y-3 mt-6">
          <Button
            onClick={handleNext}
            className="w-full"
            size="lg"
            disabled={
              (step === "pin" && pin.length < 4) ||
              (step === "confirm" && confirmPin.length < 4)
            }
          >
            {step === "intro" && "Get Started"}
            {step === "pin" && "Continue"}
            {step === "confirm" && "Create Wallets"}
          </Button>

          {step !== "intro" && (
            <Button
              variant="ghost"
              onClick={handleBack}
              className="w-full"
            >
              Back
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
