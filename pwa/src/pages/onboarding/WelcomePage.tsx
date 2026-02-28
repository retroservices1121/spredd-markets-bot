import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

const slides = [
  {
    title: "Predict the Future",
    subtitle: "Trade on real-world events across multiple prediction markets",
    gradient: "mesh-gradient-welcome",
  },
  {
    title: "Swipe & Trade",
    subtitle: "Discover trending markets with a simple swipe — buy Yes or No in seconds",
    gradient: "mesh-gradient-green",
  },
  {
    title: "Track & Win",
    subtitle: "Monitor your portfolio, climb the leaderboard, and earn rewards",
    gradient: "mesh-gradient-feed",
  },
];

export function WelcomePage() {
  const [currentSlide, setCurrentSlide] = useState(0);
  const navigate = useNavigate();

  const handleNext = () => {
    if (currentSlide < slides.length - 1) {
      setCurrentSlide(currentSlide + 1);
    } else {
      navigate("/login");
    }
  };

  return (
    <div className="h-[100dvh] flex flex-col bg-spredd-bg overflow-hidden">
      {/* Slides */}
      <div className="flex-1 relative">
        <AnimatePresence mode="wait">
          <motion.div
            key={currentSlide}
            className={`absolute inset-0 flex flex-col items-center justify-center px-8 text-center ${slides[currentSlide].gradient}`}
            initial={{ opacity: 0, x: 50 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -50 }}
            transition={{ duration: 0.3 }}
          >
            {/* Logo */}
            <h1 className="font-brand text-4xl text-spredd-green mb-12">SPREDD</h1>

            <h2 className="text-3xl font-bold text-white mb-4 leading-tight">
              {slides[currentSlide].title}
            </h2>
            <p className="text-white/60 text-lg max-w-sm">
              {slides[currentSlide].subtitle}
            </p>
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Bottom controls */}
      <div className="px-6 pb-10 pt-4">
        {/* Dots */}
        <div className="flex justify-center gap-2 mb-8">
          {slides.map((_, i) => (
            <button
              key={i}
              onClick={() => setCurrentSlide(i)}
              className={`h-2 rounded-full transition-all ${
                i === currentSlide
                  ? "w-8 bg-spredd-green"
                  : "w-2 bg-white/20"
              }`}
            />
          ))}
        </div>

        <Button size="lg" className="w-full" onClick={handleNext}>
          {currentSlide < slides.length - 1 ? (
            <>
              Next
              <ChevronRight size={18} />
            </>
          ) : (
            "Get Started"
          )}
        </Button>

        {currentSlide < slides.length - 1 && (
          <button
            onClick={() => navigate("/login")}
            className="w-full text-center mt-4 text-white/40 text-sm"
          >
            Skip
          </button>
        )}
      </div>
    </div>
  );
}
