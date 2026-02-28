import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { GlassCard } from "@/components/ui/glass-card";
import { useCreateEvent } from "@/hooks/useCreateEvent";
import { useNavigate } from "react-router-dom";

const CATEGORIES = ["Crypto", "Politics", "Sports", "AI", "Economics", "Science", "Entertainment", "Other"];

export function CreateEventPage() {
  const navigate = useNavigate();
  const {
    step,
    formData,
    updateField,
    nextStep,
    prevStep,
    submitting,
    error,
    success,
    handleSubmit,
    reset,
  } = useCreateEvent();

  if (success) {
    return (
      <div className="min-h-[100dvh] bg-spredd-bg flex flex-col items-center justify-center px-8 text-center mesh-gradient-green">
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          className="w-20 h-20 rounded-full bg-spredd-green/10 flex items-center justify-center mb-6"
        >
          <Check className="w-10 h-10 text-spredd-green" />
        </motion.div>
        <h2 className="text-2xl font-bold text-white mb-2">Event Submitted!</h2>
        <p className="text-white/50 mb-8">
          Your event is under review and will be live soon
        </p>
        <Button onClick={() => { reset(); navigate("/"); }}>
          Back to Home
        </Button>
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] bg-spredd-bg pb-24">
      {/* Header */}
      <div className="sticky top-0 z-30 glass-tab-bar px-5 pt-14 pb-3 flex items-center justify-between">
        <button
          onClick={() => (step === 0 ? navigate(-1) : prevStep())}
          className="text-white/60 hover:text-white"
        >
          <ArrowLeft size={24} />
        </button>
        <h1 className="text-lg font-bold text-white">Create Event</h1>
        <div className="w-6" />
      </div>

      {/* Step indicator */}
      <div className="flex gap-2 px-5 py-4">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className={`flex-1 h-1 rounded-full transition-all ${
              i <= step ? "bg-spredd-green" : "bg-white/10"
            }`}
          />
        ))}
      </div>

      <div className="px-5">
        <AnimatePresence mode="wait">
          {/* Step 0: Question */}
          {step === 0 && (
            <motion.div
              key="step-0"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="space-y-5"
            >
              <div>
                <h2 className="text-xl font-bold text-white mb-1">What's the question?</h2>
                <p className="text-sm text-white/40">
                  Write a yes/no question about a future event
                </p>
              </div>

              <div>
                <label className="text-xs text-white/50 mb-1 block">Question</label>
                <Input
                  value={formData.question}
                  onChange={(e) => updateField("question", e.target.value)}
                  className="bg-white/6 border-white/10 text-white h-14 text-lg"
                  placeholder="Will Bitcoin hit $100K by..."
                  autoFocus
                />
              </div>

              <div>
                <label className="text-xs text-white/50 mb-2 block">Category</label>
                <div className="flex flex-wrap gap-2">
                  {CATEGORIES.map((cat) => (
                    <button
                      key={cat}
                      onClick={() => updateField("category", cat)}
                      className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${
                        formData.category === cat
                          ? "bg-spredd-green text-black"
                          : "bg-white/6 text-white/60 hover:bg-white/10"
                      }`}
                    >
                      {cat}
                    </button>
                  ))}
                </div>
              </div>

              <Button
                size="lg"
                className="w-full"
                disabled={!formData.question.trim() || !formData.category}
                onClick={nextStep}
              >
                Next
              </Button>
            </motion.div>
          )}

          {/* Step 1: Details */}
          {step === 1 && (
            <motion.div
              key="step-1"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="space-y-5"
            >
              <div>
                <h2 className="text-xl font-bold text-white mb-1">Add details</h2>
                <p className="text-sm text-white/40">
                  Help others understand how this event will be resolved
                </p>
              </div>

              <div>
                <label className="text-xs text-white/50 mb-1 block">Description</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => updateField("description", e.target.value)}
                  className="w-full h-28 rounded-lg bg-white/6 border border-white/10 text-white text-sm p-3 resize-none focus:outline-none focus:ring-2 focus:ring-spredd-green"
                  placeholder="Describe the event and resolution criteria..."
                />
              </div>

              <div>
                <label className="text-xs text-white/50 mb-1 block">End Date</label>
                <Input
                  type="date"
                  value={formData.end_date}
                  onChange={(e) => updateField("end_date", e.target.value)}
                  className="bg-white/6 border-white/10 text-white"
                />
              </div>

              <div>
                <label className="text-xs text-white/50 mb-1 block">Resolution Source (optional)</label>
                <Input
                  value={formData.resolution_source}
                  onChange={(e) => updateField("resolution_source", e.target.value)}
                  className="bg-white/6 border-white/10 text-white"
                  placeholder="e.g., CoinGecko, AP News..."
                />
              </div>

              <Button
                size="lg"
                className="w-full"
                disabled={!formData.description.trim() || !formData.end_date}
                onClick={nextStep}
              >
                Next
              </Button>
            </motion.div>
          )}

          {/* Step 2: Review */}
          {step === 2 && (
            <motion.div
              key="step-2"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="space-y-5"
            >
              <div>
                <h2 className="text-xl font-bold text-white mb-1">Review & Submit</h2>
                <p className="text-sm text-white/40">
                  Check your event details before submitting
                </p>
              </div>

              <GlassCard className="space-y-3">
                <div>
                  <p className="text-xs text-white/40">Question</p>
                  <p className="text-sm font-medium text-white">{formData.question}</p>
                </div>
                <div>
                  <p className="text-xs text-white/40">Category</p>
                  <p className="text-sm text-white">{formData.category}</p>
                </div>
                <div>
                  <p className="text-xs text-white/40">Description</p>
                  <p className="text-sm text-white/70">{formData.description}</p>
                </div>
                <div>
                  <p className="text-xs text-white/40">End Date</p>
                  <p className="text-sm text-white">{formData.end_date}</p>
                </div>
                {formData.resolution_source && (
                  <div>
                    <p className="text-xs text-white/40">Resolution Source</p>
                    <p className="text-sm text-white">{formData.resolution_source}</p>
                  </div>
                )}
              </GlassCard>

              {error && (
                <p className="text-spredd-red text-sm text-center">{error}</p>
              )}

              <Button
                size="lg"
                className="w-full"
                disabled={submitting}
                onClick={handleSubmit}
              >
                {submitting ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Submitting...
                  </>
                ) : (
                  "Submit Event"
                )}
              </Button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
